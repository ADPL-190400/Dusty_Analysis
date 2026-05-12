"""
theme_manager.py — Dark / Light Mode palettes + i18n loader
"""

from __future__ import annotations
import json
from pathlib import Path


# ── Language loader ───────────────────────────────────────────────────────────

LANG_DIR = Path(__file__).parent / "lang"

def load_lang(code: str = "en") -> dict:
    """Load translation dict from lang/<code>.json."""
    path = LANG_DIR / f"{code}.json"
    if not path.exists():
        path = LANG_DIR / "en.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Font sizes — chỉnh tại đây để thay đổi toàn bộ UI ───────────────────────
#
#   FONT_SIZES["base"]        : font chính toàn app  (label, button, table…)
#   FONT_SIZES["small"]       : chú thích, header bảng, status bar
#   FONT_SIZES["section"]     : tiêu đề section (LIVE METRICS, HISTORY…)
#   FONT_SIZES["metric_value"]: số lớn density / count
#   FONT_SIZES["status"]      : dải trạng thái CLEAN / HEAVY DUST…
#   FONT_SIZES["title"]       : tên app trên top bar

FONT_SIZES = {
    "base":         20, # ← tăng lên 14-15 nếu muốn to hơn
    "small":        14,
    "section":      14,
    "metric_value": 36,   # ← số density / count
    "status":       20,   # ← badge CLEAN / HEAVY DUST
    "title":        16,
}


# ── Color palettes ────────────────────────────────────────────────────────────

DARK = {
    # Backgrounds
    "bg_root":      "#0D0F14",
    "bg_topbar":    "#080A0D",
    "bg_card":      "#151820",
    "bg_input":     "#1E2330",
    "bg_video":     "#080A0D",
    "bg_metric":    "#0D0F14",
    "bg_statusbar": "#080A0D",

    # Borders
    "border_card":    "#252A35",
    "border_input":   "#2E3545",
    "border_accent":  "#00C8FF",
    "border_subtle":  "#1E2330",

    # Text
    "text_primary":   "#C8CDD8",
    "text_secondary": "#5A6070",
    "text_bright":    "#E8EAF0",
    "text_white":     "#FFFFFF",

    # Accent / action colors (keep same in both modes)
    "accent_cyan":    "#00C8FF",
    "accent_green":   "#00FF9C",
    "accent_yellow":  "#FFD600",
    "accent_orange":  "#FF8C00",
    "accent_red":     "#FF3366",

    # Button backgrounds
    "btn_cyan_bg":    "#003D55",
    "btn_cyan_hover": "#00516E",
    "btn_green_bg":   "#003D1E",
    "btn_green_hover":"#005128",
    "btn_red_bg":     "#3D0015",
    "btn_red_hover":  "#55001E",
    "btn_yellow_bg":  "#1A1500",
    "btn_yellow_hover":"#2A2000",
    "btn_orange_bg":  "#3D1500",
    "btn_orange_hover":"#5A1E00",

    # Table / history
    "history_cur_bg":   "#003040",
    "history_cur_fg":   "#00C8FF",
    "history_other_bg": "#151820",
    "history_other_fg": "#5A6070",
    "scan_cur_bg":      "#0A1520",
    "scan_other_bg":    "#080A0D",

    # Misc
    "disabled_fg":    "#3A3F50",
    "disabled_bg":    "#1E2330",
    "disabled_border":"#1E2330",
    "topbar_border":  "#00C8FF",
    "scrollbar_bg":   "#0D0F14",
    "scrollbar_handle":"#2E3545",
    "splitter":       "#1E2330",
    "grid":           "#1E2330",
    "table_row_border":"#1A1E28",
    "table_select_bg": "#003D55",
    "header_bg":       "#151820",
    "header_fg":       "#5A6070",
    "header_border":   "#00C8FF",
}

