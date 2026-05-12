"""
yolo_exporter.py  —  Export YOLO dataset from dust scan images.
All thresholds and class names are now read from config.cfg.
"""

from __future__ import annotations

import cv2
import random
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import NamedTuple

from config import cfg


# ── Backward-compatible aliases ───────────────────────────────────────────────
# main_from_ui.py imports these names directly; they now proxy cfg so they
# always reflect the current config without touching the UI code.
@property  # type: ignore[misc]
def CLASS_NAMES() -> list[str]:          # noqa: N802
    return cfg.yolo.class_names

# For module-level attribute access (not descriptor), expose as plain references
# that are re-evaluated from cfg at import time and updated if cfg changes.
# Simplest approach: make them module-level properties via a small proxy object,
# but since Python doesn't support module-level properties we use __getattr__.

def __getattr__(name: str):
    """
    Lazily resolve legacy constant names so existing imports keep working:
        from yolo_exporter import CLASS_NAMES, DEFAULT_CLASS_ID, FINE_MAX_PX, COARSE_MIN_PX
    """
    if name == "CLASS_NAMES":
        return cfg.yolo.class_names
    if name == "DEFAULT_CLASS_ID":
        return 0
    if name == "FINE_MAX_PX":
        return cfg.yolo.fine_max_px
    if name == "COARSE_MIN_PX":
        return cfg.yolo.coarse_min_px
    raise AttributeError(f"module 'yolo_exporter' has no attribute {name!r}")


def auto_classify_particle(w_px: int, h_px: int) -> int:
    """
    Auto-assign class_id by bounding-box size (longest edge).
        < fine_max_px               → 0  dust_fine
        fine_max_px .. coarse_min_px → 1  dust_medium
        >= coarse_min_px             → 2  dust_coarse
    """
    y = cfg.yolo
    max_dim = max(w_px, h_px)
    if max_dim < y.fine_max_px:
        return 0
    elif max_dim < y.coarse_min_px:
        return 1
    else:
        return 2


class ParticleBox(NamedTuple):
    cx:   int
    cy:   int
    w:    int
    h:    int
    area: int


