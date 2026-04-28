"""
main_from_ui.py — Dust Inspector v6

Thay đổi so với v5:
  • Click-to-label: sau scan, click vào hạt bụi trên ảnh → dialog chọn class
  • Size filter slider: lọc hạt bụi hiển thị theo kích thước tối thiểu (px²)
  • tableParticles thêm cột CLASS, highlight màu theo class đã gán
  • YOLO export dùng class_id đã gán thay vì luôn = 0
  • _current_scan_index lưu scan_index mới nhất để label sau
"""

from __future__ import annotations
import sys, cv2, numpy as np
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QHeaderView, QTableWidgetItem,
    QWidget, QFileDialog, QMessageBox, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QButtonGroup,
)
from PyQt6.QtCore import pyqtSlot, Qt, QRect, QPropertyAnimation, QEasingCurve, pyqtProperty, QPoint
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter, QPen, QFont
from PyQt6 import uic

UI_FILE = Path(__file__).parent / "dust_inspector.ui"
sys.path.insert(0, str(Path(__file__).parent))
from cv_worker      import CVWorker
from database       import init_db, save_inspection, fetch_history, InspectionRecord
from clickablelabel import ClickableLabel
from yolo_exporter  import YoloExporter, CLASS_NAMES, DEFAULT_CLASS_ID

SCAN_ANIM_MS = 800

STATUS_COLORS = {
    "CLEAN": "#00FF9C", "LIGHT DUST": "#FFD600",
    "MODERATE": "#FF8C00", "HEAVY DUST": "#FF3366",
}

# Màu cho mỗi class (dùng khi vẽ overlay và tô bảng)
CLASS_COLORS = [
    "#00C8FF",   # 0 dust_fine   — xanh lam
    "#FFD600",   # 1 dust_medium — vàng
    "#FF8C00",   # 2 dust_coarse — cam
    "#CC44FF",   # 3 fiber       — tím
    "#FF3366",   # 4 contaminant — đỏ
]

def _class_color(cls_id: int) -> str:
    return CLASS_COLORS[cls_id] if cls_id < len(CLASS_COLORS) else "#C8CDD8"

def _class_name(cls_id: int) -> str:
    return CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else f"class{cls_id}"


# ── Class-picker dialog ───────────────────────────────────────────────────────

