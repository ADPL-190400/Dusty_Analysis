"""
config.py  —  Dust Inspector configuration loader.

Đọc config.toml (tìm theo thứ tự ưu tiên bên dưới) rồi expose các
dataclass có kiểu rõ ràng.  Mọi module khác chỉ cần:

    from config import cfg

Thứ tự tìm config.toml:
    1. DUST_INSPECTOR_CONFIG  (biến môi trường)
    2. Thư mục chứa file này  (source tree)
    3. Thư mục hiện tại khi chạy (CWD)
    4. Thư mục cha của thư mục này  (nếu build freeze bằng PyInstaller)

Nếu không tìm thấy file nào, toàn bộ giá trị mặc định được dùng
(an toàn cho CI/test).
"""

from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Try to import tomllib (Python ≥ 3.11) or tomli (backport) ─────────────────
try:
    import tomllib  # type: ignore  # Python 3.11+
    def _load_toml(path: Path) -> dict:
        with open(path, "rb") as f:
            return tomllib.load(f)
except ImportError:
    try:
        import tomli as tomllib  # type: ignore  # pip install tomli
        def _load_toml(path: Path) -> dict:
            with open(path, "rb") as f:
                return tomllib.load(f)
    except ImportError:
        # Fallback: parse thủ công những key đơn giản (không hỗ trợ array inline)
        # Đủ dùng cho TOML flat-value + inline array strings cơ bản.
        log.warning(
            "tomllib/tomli không khả dụng. Dùng parser đơn giản. "
            "Cài tomli để hỗ trợ đầy đủ: pip install tomli"
        )
        def _load_toml(path: Path) -> dict:  # type: ignore[misc]
            return _simple_toml_parse(path)


def _simple_toml_parse(path: Path) -> dict:
    """
    Parser TOML tối giản — hỗ trợ:
      • Section headers [section]
      • key = value  (bool, int, float, string, inline array of strings)
      • Comment # và dòng trắng
    """
    import re
    result: dict = {}
    section: dict = result
    current_key = ""

    bool_map = {"true": True, "false": False}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#")[0].rstrip()  # strip inline comments
        if not line.strip():
            continue

        # Section header
        m = re.match(r"^\[([^\]]+)\]$", line.strip())
        if m:
            current_key = m.group(1).strip()
            result.setdefault(current_key, {})
            section = result[current_key]
            continue

        # key = value
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()

            # Inline array  ["a", "b", ...]
            if v.startswith("["):
                items = re.findall(r'"([^"]*)"', v)
                section[k] = items
                continue

            # Quoted string
            if v.startswith('"') and v.endswith('"'):
                section[k] = v[1:-1]
                continue

            # Bool
            if v.lower() in bool_map:
                section[k] = bool_map[v.lower()]
                continue

            # Number
            try:
                section[k] = int(v)
                continue
            except ValueError:
                pass
            try:
                section[k] = float(v)
                continue
            except ValueError:
                pass

            # Fallback: string without quotes
            section[k] = v

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Dataclasses
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CameraConfig:
    backend:              str   = "gige"
    gige_camera_id:       str   = ""
    gige_pixel_format:    str   = "BayerRG8"
    gige_timeout_ms:      int   = 3000
    gige_packet_size:     int   = 0          # 0 = auto
    sensor_target_height: int   = 1300
    sensor_full_height:   int   = 2448
    sensor_full_width:    int   = 2048
    opencv_camera_index:  int   = 0
    target_fps:           int   = 30


@dataclass
class ExposureConfig:
    mode:             str   = "manual"   # "auto" | "manual"
    exposure_time_us: float = 20_000.0


@dataclass
class CVConfig:
    diff_threshold:     int   = 20
    morph_open_kernel:  int   = 3
    morph_close_kernel: int   = 5
    min_dust_area_px:   int   = 8
    use_clahe:          bool  = True
    clahe_clip:         float = 2.0
    clahe_grid_w:       int   = 8
    clahe_grid_h:       int   = 8
    gaussian_blur_ksize: int  = 3
    threshold_clean:    float = 1.0
    threshold_light:    float = 5.0
    threshold_moderate: float = 15.0

    @property
    def clahe_grid(self) -> tuple[int, int]:
        return (self.clahe_grid_w, self.clahe_grid_h)


@dataclass
class YoloConfig:
    train_ratio:       float      = 0.8
    crop_padding:      int        = 6
    class_names:       list[str]  = field(default_factory=lambda: [
        "dust_fine", "dust_medium", "dust_coarse", "fiber", "contaminant"
    ])
    fine_max_px:       int        = 20
    coarse_min_px:     int        = 60
    min_box_px:        int        = 20
    default_output_dir: str       = "yolo_dataset"


@dataclass
class PathsConfig:
    db_path:   str = "data/inspection_history.db"
    image_dir: str = "data/captures"


@dataclass
class AppConfig:
    camera:   CameraConfig   = field(default_factory=CameraConfig)
    exposure: ExposureConfig = field(default_factory=ExposureConfig)
    cv:       CVConfig       = field(default_factory=CVConfig)
    yolo:     YoloConfig     = field(default_factory=YoloConfig)
    paths:    PathsConfig    = field(default_factory=PathsConfig)

    # Path của file config đang được dùng (None nếu dùng default)
    config_file: Optional[Path] = field(default=None, compare=False)


# ══════════════════════════════════════════════════════════════════════════════
#  Loader
# ══════════════════════════════════════════════════════════════════════════════