class YoloExporter:
    """
    Collect scans then write a YOLO-format dataset with export().

    Usage:
        exporter = YoloExporter()
        scan_idx = exporter.add_scan(crop_bgr, particles, roi)
        exporter.set_particle_class(scan_idx, particle_id, class_id)
        exporter.export()          # uses cfg.yolo.default_output_dir
    """

    def __init__(self):
        self._scans: list[dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def add_scan(self, crop_bgr: np.ndarray,
                 particles: list[dict],
                 roi: tuple) -> int:
        if len(particles) == 0:
            return -1
        labels = {
            p["id"]: auto_classify_particle(p.get("w_px", 0), p.get("h_px", 0))
            for p in particles
        }
        self._scans.append({
            "crop":      crop_bgr.copy(),
            "particles": list(particles),
            "roi":       roi,
            "labels":    labels,
        })
        return len(self._scans) - 1

    def set_particle_class(self, scan_index: int,
                           particle_id: int,
                           class_id: int) -> None:
        if 0 <= scan_index < len(self._scans):
            self._scans[scan_index]["labels"][particle_id] = class_id

    def get_particle_class(self, scan_index: int, particle_id: int) -> int:
        if 0 <= scan_index < len(self._scans):
            return self._scans[scan_index]["labels"].get(particle_id, 0)
        return 0

    def get_label_stats(self, scan_index: int) -> dict:
        if not (0 <= scan_index < len(self._scans)):
            return {}
        from collections import Counter
        return dict(Counter(self._scans[scan_index]["labels"].values()))

    def clear(self) -> None:
        self._scans.clear()

    def count(self) -> int:
        return len(self._scans)

    def export(self, out_dir: str | Path | None = None) -> dict:
        """Write full dataset to disk. out_dir defaults to cfg.yolo.default_output_dir."""
        y = cfg.yolo
        out_dir = Path(out_dir) if out_dir is not None else Path(y.default_output_dir)

        for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
            (out_dir / sub).mkdir(parents=True, exist_ok=True)

        indices  = list(range(len(self._scans)))
        random.shuffle(indices)
        n_train  = max(1, int(len(indices) * y.train_ratio))
        train_idx = set(indices[:n_train])

        stats = {"images": 0, "labels": 0, "crops": 0,
                 "train": 0, "val": 0, "skipped": 0}
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        for seq_i, orig_i in enumerate(indices):
            scan      = self._scans[orig_i]
            crop      = scan["crop"]
            particles = scan["particles"]
            labels    = scan["labels"]
            split     = "train" if orig_i in train_idx else "val"

            h_img, w_img = crop.shape[:2]
            if w_img == 0 or h_img == 0:
                stats["skipped"] += 1
                continue

            stem = f"{ts}_scan{seq_i:04d}"

            # ── Image ─────────────────────────────────────────────────────────
            img_path = out_dir / "images" / split / f"{stem}.jpg"
            cv2.imwrite(str(img_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            stats["images"] += 1
            stats[split]    += 1

            # ── YOLO labels ───────────────────────────────────────────────────
            lbl_path  = out_dir / "labels" / split / f"{stem}.txt"
            lbl_lines = []
            for p in particles:
                box = self._particle_to_yolo(p, w_img, h_img)
                if box:
                    cls = labels.get(p["id"], 0)
                    lbl_lines.append(
                        f"{cls} {box[0]:.6f} {box[1]:.6f} "
                        f"{box[2]:.6f} {box[3]:.6f}"
                    )
            lbl_path.write_text("\n".join(lbl_lines))
            stats["labels"] += 1

            # ── Per-particle crops ────────────────────────────────────────────
            for p_i, p in enumerate(particles):
                crop_img = self._crop_particle(crop, p)
                if crop_img is not None:
                    cls      = labels.get(p["id"], 0)
                    cls_name = (y.class_names[cls]
                                if cls < len(y.class_names) else f"class{cls}")
                    c_dir = out_dir / "crops" / cls_name
                    c_dir.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(c_dir / f"{stem}_p{p_i+1:03d}.jpg"),
                                crop_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    stats["crops"] += 1

        # ── dataset.yaml ──────────────────────────────────────────────────────
        (out_dir / "dataset.yaml").write_text(
            f"# Auto-generated by DustInspector — {ts}\n"
            f"path: {out_dir.resolve()}\n"
            f"train: images/train\n"
            f"val:   images/val\n\n"
            f"nc: {len(y.class_names)}\n"
            f"names: {y.class_names}\n"
        )

        return stats

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _particle_to_yolo(p: dict, img_w: int, img_h: int) -> tuple | None:
        min_px = cfg.yolo.min_box_px
        cx, cy = p.get("cx", 0), p.get("cy", 0)
        w,  h  = p.get("w_px", 0), p.get("h_px", 0)
        if w <= min_px or h <= min_px or img_w <= 0 or img_h <= 0:
            return None
        x1  = max(0, cx - w // 2)
        y1  = max(0, cy - h // 2)
        x2  = min(img_w, x1 + w)
        y2  = min(img_h, y1 + h)
        bcx = (x1 + x2) / 2
        bcy = (y1 + y2) / 2
        return (bcx / img_w, bcy / img_h, (x2-x1) / img_w, (y2-y1) / img_h)

    @staticmethod
    def _crop_particle(crop: np.ndarray, p: dict) -> np.ndarray | None:
        pad = cfg.yolo.crop_padding
        min_px = cfg.yolo.min_box_px
        cx, cy = p.get("cx", 0), p.get("cy", 0)
        w,  h  = p.get("w_px", 0), p.get("h_px", 0)
        if w <= min_px or h <= min_px:
            return None
        ih, iw = crop.shape[:2]
        x1 = max(0, cx - w // 2 - pad)
        y1 = max(0, cy - h // 2 - pad)
        x2 = min(iw, cx + w // 2 + pad)
        y2 = min(ih, cy + h // 2 + pad)
        if x2 <= x1 or y2 <= y1:
            return None
        return crop[y1:y2, x1:x2].copy()
