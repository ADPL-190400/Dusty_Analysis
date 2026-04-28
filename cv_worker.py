from __future__ import annotations

import time
import os
import cv2
import numpy as np
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from PyQt6.QtGui import QImage

from database import IMAGE_DIR


# ══════════════════════════════════════════════════════════════════════════════
#  TUNING PARAMETERS — chỉnh tại đây để thay đổi độ nhạy phát hiện bụi
# ══════════════════════════════════════════════════════════════════════════════

DIFF_THRESHOLD      = 20    # [15–60]   ngưỡng diff pixel grayscale
MORPH_KERNEL        = 3     # [1–7]    kernel morphological open (xóa noise)
MORPH_CLOSE_KERNEL  = 5     # [1–11]   kernel morphological close (nối mảnh)
MIN_DUST_CONTOUR    = 8     # [3–50]   diện tích px² tối thiểu 1 hạt bụi
USE_CLAHE           = True  # True = tăng tương phản trước diff
CLAHE_CLIP          = 2.0   # [1.0–4.0]  clipLimit CLAHE
CLAHE_GRID          = (8, 8)  # tileGridSize CLAHE
GAUSSIAN_BLUR_KSIZE = 3     # [1,3,5,7]  blur trước diff (1 = tắt)

TARGET_FPS     = 30
FRAME_INTERVAL = 1.0 / TARGET_FPS

_clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_GRID)