LIGHT = {
    # Backgrounds
    "bg_root":      "#F0F2F5",
    "bg_topbar":    "#FFFFFF",
    "bg_card":      "#FFFFFF",
    "bg_input":     "#F0F2F5",
    "bg_video":     "#E0E4EC",
    "bg_metric":    "#F8F9FB",
    "bg_statusbar": "#FFFFFF",

    # Borders
    "border_card":    "#D0D4DE",
    "border_input":   "#B8BEC8",
    "border_accent":  "#007BB5",
    "border_subtle":  "#D8DCE6",

    # Text
    "text_primary":   "#000000",
    "text_secondary": "#000000",
    "text_bright":    "#0048FF",
    "text_white":     "#000000",

    # Accent / action colors (slightly deepened for light bg readability)
    "accent_cyan":    "#007BB5",
    "accent_green":   "#00A060",
    "accent_yellow":  "#C09000",
    "accent_orange":  "#C05000",
    "accent_red":     "#CC1044",

    # Button backgrounds
    "btn_cyan_bg":    "#D0EAF5",
    "btn_cyan_hover": "#B0D8EE",
    "btn_green_bg":   "#D0F0E0",
    "btn_green_hover":"#B0E8CC",
    "btn_red_bg":     "#F5D0D8",
    "btn_red_hover":  "#EEB8C4",
    "btn_yellow_bg":  "#F5EAC0",
    "btn_yellow_hover":"#EEE0A8",
    "btn_orange_bg":  "#F5E0C8",
    "btn_orange_hover":"#EED0B0",

    # Table / history
    "history_cur_bg":   "#CCE8F5",
    "history_cur_fg":   "#005A8A",
    "history_other_bg": "#FFFFFF",
    "history_other_fg": "#616161",
    "scan_cur_bg":      "#E8F4FB",
    "scan_other_bg":    "#F8F9FB",

    # Misc
    "disabled_fg":    "#B0B8C8",
    "disabled_bg":    "#E8EAF0",
    "disabled_border":"#D0D4DE",
    "topbar_border":  "#007BB5",
    "scrollbar_bg":   "#E8EAF0",
    "scrollbar_handle":"#B0B8C8",
    "splitter":       "#D0D4DE",
    "grid":           "#D0D4DE",
    "table_row_border":"#E0E4EC",
    "table_select_bg": "#CCE8F5",
    "header_bg":       "#F0F2F5",
    "header_fg":       "#7A8090",
    "header_border":   "#007BB5",
}


