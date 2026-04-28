"""
yolo_exporter.py — Xuất dataset YOLO từ ảnh scan bụi.

Cấu trúc output (YOLO format):
    yolo_dataset/
    ├── images/
    │   ├── train/   (80%)
    │   └── val/     (20%)
    ├── labels/
    │   ├── train/
    │   └── val/
    ├── dataset.yaml
    └── export_log.txt

Mỗi hạt bụi (particle) → 1 bounding box trong file .txt:
    <class_id> <cx_norm> <cy_norm> <w_norm> <h_norm>

    class_id được gán qua UI (click-to-label). Nếu chưa gán thì dùng
    DEFAULT_CLASS_ID (= 0).

Ngoài ra còn tạo ảnh crop riêng từng hạt bụi vào:
    yolo_dataset/crops/<class_name>/  ← phân thư mục theo class
"""

from __future__ import annotations

import cv2
import random
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import NamedTuple


# ── Constants ────────────────────────────────────────────────────────────────
TRAIN_RATIO      = 0.8
CROP_PADDING     = 6
DEFAULT_CLASS_ID = 0

# Danh sách class — thêm/bớt tùy dự án
CLASS_NAMES = [
    "dust_fine",       # 0 — bụi mịn
    "dust_medium",     # 1 — bụi trung
    "dust_coarse",     # 2 — bụi thô
    "fiber",           # 3 — sợi / fiber
    "contaminant",     # 4 — tạp chất khác
]


class ParticleBox(NamedTuple):
    cx:   int
    cy:   int
    w:    int
    h:    int
    area: int


class YoloExporter:
    """
    Nhận danh sách (image_bgr, particles, roi_tuple) từ mỗi lần scan
    rồi ghi ra chuẩn YOLO khi export().

    Dùng từ MainWindow:
        exporter = YoloExporter()
        scan_idx = exporter.add_scan(crop_bgr, particles, roi)
        exporter.set_particle_class(scan_idx, particle_id, class_id)
        exporter.export("yolo_dataset")
    """

    def __init__(self):
        self._scans: list[dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def add_scan(self, crop_bgr: np.ndarray,
                 particles: list[dict],
                 roi: tuple) -> int:
        """
        Lưu 1 scan. Trả về scan_index dùng cho set_particle_class().
        """
        if len(particles) == 0:
            return -1
        labels = {p["id"]: DEFAULT_CLASS_ID for p in particles}
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
        """Gán class_id cho 1 hạt bụi trong scan scan_index."""
        if 0 <= scan_index < len(self._scans):
            self._scans[scan_index]["labels"][particle_id] = class_id

    def get_particle_class(self, scan_index: int,
                           particle_id: int) -> int:
        if 0 <= scan_index < len(self._scans):
            return self._scans[scan_index]["labels"].get(particle_id, DEFAULT_CLASS_ID)
        return DEFAULT_CLASS_ID

    def get_label_stats(self, scan_index: int) -> dict:
        """Trả về {class_id: count} cho scan đã chọn."""
        if not (0 <= scan_index < len(self._scans)):
            return {}
        from collections import Counter
        return dict(Counter(self._scans[scan_index]["labels"].values()))

    def clear(self) -> None:
        self._scans.clear()

    def count(self) -> int:
        return len(self._scans)

    def export(self, out_dir: str | Path = "yolo_dataset") -> dict:
        """Ghi toàn bộ dataset ra disk."""
        out_dir = Path(out_dir)
        for sub in ["images/train", "images/val",
                    "labels/train", "labels/val"]:
            (out_dir / sub).mkdir(parents=True, exist_ok=True)

        indices   = list(range(len(self._scans)))
        random.shuffle(indices)
        n_train   = max(1, int(len(indices) * TRAIN_RATIO))
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

            # ── Lưu ảnh ───────────────────────────────────────────────────
            img_path = out_dir / "images" / split / f"{stem}.jpg"
            cv2.imwrite(str(img_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            stats["images"] += 1
            stats[split]    += 1

            # ── Lưu label YOLO ────────────────────────────────────────────
            lbl_path  = out_dir / "labels" / split / f"{stem}.txt"
            lbl_lines = []
            for p in particles:
                box = self._particle_to_yolo(p, w_img, h_img)
                if box:
                    cls = labels.get(p["id"], DEFAULT_CLASS_ID)
                    lbl_lines.append(
                        f"{cls} {box[0]:.6f} {box[1]:.6f} "
                        f"{box[2]:.6f} {box[3]:.6f}"
                    )
            lbl_path.write_text("\n".join(lbl_lines))
            stats["labels"] += 1

            # ── Crop từng hạt riêng vào thư mục theo class ────────────────
            for p_i, p in enumerate(particles):
                crop_img = self._crop_particle(crop, p)
                if crop_img is not None:
                    cls      = labels.get(p["id"], DEFAULT_CLASS_ID)
                    cls_name = CLASS_NAMES[cls] if cls < len(CLASS_NAMES) else f"class{cls}"
                    c_dir    = out_dir / "crops" / cls_name
                    c_dir.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(c_dir / f"{stem}_p{p_i+1:03d}.jpg"),
                                crop_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    stats["crops"] += 1

        # ── dataset.yaml ──────────────────────────────────────────────────
        (out_dir / "dataset.yaml").write_text(
            f"# Auto-generated by DustInspector — {ts}\n"
            f"path: {out_dir.resolve()}\n"
            f"train: images/train\n"
            f"val:   images/val\n\n"
            f"nc: {len(CLASS_NAMES)}\n"
            f"names: {CLASS_NAMES}\n"
        )

        return stats

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _particle_to_yolo(p: dict, img_w: int, img_h: int) -> tuple | None:
        cx, cy = p.get("cx", 0), p.get("cy", 0)
        w,  h  = p.get("w_px", 0), p.get("h_px", 0)
        if w <= 20 or h <= 20 or img_w <= 0 or img_h <= 0:
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
        cx, cy = p.get("cx", 0), p.get("cy", 0)
        w,  h  = p.get("w_px", 0), p.get("h_px", 0)
        if w <= 20 or h <= 20:
            return None
        ih, iw = crop.shape[:2]
        x1 = max(0, cx - w // 2 - CROP_PADDING)
        y1 = max(0, cy - h // 2 - CROP_PADDING)
        x2 = min(iw, cx + w // 2 + CROP_PADDING)
        y2 = min(ih, cy + h // 2 + CROP_PADDING)
        if x2 <= x1 or y2 <= y1:
            return None
        return crop[y1:y2, x1:x2].copy()