class CVWorker(QThread):
    """
    Live preview + single-shot analysis.

    Mỗi lần nhấn SCAN:
      1. Grab 1 frame từ camera.
      2. Phân tích vs REFERENCE (ảnh sạch ban đầu của session).
      3. Phân tích vs PREV_SCAN:
           - Lần scan đầu tiên → PREV_SCAN = REFERENCE
             (cả 2 tab cho kết quả giống nhau, UI label rõ "scan 1")
           - Từ lần 2 trở đi → PREV_SCAN = kết quả scan trước đó.
      4. Emit scan_result với cả 2 kết quả + annotated frames.
      5. Lưu crop hiện tại làm PREV_SCAN cho lần tiếp theo.
    """

    frame_ready = pyqtSignal(QImage)
    scan_result = pyqtSignal(dict)
    error       = pyqtSignal(str)

    IDLE    = "idle"
    CAPTURE = "capture"
    SCAN    = "scan"

    def __init__(self, camera_index: int = 0, roi: tuple | None = None):
        super().__init__()
        self.camera_index = camera_index
        self.roi          = roi
        self.state        = self.IDLE
        self._running     = False
        self._mutex       = QMutex()
        self._reference   = None   # np.ndarray – ảnh sạch (ROI crop)
        self._prev_scan   = None   # np.ndarray – scan lần trước (ROI crop)

    # ── Public API ───────────────────────────────────────────────────────────

    def set_roi(self, roi: tuple) -> None:
        with QMutexLocker(self._mutex):
            self.roi = roi

    def capture_reference(self) -> None:
        """Grab frame tiếp theo làm reference (ảnh sạch)."""
        with QMutexLocker(self._mutex):
            self.state = self.CAPTURE

    def capture_scan(self) -> None:
        """
        Grab 1 frame và phân tích.
        Lần đầu (prev_scan=None): so vs reference cho cả 2 chế độ.
        Lần tiếp: so vs reference VÀ vs lần scan trước.
        """
        with QMutexLocker(self._mutex):
            if self._reference is None:
                self.error.emit("Chưa có ảnh reference. Hãy chụp reference trước.")
                return
            self.state = self.SCAN

    def reset_session(self) -> None:
        """Xóa reference và prev_scan khi bắt đầu session mới."""
        with QMutexLocker(self._mutex):
            self._reference = None
            self._prev_scan = None
            self.state = self.IDLE

    def stop(self) -> None:
        self._running = False

    # ── Thread loop ──────────────────────────────────────────────────────────

    def run(self) -> None:
        cap = cv2.VideoCapture(
            self.camera_index,
            cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY,
        )
        if not cap.isOpened():
            self.error.emit(f"Không mở được camera {self.camera_index}")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  2048)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1200)
        cap.set(cv2.CAP_PROP_FPS,          TARGET_FPS)

        self._running = True

        while self._running:
            t0 = time.perf_counter()

            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue

            with QMutexLocker(self._mutex):
                state = self.state
                roi   = self.roi

            # Vẽ ROI border lên live preview
            annotated = frame.copy()
            if roi:
                x, y, w, h = roi
                cv2.rectangle(annotated, (x, y), (x + w, y + h),
                              (0, 200, 255), 2)

            # ── State handling ────────────────────────────────────────────
            if state == self.CAPTURE and roi:
                crop = self._crop(frame, roi)
                with QMutexLocker(self._mutex):
                    self._reference = crop.copy()
                    self._prev_scan = None   # reset prev khi có reference mới
                    self.state      = self.IDLE
                self.scan_result.emit({"event": "reference_captured"})

            elif state == self.SCAN and roi:
                with QMutexLocker(self._mutex):
                    ref       = self._reference
                    prev_scan = self._prev_scan

                if ref is not None:
                    crop     = self._crop(frame, roi)
                    has_prev = prev_scan is not None

                    # VS REFERENCE — luôn so với ảnh sạch ban đầu
                    result_vs_ref = self._analyse(crop, ref, roi)

                    # VS PREV SCAN — lần đầu: prev_target = reference
                    #                 lần sau: prev_target = lần scan trước
                    prev_target    = prev_scan if has_prev else ref
                    result_vs_prev = self._analyse(crop, prev_target, roi)

                    # Annotated frames
                    ann_vs_ref  = self._build_overlay(
                        frame.copy(), crop, ref,         roi)
                    ann_vs_prev = self._build_overlay(
                        frame.copy(), crop, prev_target, roi)

                    # Lưu crop hiện tại làm prev cho lần sau
                    with QMutexLocker(self._mutex):
                        self._prev_scan = crop.copy()
                        self.state      = self.IDLE

                    self.scan_result.emit({
                        "event":          "scan_done",
                        # VS reference
                        "density":        result_vs_ref["density"],
                        "count":          result_vs_ref["count"],
                        "status":         result_vs_ref["status"],
                        "particles":      result_vs_ref["particles"],
                        # VS previous scan
                        "density_prev":   result_vs_prev["density"],
                        "count_prev":     result_vs_prev["count"],
                        "status_prev":    result_vs_prev["status"],
                        "particles_prev": result_vs_prev["particles"],
                        # Annotated BGR frames
                        "frame_vs_ref":   ann_vs_ref,
                        "frame_vs_prev":  ann_vs_prev,
                        # Thông tin thêm
                        "crop_bgr":       crop,
                        "has_prev":       has_prev,
                    })

            # Emit live frame
            self.frame_ready.emit(self._to_qimage(annotated))

            elapsed = time.perf_counter() - t0
            sleep   = max(0.0, FRAME_INTERVAL - elapsed)
            if sleep:
                time.sleep(sleep)

        cap.release()

    # ── CV helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _crop(frame: np.ndarray, roi: tuple) -> np.ndarray:
        x, y, w, h = roi
        return frame[y:y+h, x:x+w].copy()

    @staticmethod
    def _preprocess_gray(bgr: np.ndarray) -> np.ndarray:
        """
        Pipeline xử lý ảnh trước khi tính diff:
          1. Grayscale
          2. Gaussian blur  → giảm noise sensor
          3. CLAHE          → tăng tương phản cục bộ, làm nổi bụi mờ
        Áp dụng GIỐNG NHAU cho cả crop và ref để diff chính xác.
        """
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        if GAUSSIAN_BLUR_KSIZE > 1:
            gray = cv2.GaussianBlur(
                gray, (GAUSSIAN_BLUR_KSIZE, GAUSSIAN_BLUR_KSIZE), 0)

        if USE_CLAHE:
            gray = _clahe.apply(gray)

        return gray

    def _analyse(self, crop: np.ndarray, ref: np.ndarray,
                 roi: tuple) -> dict:
        """
        Phân tích độ bụi giữa crop và ref.

        Pipeline:
          preprocess → absdiff → threshold
          → morph open  (xóa noise nhỏ)
          → morph close (nối mảnh bụi bị gián đoạn)
          → findContours → lọc theo MIN_DUST_CONTOUR
          → tính density % và danh sách particle
        """
        gray_now = self._preprocess_gray(crop)
        gray_ref = self._preprocess_gray(ref)

        diff  = cv2.absdiff(gray_now, gray_ref)
        _, th = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        # Open: xóa noise salt-and-pepper
        k_open  = cv2.getStructuringElement(
            cv2.MORPH_RECT, (MORPH_KERNEL, MORPH_KERNEL))
        opened  = cv2.morphologyEx(th, cv2.MORPH_OPEN, k_open)

        # Close: nối mảnh bụi bị đứt
        k_close = cv2.getStructuringElement(
            cv2.MORPH_RECT, (MORPH_CLOSE_KERNEL, MORPH_CLOSE_KERNEL))
        cleaned = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k_close)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) >= MIN_DUST_CONTOUR]

        # Build particle list
        particles = []
        for c in valid:
            area = cv2.contourArea(c)
            x, y, w, h = cv2.boundingRect(c)
            M  = cv2.moments(c)
            cx = int(M["m10"] / M["m00"]) if M["m00"] else x + w // 2
            cy = int(M["m01"] / M["m00"]) if M["m00"] else y + h // 2
            particles.append({
                "area_px": int(area),
                "w_px":    w,
                "h_px":    h,
                "cx":      cx,
                "cy":      cy,
            })

        # Sort lớn → nhỏ rồi đánh id
        particles.sort(key=lambda p: p["area_px"], reverse=True)
        for i, p in enumerate(particles):
            p["id"] = i + 1

        dust_px  = sum(p["area_px"] for p in particles)
        total_px = roi[2] * roi[3]
        density  = (dust_px / total_px * 100) if total_px else 0.0

        if   density < 1.0:  status = "CLEAN"
        elif density < 5.0:  status = "LIGHT DUST"
        elif density < 15.0: status = "MODERATE"
        else:                status = "HEAVY DUST"

        return {
            "density":   round(density, 2),
            "count":     len(valid),
            "status":    status,
            "mask":      cleaned,
            "particles": particles,
        }

    def _build_overlay(self, full_frame: np.ndarray,
                       crop: np.ndarray, ref: np.ndarray,
                       roi: tuple) -> np.ndarray:
        """Vẽ highlight đỏ bán trong suốt lên vùng bụi trong full frame."""
        x, y, w, h = roi
        result  = full_frame.copy()
        metrics = self._analyse(crop, ref, (0, 0, crop.shape[1], crop.shape[0]))
        mask    = metrics.get("mask")
        if mask is not None:
            roi_region = result[y:y+h, x:x+w].copy()
            red_layer  = np.zeros_like(roi_region)
            red_layer[:, :, 2] = 255
            alpha   = (mask / 255.0 * 0.55)[..., np.newaxis]
            blended = (roi_region * (1 - alpha) + red_layer * alpha).astype(np.uint8)
            result[y:y+h, x:x+w] = blended
        cv2.rectangle(result, (x, y), (x + w, y + h), (0, 200, 255), 2)
        return result

    @staticmethod
    def _to_qimage(frame: np.ndarray) -> QImage:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
    