def build_stylesheet(p: dict, f: dict | None = None) -> str:
    """
    Generate a full QSS stylesheet from a palette dict.
    f  — font sizes dict (defaults to FONT_SIZES if None)
    Call with DARK or LIGHT.
    """
    if f is None:
        f = FONT_SIZES
    return f"""
/* ── Foundations ── */
QMainWindow, QWidget {{
    background-color: {p['bg_root']};
    color: {p['text_primary']};
    font-family: "Consolas", "Courier New", monospace;
    font-size: {f['base']}px;
}}

/* ── Panels / Cards ── */
QFrame#card, QFrame#cardLeft, QFrame#cardRight,
QFrame#cardControls, QFrame#cardMetrics, QFrame#cardHistory {{
    background-color: {p['bg_card']};
    border: 1px solid {p['border_card']};
    border-radius: 6px;
}}

/* ── Top bar ── */
QFrame#topBar {{
    background-color: {p['bg_topbar']};
    border: none;
    border-bottom: 2px solid {p['topbar_border']};
    border-radius: 0px;
}}

/* ── Labels ── */
QLabel#lblTitle {{
    color: {p['accent_cyan']};
    font-size: {f['title']}px;
    font-weight: bold;
    letter-spacing: 5px;
}}
QLabel#lblSectionCamera,
QLabel#lblSectionRoi,
QLabel#lblSectionMetrics,
QLabel#lblSectionHistory {{
    color: {p['accent_cyan']};
    font-size: {f['small']}px;
    font-weight: bold;
    letter-spacing: 3px;
}}
QLabel#lblDensityValue,
QLabel#lblCountValue {{
    color: {p['text_bright']};
    font-size: {f['metric_value']}px;
    font-weight: bold;
    font-family: "Consolas", monospace;
    background-color: transparent;
}}
QLabel#lblDensityUnit,
QLabel#lblDensityTitle,
QLabel#lblCountTitle {{
    color: {p['text_secondary']};
    font-size: {f['small']}px;
    letter-spacing: 2px;
    background-color: transparent;
}}
QLabel#lblStatus {{
    color: {p['accent_green']};
    font-size: {f['status']}px;
    font-weight: bold;
    border: 1px solid {p['border_subtle']};
    border-radius: 4px;
    background-color: {p['bg_root']};
    letter-spacing: 4px;
    padding: 8px;
}}
QLabel#lblVideoFeed {{
    background-color: {p['bg_video']};
    border: 1px solid {p['border_subtle']};
    border-radius: 4px;
}}
QLabel#lblCameraText {{
    color: {p['text_primary']};
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {p['bg_input']};
    color: {p['text_primary']};
    border: 1px solid {p['border_input']};
    border-radius: 4px;
    padding: 8px 18px;
    font-family: "Consolas", monospace;
    font-size: {f['base']-1}px;
    letter-spacing: 1px;
}}
QPushButton:hover  {{ background-color: {p['btn_cyan_hover']}; border-color: {p['accent_cyan']}; color: {p['text_white']}; }}
QPushButton:pressed {{ background-color: {p['bg_root']}; }}
QPushButton:disabled {{ color: {p['disabled_fg']}; border-color: {p['disabled_border']}; background-color: {p['disabled_bg']}; }}

QPushButton#btnConnect {{
    background-color: {p['btn_cyan_bg']};
    border: 1px solid {p['accent_cyan']};
    color: {p['accent_cyan']};
    font-weight: bold;
    min-width: 110px;
}}
QPushButton#btnConnect:hover {{ background-color: {p['btn_cyan_hover']}; }}

QPushButton#btnReference {{
    background-color: {p['btn_green_bg']};
    border: 1px solid {p['accent_green']};
    color: {p['accent_green']};
    font-weight: bold;
}}
QPushButton#btnReference:hover {{ background-color: {p['btn_green_hover']}; }}
QPushButton#btnReference:disabled {{ color: {p['disabled_fg']}; border-color: {p['disabled_border']}; background-color: {p['disabled_bg']}; }}

QPushButton#btnScan {{
    background-color: {p['btn_cyan_bg']};
    border: 1px solid {p['accent_cyan']};
    color: {p['accent_cyan']};
    font-weight: bold;
}}
QPushButton#btnScan:hover {{ background-color: {p['btn_cyan_hover']}; }}
QPushButton#btnScan:disabled {{ color: {p['disabled_fg']}; border-color: {p['disabled_border']}; background-color: {p['disabled_bg']}; }}

QPushButton#btnReset {{
    background-color: {p['btn_red_bg']};
    border: 1px solid {p['accent_red']};
    color: {p['accent_red']};
    font-weight: bold;
}}
QPushButton#btnReset:hover {{ background-color: {p['btn_red_hover']}; }}
QPushButton#btnReset:disabled {{ color: {p['disabled_fg']}; border-color: {p['disabled_border']}; background-color: {p['disabled_bg']}; }}

QPushButton#btnRefresh {{
    background-color: {p['bg_input']};
    border: 1px solid {p['border_input']};
    color: {p['text_secondary']};
    font-size: {f['small']}px;
    padding: 4px 10px;
}}
QPushButton#btnRefresh:hover {{ color: {p['text_primary']}; border-color: {p['accent_cyan']}; }}

/* ── Theme / Lang toggle buttons ── */
QPushButton#btnToggleTheme {{
    background-color: {p['bg_input']};
    border: 1px solid {p['border_input']};
    color: {p['text_secondary']};
    font-size: {f['small']}px;
    padding: 4px 10px;
    min-width: 72px;
}}
QPushButton#btnToggleTheme:hover {{ color: {p['text_primary']}; border-color: {p['accent_cyan']}; }}

QPushButton#btnLangEn,
QPushButton#btnLangJa {{
    background-color: {p['bg_input']};
    border: 1px solid {p['border_input']};
    color: {p['text_secondary']};
    font-size: {f['small']}px;
    padding: 4px 10px;
    min-width: 40px;
}}
QPushButton#btnLangEn:hover,
QPushButton#btnLangJa:hover {{ color: {p['text_primary']}; border-color: {p['accent_cyan']}; }}
QPushButton#btnLangEn:checked,
QPushButton#btnLangJa:checked {{
    background-color: {p['btn_cyan_bg']};
    border-color: {p['accent_cyan']};
    color: {p['accent_cyan']};
    font-weight: bold;
}}

/* ── Combo Box ── */
QComboBox {{
    background-color: {p['bg_input']};
    border: 1px solid {p['border_input']};
    border-radius: 4px;
    padding: 6px 10px;
    color: {p['text_primary']};
    min-width: 140px;
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ color: {p['accent_cyan']}; }}
QComboBox QAbstractItemView {{
    background-color: {p['bg_input']};
    selection-background-color: {p['btn_cyan_bg']};
    border: 1px solid {p['accent_cyan']};
    color: {p['text_primary']};
}}

/* ── Progress Bar ── */
QProgressBar {{
    background-color: {p['bg_input']};
    border: 1px solid {p['border_input']};
    border-radius: 3px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {p['accent_cyan']}; border-radius: 3px; }}

/* ── Table ── */
QTableWidget {{
    background-color: {p['bg_root']};
    gridline-color: {p['grid']};
    border: none;
    font-size: {f['base']-1}px;
}}
QTableWidget::item {{ padding: 6px 10px; border-bottom: 1px solid {p['table_row_border']}; }}
QTableWidget::item:selected {{ background-color: {p['table_select_bg']}; color: {p['text_white']}; }}
QHeaderView::section {{
    background-color: {p['header_bg']};
    color: {p['header_fg']};
    border: none;
    border-bottom: 2px solid {p['header_border']};
    padding: 6px 10px;
    font-size: {f['small']}px;
    letter-spacing: 2px;
}}

/* ── Scroll Bar ── */
QScrollBar:vertical {{
    background: {p['scrollbar_bg']}; width: 6px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['scrollbar_handle']}; border-radius: 3px; min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── Status Bar ── */
QStatusBar {{
    background-color: {p['bg_statusbar']};
    color: {p['text_secondary']};
    font-size: {f['small']}px;
}}
QStatusBar::item {{ border: none; }}

/* ── Splitter ── */
QSplitter::handle {{ background-color: {p['splitter']}; width: 2px; height: 2px; }}

/* ── Toggle Overlay Button ── */
QPushButton#btnToggleOverlay {{
    background-color: {p['btn_cyan_bg']};
    border: 1px solid {p['accent_cyan']};
    color: {p['accent_cyan']};
    font-weight: bold;
    padding: 6px 14px;
    font-size: {f['base']-1}px;
    letter-spacing: 1px;
}}
QPushButton#btnToggleOverlay:hover {{ background-color: {p['btn_cyan_hover']}; }}
QPushButton#btnToggleOverlay:checked {{
    background-color: {p['btn_orange_bg']};
    border: 1px solid {p['accent_orange']};
    color: {p['accent_orange']};
}}
QPushButton#btnToggleOverlay:checked:hover {{ background-color: {p['btn_orange_hover']}; }}
QPushButton#btnToggleOverlay:disabled {{ color: {p['disabled_fg']}; border-color: {p['disabled_border']}; background-color: {p['disabled_bg']}; }}

/* ── Export YOLO Button ── */
QPushButton#btnExportYolo {{
    background-color: {p['btn_yellow_bg']};
    border: 1px solid {p['accent_yellow']};
    color: {p['accent_yellow']};
    font-weight: bold;
    padding: 6px 14px;
    font-size: {f['base']-1}px;
    letter-spacing: 1px;
}}
QPushButton#btnExportYolo:hover {{ background-color: {p['btn_yellow_hover']}; }}
QPushButton#btnExportYolo:disabled {{ color: {p['disabled_fg']}; border-color: {p['disabled_border']}; background-color: {p['disabled_bg']}; }}

/* ── Particle table ── */
QTableWidget#tableParticles {{ font-size: {f['small']}px; }}
QLabel#lblSectionParticles {{
    color: {p['accent_cyan']};
    font-size: {f['small']}px;
    font-weight: bold;
    letter-spacing: 3px;
}}

/* ── Size filter slider ── */
QSlider#sliderSizeFilter::groove:horizontal {{
    background: {p['bg_input']};
    height: 4px;
    border-radius: 2px;
}}
QSlider#sliderSizeFilter::handle:horizontal {{
    background: {p['accent_cyan']};
    border: 1px solid {p['accent_cyan']};
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider#sliderSizeFilter::sub-page:horizontal {{
    background: {p['accent_cyan']};
    border-radius: 2px;
}}
QLabel#lblSizeFilterTitle {{
    color: {p['text_secondary']};
    font-size: {f['small']}px;
    letter-spacing: 2px;
}}
QLabel#lblSizeFilterValue {{
    color: {p['accent_cyan']};
    font-size: {f['small']}px;
    font-weight: bold;
    min-width: 56px;
}}

/* ── Radio button ── */
QRadioButton {{
    color: {p['text_secondary']};
    font-size: {f['small']}px;
}}
QRadioButton::indicator:checked {{
    background-color: {p['accent_cyan']};
    border: 2px solid {p['accent_cyan']};
    border-radius: 5px;
    width: 8px;
    height: 8px;
}}
QRadioButton::indicator:unchecked {{
    background-color: {p['bg_input']};
    border: 2px solid {p['border_input']};
    border-radius: 5px;
    width: 8px;
    height: 8px;
}}

/* ── Inner metric cards ── */
QFrame#cardDensity, QFrame#cardCount {{
    background-color: {p['bg_metric']};
    border: 1px solid {p['border_card']};
    border-radius: 4px;
}}
"""