def _find_config_file() -> Optional[Path]:
    """Tìm config.toml theo thứ tự ưu tiên."""
    candidates: list[Path] = []

    # 1. Biến môi trường
    env = os.environ.get("DUST_INSPECTOR_CONFIG")
    if env:
        candidates.append(Path(env))

    # 2. Cùng thư mục với config.py (source tree)
    candidates.append(Path(__file__).parent / "config.toml")

    # 3. CWD
    candidates.append(Path.cwd() / "config.toml")

    # 4. Thư mục executable (PyInstaller freeze)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "config.toml")

    for p in candidates:
        if p.exists():
            log.info("Config loaded from: %s", p.resolve())
            return p

    log.warning("config.toml not found — using built-in defaults.")
    return None


def _get(d: dict, *keys, default=None):
    """Lấy giá trị lồng nhau an toàn."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not None else default


def load_config(path: Optional[Path | str] = None) -> AppConfig:
    """
    Load và trả về AppConfig.

    Parameters
    ----------
    path : đường dẫn tường minh tới file TOML.
           None → tự tìm theo thứ tự ưu tiên.
    """
    if path is not None:
        cfg_path = Path(path)
    else:
        cfg_path = _find_config_file()

    if cfg_path is None or not cfg_path.exists():
        return AppConfig()

    try:
        raw = _load_toml(cfg_path)
    except Exception as exc:
        log.error("Không đọc được config.toml (%s): %s — dùng default.", cfg_path, exc)
        return AppConfig()

    cam_raw = raw.get("camera", {})
    exp_raw = raw.get("exposure", {})
    cv_raw  = raw.get("cv", {})
    yolo_raw = raw.get("yolo", {})
    paths_raw = raw.get("paths", {})

    # gige_camera_id: "" hoặc string → None nếu rỗng (để Aravis auto-select)
    gige_id_str = _get(cam_raw, "gige_camera_id", default="")
    gige_id = gige_id_str if gige_id_str else ""

    camera = CameraConfig(
        backend              = _get(cam_raw, "backend",              default="gige"),
        gige_camera_id       = gige_id,
        gige_pixel_format    = _get(cam_raw, "gige_pixel_format",    default="BayerRG8"),
        gige_timeout_ms      = int(_get(cam_raw, "gige_timeout_ms",  default=3000)),
        gige_packet_size     = int(_get(cam_raw, "gige_packet_size", default=0)),
        sensor_target_height = int(_get(cam_raw, "sensor_target_height", default=1300)),
        sensor_full_height   = int(_get(cam_raw, "sensor_full_height",   default=2448)),
        sensor_full_width    = int(_get(cam_raw, "sensor_full_width",    default=2048)),
        opencv_camera_index  = int(_get(cam_raw, "opencv_camera_index",  default=0)),
        target_fps           = int(_get(cam_raw, "target_fps",           default=30)),
    )

    exposure = ExposureConfig(
        mode             = _get(exp_raw, "mode",             default="manual"),
        exposure_time_us = float(_get(exp_raw, "exposure_time_us", default=20_000.0)),
    )

    cv = CVConfig(
        diff_threshold      = int(_get(cv_raw, "diff_threshold",      default=20)),
        morph_open_kernel   = int(_get(cv_raw, "morph_open_kernel",   default=3)),
        morph_close_kernel  = int(_get(cv_raw, "morph_close_kernel",  default=5)),
        min_dust_area_px    = int(_get(cv_raw, "min_dust_area_px",    default=8)),
        use_clahe           = bool(_get(cv_raw, "use_clahe",          default=True)),
        clahe_clip          = float(_get(cv_raw, "clahe_clip",        default=2.0)),
        clahe_grid_w        = int(_get(cv_raw, "clahe_grid_w",        default=8)),
        clahe_grid_h        = int(_get(cv_raw, "clahe_grid_h",        default=8)),
        gaussian_blur_ksize = int(_get(cv_raw, "gaussian_blur_ksize", default=3)),
        threshold_clean     = float(_get(cv_raw, "threshold_clean",   default=1.0)),
        threshold_light     = float(_get(cv_raw, "threshold_light",   default=5.0)),
        threshold_moderate  = float(_get(cv_raw, "threshold_moderate",default=15.0)),
    )

    default_classes = ["dust_fine", "dust_medium", "dust_coarse", "fiber", "contaminant"]
    yolo = YoloConfig(
        train_ratio        = float(_get(yolo_raw, "train_ratio",   default=0.8)),
        crop_padding       = int(_get(yolo_raw, "crop_padding",    default=6)),
        class_names        = list(_get(yolo_raw, "class_names",    default=default_classes)),
        fine_max_px        = int(_get(yolo_raw, "fine_max_px",     default=20)),
        coarse_min_px      = int(_get(yolo_raw, "coarse_min_px",   default=60)),
        min_box_px         = int(_get(yolo_raw, "min_box_px",      default=20)),
        default_output_dir = str(_get(yolo_raw, "default_output_dir", default="yolo_dataset")),
    )

    paths = PathsConfig(
        db_path   = str(_get(paths_raw, "db_path",   default="data/inspection_history.db")),
        image_dir = str(_get(paths_raw, "image_dir", default="data/captures")),
    )

    return AppConfig(
        camera=camera,
        exposure=exposure,
        cv=cv,
        yolo=yolo,
        paths=paths,
        config_file=cfg_path,
    )


# ── Module-level singleton ─────────────────────────────────────────────────────
# Import và dùng ngay:   from config import cfg
cfg: AppConfig = load_config()