class ClassPickerDialog(QDialog):
    """Popup chọn class cho 1 hạt bụi."""

    def __init__(self, particle: dict, current_class: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Gán loại bụi — hạt #{particle['id']}")
        self.setModal(True)
        self.setFixedWidth(320)
        self.chosen_class = current_class

        self.setStyleSheet("""
            QDialog {
                background-color: #151820;
                color: #C8CDD8;
                font-family: 'Consolas', monospace;
            }
            QLabel { color: #C8CDD8; }
            QPushButton {
                background-color: #1E2330;
                color: #C8CDD8;
                border: 1px solid #2E3545;
                border-radius: 4px;
                padding: 8px 14px;
                font-family: 'Consolas', monospace;
                font-size: 12px;
                text-align: left;
            }
            QPushButton:hover { background-color: #252B3B; border-color: #00C8FF; }
            QPushButton:checked {
                background-color: #003D55;
                border-color: #00C8FF;
                color: #FFFFFF;
                font-weight: bold;
            }
            QPushButton#btnOk {
                background-color: #003D1E;
                border-color: #00FF9C;
                color: #00FF9C;
                font-weight: bold;
                text-align: center;
            }
            QPushButton#btnOk:hover { background-color: #005128; }
            QPushButton#btnCancel {
                background-color: #1E2330;
                border-color: #2E3545;
                color: #5A6070;
                text-align: center;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        # Info hạt bụi
        info = QLabel(
            f"  Area: {particle.get('area_px', 0)} px²   "
            f"W: {particle.get('w_px', 0)} px   "
            f"H: {particle.get('h_px', 0)} px"
        )
        info.setStyleSheet("color: #5A6070; font-size: 11px; margin-bottom: 6px;")
        layout.addWidget(info)

        # Buttons chọn class
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for cls_id, cls_name in enumerate(CLASS_NAMES):
            color = _class_color(cls_id)
            btn = QPushButton(f"  ● {cls_name}")
            btn.setCheckable(True)
            btn.setChecked(cls_id == current_class)
            btn.setStyleSheet(
                f"QPushButton {{ color: {color}; border-color: #2E3545; }}"
                f"QPushButton:checked {{ background-color: #1A2030; border-color: {color}; "
                f"  color: {color}; font-weight: bold; }}"
                f"QPushButton:hover {{ border-color: {color}; }}"
            )
            btn.clicked.connect(lambda checked, cid=cls_id: self._select(cid))
            self._btn_group.addButton(btn, cls_id)
            layout.addWidget(btn)

        layout.addSpacing(6)

        # OK / Cancel
        row = QHBoxLayout()
        row.setSpacing(8)
        btn_ok = QPushButton("✔  CONFIRM")
        btn_ok.setObjectName("btnOk")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("CANCEL")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        layout.addLayout(row)

    def _select(self, cls_id: int):
        self.chosen_class = cls_id


# ── Scan-line overlay ────────────────────────────────────────────────────────

class ScanLineWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._y_norm = 0.0; self._active = False; self._cb = None
        self._anim = QPropertyAnimation(self, b"scan_y", self)
        self._anim.setDuration(SCAN_ANIM_MS)
        self._anim.setStartValue(0.0); self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(1); self._anim.finished.connect(self._done)

    def _get_y(self): return self._y_norm
    def _set_y(self, v): self._y_norm = v; self.update()
    scan_y = pyqtProperty(float, _get_y, _set_y)

    def run_once(self, cb=None):
        self._cb = cb; self._active = True
        self._anim.stop(); self._anim.setCurrentTime(0); self.show(); self._anim.start()

    def cancel(self):
        self._anim.stop(); self._active = False; self.hide()

    def _done(self):
        self._active = False; self.hide()
        if self._cb: self._cb()

    def paintEvent(self, _):
        if not self._active: return
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = int(self._y_norm * self.height()); w = self.width()
        for width, alpha in [(22,10),(12,35),(5,120),(2,200),(1,255)]:
            pen = QPen(QColor(0,200,255,alpha)); pen.setWidth(width)
            p.setPen(pen); p.drawLine(0,y,w,y)
        p.end()


# ── History helpers ──────────────────────────────────────────────────────────

def _item(text, color=None, bold=False, bg=None):
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color: it.setForeground(QColor(color))
    if bold: f = it.font(); f.setBold(True); it.setFont(f)
    if bg: it.setBackground(QColor(bg))
    return it

def _extract_session(image_path, timestamp):
    import re
    if image_path:
        m = re.search(r"captures[/\\](\d{8}_\d{6})_scan", image_path)
        if m: return m.group(1)
    try:
        return datetime.strptime(timestamp.strip(), "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d_%H%M")
    except Exception:
        return timestamp[:16].replace(" ","_").replace(":","")

def _populate_history_table(table, all_records, current_session_id):
    from collections import defaultdict
    table.clearContents(); table.setRowCount(0); table.setColumnCount(5)
    session_map = defaultdict(list)
    for r in all_records:
        session_map[_extract_session(r.image_path, r.timestamp)].append(r)
    rows = []
    for sid in sorted(session_map.keys(), reverse=True):
        is_cur = (sid == current_session_id)
        rows.append(("header", sid, is_cur))
        for i,r in enumerate(sorted(session_map[sid], key=lambda x: x.timestamp), 1):
            rows.append(("scan", i, r, is_cur))
    table.setRowCount(len(rows))
    for ri, rd in enumerate(rows):
        if rd[0] == "header":
            _, sid, is_cur = rd
            bg = "#003040" if is_cur else "#151820"
            fg = "#00C8FF" if is_cur else "#5A6070"
            mk = "ACTIVE" if is_cur else ""
            for c in range(5): table.setItem(ri, c, _item("", bg=bg))
            table.setItem(ri, 0, _item(f"{'▶' if is_cur else '▷'} {mk} SESSION {sid}", color=fg, bold=True, bg=bg))
            table.setSpan(ri, 0, 1, 5); table.setRowHeight(ri, 30)
        else:
            _, sn, r, is_cur = rd
            bg = "#0A1520" if is_cur else "#080A0D"
            sc = STATUS_COLORS.get(r.status, "#C8CDD8")
            table.setItem(ri,0,_item(f"  #{sn}", color="#5A6070", bg=bg))
            table.setItem(ri,1,_item(r.timestamp, color="#C8CDD8", bg=bg))
            table.setItem(ri,2,_item(f"{r.density_score:.2f}%", color="#FFFFFF", bg=bg))
            table.setItem(ri,3,_item(str(r.pixel_count), color="#FFFFFF", bg=bg))
            table.setItem(ri,4,_item(r.status or "N/A", color=sc, bg=bg))
            table.setRowHeight(ri, 25)


# ── Main Window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(UI_FILE, self)
        init_db()
        self._worker = None; self._roi_frame = None
        self._session_id = None; self._session_row_ids = []
        self._frame_vs_ref = None; self._frame_vs_prev = None
        self._overlay_mode = "ref"; self._showing_result = False
        self._first_scan = True
        self._particles_ref = []; self._particles_prev = []
        self._yolo = YoloExporter()
        self._current_scan_index = -1   # scan_index mới nhất trong _yolo
        self._min_area_filter = 0       # giá trị slider size filter
        self._post_init()

    def _post_init(self):
        if not isinstance(self.lblVideoFeed, ClickableLabel):
            self._replace_with_clickable()
        self.lblVideoFeed.roi_selected.connect(self._on_roi_selected)
        # Dùng signal clicked (emit sau mouseRelease không drag) để label hạt bụi
        # KHÔNG override mousePressEvent — sẽ phá vỡ logic ROI drag
        self.lblVideoFeed.clicked.connect(self._on_label_clicked)
        self.scan_line = ScanLineWidget(self.lblVideoFeed); self.scan_line.hide()

        hh = self.tableHistory.horizontalHeader()
        modes = [QHeaderView.ResizeMode.ResizeToContents]*4 + [QHeaderView.ResizeMode.Stretch]
        for col, mode in enumerate(modes): hh.setSectionResizeMode(col, mode)
        self.tableHistory.setHorizontalHeaderLabels(["","TIMESTAMP","DENSITY","COUNT","STATUS"])
        self.tableHistory.verticalHeader().setVisible(False)

        # tableParticles: 5 cột (thêm CLASS)
        self.tableParticles.setColumnCount(5)
        self.tableParticles.setHorizontalHeaderLabels(["#","AREA px²","W px","H px","CLASS"])
        self.tableParticles.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.btnConnect.clicked.connect(self._on_connect)
        self.btnReference.clicked.connect(self._on_capture_ref)
        self.btnScan.clicked.connect(self._on_scan)
        self.btnReset.clicked.connect(self._on_new_paper)
        self.btnRefresh.clicked.connect(self._refresh_history)
        self.btnToggleOverlay.clicked.connect(self._on_toggle_overlay)
        self.btnExportYolo.clicked.connect(self._on_export_yolo)
        self.radioShowBB.toggled.connect(lambda _: self._redraw_overlay_with_labels())  

        # Size filter slider
        self.sliderSizeFilter.setMinimum(0)
        self.sliderSizeFilter.setMaximum(5000)
        self.sliderSizeFilter.setValue(0)
        self.sliderSizeFilter.valueChanged.connect(self._on_size_filter_changed)
        self._update_size_filter_label(0)

        self.btnReset.setText("NEW PAPER")
        self.btnScan.setText("SCAN")
        self._set_btn_state("idle")
        self._refresh_history()
        self._set_status("System ready. Select camera and press CONNECT.")

    def _replace_with_clickable(self):
        old = self.lblVideoFeed
        cl = ClickableLabel(old.parentWidget())
        cl.setObjectName("lblVideoFeed")
        cl.setAlignment(old.alignment()); cl.setStyleSheet(old.styleSheet())
        cl.setSizePolicy(old.sizePolicy()); cl.setMinimumSize(old.minimumSize())
        layout = old.parentWidget().layout()
        for i in range(layout.count()):
            if layout.itemAt(i).widget() is old:
                layout.removeWidget(old); layout.insertWidget(i, cl); break
        old.deleteLater(); self.lblVideoFeed = cl

    def _set_btn_state(self, state):
        self.btnConnect.setEnabled(True)
        self.btnReference.setEnabled(state in ("roi_set","ref_captured","scan_done"))
        self.btnScan.setEnabled(state in ("ref_captured","scan_done"))
        self.btnReset.setEnabled(state in ("ref_captured","scanning","scan_done"))
        self.btnToggleOverlay.setEnabled(state == "scan_done")
        self.btnExportYolo.setEnabled(state == "scan_done" and self._yolo.count() > 0)

    # ── Size filter ───────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_size_filter_changed(self, value: int):
        self._min_area_filter = value
        self._update_size_filter_label(value)
        if self._showing_result:
            particles = self._particles_ref if self._overlay_mode == "ref" else self._particles_prev
            self._update_particle_table(particles)
            
            
            
            self._redraw_overlay_with_labels()
          
    

    def _update_size_filter_label(self, value: int):
        try:
            self.lblSizeFilterValue.setText(f"{value} px²")
        except AttributeError:
            pass  # widget chưa tồn tại

    def _filtered_particles(self, particles: list[dict]) -> list[dict]:
        """Lọc particles theo slider size filter."""
        if self._min_area_filter <= 0:
            return particles
        return [p for p in particles if p.get("area_px", 0) >= self._min_area_filter]

    # ── Click-to-label ────────────────────────────────────────────────────────

    @pyqtSlot(QPoint)
    def _on_label_clicked(self, widget_pt: QPoint):
        """
        Nhận QPoint tọa độ widget từ ClickableLabel.clicked signal.
        Signal này chỉ emit khi thả chuột mà KHÔNG drag (tức là click thật),
        nên không cản trở việc vẽ ROI.
        """
        if not self._showing_result or self._current_scan_index < 0:
            return

        particles = self._particles_ref if self._overlay_mode == "ref" else self._particles_prev
        filtered  = self._filtered_particles(particles)
        if not filtered:
            return

        # widget_pt đã là QPoint tọa độ widget → chuyển về tọa độ ảnh gốc
        img_pt = self._widget_to_image_coords(widget_pt)
        if img_pt is None:
            return

        # Tìm hạt gần nhất với click
        best_p   = None
        best_dist = float("inf")
        for p in filtered:
            dx = p["cx"] - img_pt.x()
            dy = p["cy"] - img_pt.y()
            # Kiểm tra click nằm trong bbox (với tolerance 10px)
            half_w = p.get("w_px", 0) // 2 + 10
            half_h = p.get("h_px", 0) // 2 + 10
            if abs(dx) <= half_w and abs(dy) <= half_h:
                dist = dx*dx + dy*dy
                if dist < best_dist:
                    best_dist = dist
                    best_p = p

        if best_p is None:
            return

        # Mở dialog chọn class
        cur_class = self._yolo.get_particle_class(self._current_scan_index, best_p["id"])
        dlg = ClassPickerDialog(best_p, cur_class, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._yolo.set_particle_class(
                self._current_scan_index, best_p["id"], dlg.chosen_class)
            self._update_particle_table(particles)
            self._redraw_overlay_with_labels()
            cls_name = _class_name(dlg.chosen_class)
            self._set_status(
                f"Hạt #{best_p['id']} → {cls_name}  "
                f"[scan {self._current_scan_index}]")

    def _widget_to_image_coords(self, pt: QPoint) -> QPoint | None:
        """
        Chuyển tọa độ click trong QLabel widget → tọa độ trong ROI CROP.
        Kết quả dùng để so sánh trực tiếp với particle cx/cy (vốn là crop coords).
        """
        pm = self.lblVideoFeed.pixmap()
        if pm is None or pm.isNull():
            return None

        lbl_w, lbl_h = self.lblVideoFeed.width(), self.lblVideoFeed.height()
        pm_w,  pm_h  = pm.width(), pm.height()

        # Offset letterbox (KeepAspectRatio + AlignCenter)
        off_x = (lbl_w - pm_w) // 2
        off_y = (lbl_h - pm_h) // 2
        img_x = pt.x() - off_x
        img_y = pt.y() - off_y
        if not (0 <= img_x < pm_w and 0 <= img_y < pm_h):
            return None

        # Scale về kích thước full frame
        frame = self._frame_vs_ref if self._overlay_mode == "ref" else self._frame_vs_prev
        if frame is None:
            return None
        orig_h, orig_w = frame.shape[:2]
        frame_x = int(img_x * orig_w / pm_w)
        frame_y = int(img_y * orig_h / pm_h)

        # Trừ offset ROI để ra tọa độ trong crop (khớp với particle cx/cy)
        roi_x = self._roi_frame[0] if self._roi_frame else 0
        roi_y = self._roi_frame[1] if self._roi_frame else 0
        return QPoint(frame_x - roi_x, frame_y - roi_y)

    # ── Overlay với class label ───────────────────────────────────────────────

    def _redraw_overlay_with_labels(self):
        """
        Vẽ lại ảnh overlay, tô màu bounding box theo class đã gán.

        QUAN TRỌNG: frame_vs_ref/frame_vs_prev là FULL FRAME (toàn màn hình),
        còn cx/cy của particles là tọa độ trong ROI CROP.
        Phải offset thêm (roi_x, roi_y) khi vẽ lên full frame.
        """
        frame_bgr = self._frame_vs_ref if self._overlay_mode == "ref" else self._frame_vs_prev
        if frame_bgr is None:
            return

        particles = self._particles_ref if self._overlay_mode == "ref" else self._particles_prev
        filtered  = self._filtered_particles(particles)

        # Offset ROI: particles cx/cy là tọa độ trong crop, cần cộng thêm roi origin
        roi_x = self._roi_frame[0] if self._roi_frame else 0
        roi_y = self._roi_frame[1] if self._roi_frame else 0

        canvas = frame_bgr.copy()
        if self.radioShowBB.isChecked():
            for p in filtered:
                cls_id = self._yolo.get_particle_class(self._current_scan_index, p["id"])
                hex_c  = _class_color(cls_id)
                # Hex → BGR
                r_val = int(hex_c[1:3], 16); g_val = int(hex_c[3:5], 16); b_val = int(hex_c[5:7], 16)
                bgr = (b_val, g_val, r_val)

                # Tọa độ thực trên full frame
                cx = p["cx"] + roi_x
                cy = p["cy"] + roi_y
                hw = max(p.get("w_px", 20) // 2, 4)
                hh = max(p.get("h_px", 20) // 2, 4)
                pt1 = (cx - hw, cy - hh)
                pt2 = (cx + hw, cy + hh)
                cv2.rectangle(canvas, pt1, pt2, bgr, 2)

                # ID + class label nhỏ ở góc trên bbox
                label_txt = f"#{p['id']} {_class_name(cls_id)[:6]}"
                cv2.putText(canvas, label_txt,
                            (cx - hw, max(roi_y + 2, cy - hh - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, bgr, 1, cv2.LINE_AA)

        qimg = self._bgr_to_qimage(canvas)
        self.lblVideoFeed.set_frame_size(qimg.width(), qimg.height())
        pm = QPixmap.fromImage(qimg).scaled(
            self.lblVideoFeed.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.lblVideoFeed.setPixmap(pm)


    # ── ROI ──────────────────────────────────────────────────────────────────

    @pyqtSlot(QRect)
    def _on_roi_selected(self, frame_rect):
        if frame_rect.width() < 10 or frame_rect.height() < 10: return
        self._roi_frame = (frame_rect.x(), frame_rect.y(), frame_rect.width(), frame_rect.height())
        if self._worker and self._worker.isRunning():
            self._worker.set_roi(self._roi_frame); self._set_btn_state("roi_set")
        self._set_status(f"ROI: {frame_rect.width()}x{frame_rect.height()} px — Capture reference to begin.")

    # ── Connect ───────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_connect(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop(); self._worker.wait(); self._worker = None
            self.btnConnect.setText("CONNECT"); self._set_btn_state("idle")
            self._set_status("Camera disconnected."); return
        cam_idx = self.cmbCamera.currentIndex()
        self._worker = CVWorker(camera_index=cam_idx)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.scan_result.connect(self._on_scan_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self.btnConnect.setText("DISCONNECT")
        self._set_btn_state("roi_set" if self._roi_frame else "idle")
        self._set_status(f"Camera {cam_idx} connected. Draw ROI then CAPTURE REFERENCE.")

    @pyqtSlot()
    def _on_capture_ref(self):
        if not self._worker or not self._roi_frame:
            self._set_status("Draw ROI before capturing reference.", error=True); return
        self.lblVideoFeed.clear_roi()
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_row_ids = []
        self._frame_vs_ref = self._frame_vs_prev = None
        self._showing_result = False; self._overlay_mode = "ref"; self._first_scan = True
        self._particles_ref = []; self._particles_prev = []
        self._yolo.clear(); self._current_scan_index = -1
        self.btnToggleOverlay.setChecked(False); self.btnToggleOverlay.setText("VS REFERENCE")
        self._worker.capture_reference()
        self.lblDensityValue.setText("—"); self.lblCountValue.setText("—")
        self.lblStatus.setText("—"); self.progressDensity.setValue(0)
        self._clear_particle_table()
        self._refresh_history(); self._set_btn_state("ref_captured")
        self._set_status(f"[{self._session_id}] Reference captured. Press SCAN.")

    @pyqtSlot()
    def _on_scan(self):
        if not self._worker: return
        self._worker.capture_scan()
        self.scan_line.setGeometry(self.lblVideoFeed.rect()); self.scan_line.run_once()
        self.btnScan.setText("SCANNING..."); self._set_btn_state("scanning")
        self._set_status(f"[{self._session_id}] Capturing and analysing...")

    @pyqtSlot(dict)
    def _on_scan_result(self, data):
        event = data.get("event")
        if event == "reference_captured":
            self._set_status(f"[{self._session_id}] Reference OK - Press SCAN."); return
        if event != "scan_done": return

        self._frame_vs_ref  = data.get("frame_vs_ref")
        self._frame_vs_prev = data.get("frame_vs_prev")
        self._particles_ref  = data.get("particles", [])
        self._particles_prev = data.get("particles_prev", [])
        has_prev = data.get("has_prev", False)
        crop_bgr = data.get("crop_bgr")
        density  = data.get("density", 0.0)
        count    = data.get("count", 0)
        status   = data.get("status", "—")

        self.lblDensityValue.setText(f"{density:.1f}")
        self.lblCountValue.setText(str(count))
        self.lblStatus.setText(status)
        self.progressDensity.setValue(min(int(density), 100))
        color = STATUS_COLORS.get(status, "#00C8FF")
        self.lblStatus.setStyleSheet(
            f"color:{color};font-size:20px;font-weight:bold;"
            "border:1px solid #1E2330;border-radius:4px;"
            "background:#0D0F14;letter-spacing:4px;padding:8px;")

        self._first_scan = not has_prev
        self._overlay_mode = "ref"
        self.btnToggleOverlay.setChecked(False)
        self.btnToggleOverlay.setText("VS REFERENCE")
        self._update_particle_table(self._particles_ref)
        self._showing_result = True

        if crop_bgr is not None and self._particles_ref:
            roi = self._roi_frame or (0,0,crop_bgr.shape[1],crop_bgr.shape[0])
            self._current_scan_index = self._yolo.add_scan(
                crop_bgr, self._particles_ref, roi)

        # Vẽ overlay với class labels
        self._redraw_overlay_with_labels()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_path = ""
        Path("data/captures").mkdir(parents=True, exist_ok=True)
        if crop_bgr is not None and self._session_id:
            image_path = f"data/captures/{self._session_id}_scan_{ts.replace(' ','_').replace(':','')}.jpg"
            cv2.imwrite(image_path, crop_bgr)

        record = InspectionRecord(
            id=None, timestamp=ts, density_score=density, pixel_count=count,
            status=status, image_path=image_path,
            roi_width=self._roi_frame[2] if self._roi_frame else 0,
            roi_height=self._roi_frame[3] if self._roi_frame else 0,
        )
        row_id = save_inspection(record)
        self._session_row_ids.append(row_id)
        self._refresh_history(); self.btnScan.setText("SCAN")
        self._set_btn_state("scan_done")
        self._set_status(
            f"[{self._session_id}] Scan #{len(self._session_row_ids)}: "
            f"{density:.1f}% - {status} (ID#{row_id}) [YOLO:{self._yolo.count()}] "
            f"— Click hạt bụi để gán loại")

    @pyqtSlot()
    def _on_toggle_overlay(self):
        checked = self.btnToggleOverlay.isChecked()
        if checked:
            self._overlay_mode = "prev"
            d = self._get_prev_density()
            label = "VS REFERENCE (scan 1)" if self._first_scan else f"VS PREV SCAN ({d:.1f}%)"
            self.btnToggleOverlay.setText(label)
            self.lblDensityValue.setText(f"{d:.1f}")
            self.lblCountValue.setText(str(len(self._particles_prev)))
            self._update_particle_table(self._particles_prev)
        else:
            self._overlay_mode = "ref"
            self.btnToggleOverlay.setText("VS REFERENCE")
            if self._particles_ref:
                area_total = sum(p["area_px"] for p in self._particles_ref)
                roi_area = (self._roi_frame[2]*self._roi_frame[3] if self._roi_frame else 1)
                self.lblDensityValue.setText(f"{area_total/roi_area*100:.1f}")
            self.lblCountValue.setText(str(len(self._particles_ref)))
            self._update_particle_table(self._particles_ref)
        self._redraw_overlay_with_labels()

    def _get_prev_density(self):
        if not self._particles_prev or not self._roi_frame: return 0.0
        area = sum(p["area_px"] for p in self._particles_prev)
        roi_area = self._roi_frame[2]*self._roi_frame[3]
        return area/roi_area*100 if roi_area else 0.0

    def _display_overlay_frame(self):
        """Dùng khi không cần redraw class labels (ví dụ chỉ switch overlay)."""
        self._redraw_overlay_with_labels()

    def _clear_particle_table(self):
        self.tableParticles.clearContents(); self.tableParticles.setRowCount(0)

    def _update_particle_table(self, particles):
        filtered = self._filtered_particles(particles)
        self.tableParticles.clearContents()
        self.tableParticles.setRowCount(len(filtered))
        for row, p in enumerate(filtered):
            cls_id   = self._yolo.get_particle_class(self._current_scan_index, p["id"])
            cls_name = _class_name(cls_id)
            cls_col  = _class_color(cls_id)
            self.tableParticles.setItem(row, 0, _item(str(p["id"]),       color="#5A6070"))
            self.tableParticles.setItem(row, 1, _item(str(p["area_px"]), color="#FFFFFF"))
            self.tableParticles.setItem(row, 2, _item(str(p["w_px"]),    color="#C8CDD8"))
            self.tableParticles.setItem(row, 3, _item(str(p["h_px"]),    color="#C8CDD8"))
            self.tableParticles.setItem(row, 4, _item(cls_name,           color=cls_col,  bold=True))
            self.tableParticles.setRowHeight(row, 22)

    # ── Export YOLO ───────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_export_yolo(self):
        if self._yolo.count() == 0:
            self._set_status("No scan data to export.", error=True); return
        out_dir = QFileDialog.getExistingDirectory(self, "Choose YOLO dataset folder", str(Path.home()))
        if not out_dir: return
        out_path = Path(out_dir) / "yolo_dataset"
        self._set_status(f"Exporting {self._yolo.count()} images to {out_path}...")
        QApplication.processEvents()
        try:
            stats = self._yolo.export(out_path)
            msg = (
                f"YOLO Export complete!\n\n"
                f"  Folder  : {out_path}\n"
                f"  Images  : {stats['images']}  (train {stats['train']} / val {stats['val']})\n"
                f"  Labels  : {stats['labels']}\n"
                f"  Crops   : {stats['crops']} individual particles\n"
                f"  Skipped : {stats['skipped']}\n\n"
                f"dataset.yaml is ready for YOLO training.\n"
                f"Train command:\n"
                f"  yolo detect train data={out_path}/dataset.yaml model=yolov8n.pt epochs=100"
            )
            QMessageBox.information(self, "Export YOLO", msg)
            self._set_status(f"Export OK - {stats['images']} images, {stats['crops']} crops -> {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
            self._set_status(f"Export failed: {e}", error=True)

    # ── New paper ─────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_new_paper(self):
        self.scan_line.cancel()
        if self._worker: self._worker.reset_session()
        self._session_id = None; self._session_row_ids = []
        self._frame_vs_ref = self._frame_vs_prev = None
        self._showing_result = False; self._overlay_mode = "ref"; self._first_scan = True
        self._particles_ref = []; self._particles_prev = []
        self._yolo.clear(); self._current_scan_index = -1
        if self._roi_frame: self.lblVideoFeed.restore_roi(QRect(*self._roi_frame))
        self.lblDensityValue.setText("—"); self.lblCountValue.setText("—")
        self.lblStatus.setText("—"); self.progressDensity.setValue(0)
        self.btnScan.setText("SCAN")
        self.btnToggleOverlay.setChecked(False); self.btnToggleOverlay.setText("VS REFERENCE")
        self._clear_particle_table(); self._refresh_history()
        if self._roi_frame:
            self._set_btn_state("roi_set")
            self._set_status("ROI restored. Capture reference for new sheet.")
        else:
            self._set_btn_state("idle")
            self._set_status("New sheet. Draw ROI and capture reference.")

    # ── Frame / error ─────────────────────────────────────────────────────────

    @pyqtSlot(QImage)
    def _on_frame(self, img):
        if self._showing_result:
            self.scan_line.setGeometry(self.lblVideoFeed.rect()); return
        self.lblVideoFeed.set_frame_size(img.width(), img.height())
        pm = QPixmap.fromImage(img).scaled(
            self.lblVideoFeed.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.lblVideoFeed.setPixmap(pm)
        self.scan_line.setGeometry(self.lblVideoFeed.rect())

    @pyqtSlot(str)
    def _on_error(self, msg): self._set_status(f"ERROR: {msg}", error=True)

    def _refresh_history(self):
        _populate_history_table(self.tableHistory, fetch_history(500), self._session_id)

    @staticmethod
    def _bgr_to_qimage(frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data, w, h, ch*w, QImage.Format.Format_RGB888).copy()

    def _set_status(self, msg, error=False):
        color = "#FF3366" if error else "#5A6070"
        self.statusBar.showMessage(f"  {msg}")
        self.statusBar.setStyleSheet(f"QStatusBar {{ background:#080A0D; color:{color}; }}")

    def closeEvent(self, e):
        if self._worker and self._worker.isRunning():
            self._worker.stop(); self._worker.wait()
        e.accept()


def main():
    app = QApplication(sys.argv); app.setStyle("Fusion")
    w = MainWindow(); w.show(); sys.exit(app.exec())

if __name__ == "__main__":
    main()