def dialog_stylesheet(p: dict) -> str:
    """QSS for ClassPickerDialog (pass palette dict)."""
    return f"""
QDialog {{
    background-color: {p['bg_card']};
    color: {p['text_primary']};
    font-family: 'Consolas', monospace;
}}
QLabel {{ color: {p['text_primary']}; }}
QPushButton {{
    background-color: {p['bg_input']};
    color: {p['text_primary']};
    border: 1px solid {p['border_input']};
    border-radius: 4px;
    padding: 8px 14px;
    font-family: 'Consolas', monospace;
    font-size: 12px;
    text-align: left;
}}
QPushButton:hover {{ background-color: {p['btn_cyan_hover']}; border-color: {p['accent_cyan']}; }}
QPushButton:checked {{
    background-color: {p['btn_cyan_bg']};
    border-color: {p['accent_cyan']};
    color: {p['text_white']};
    font-weight: bold;
}}
QPushButton#btnOk {{
    background-color: {p['btn_green_bg']};
    border-color: {p['accent_green']};
    color: {p['accent_green']};
    font-weight: bold;
    text-align: center;
}}
QPushButton#btnOk:hover {{ background-color: {p['btn_green_hover']}; }}
QPushButton#btnCancel {{
    background-color: {p['bg_input']};
    border-color: {p['border_input']};
    color: {p['text_secondary']};
    text-align: center;
}}
"""
