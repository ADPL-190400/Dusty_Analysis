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
#  CAMERA BACKEND SELECTION
#  ─────────────────────────
#  "gige"   → GigE Vision camera qua Aravis (gi.repository.Aravis)
#  "opencv" → Camera USB/webcam thông thường qua OpenCV VideoCapture
# ══════════════════════════════════════════════════════════════════════════════

CAMERA_BACKEND = "gige"   # ← ĐỔI "opencv" nếu muốn dùng webcam USB

# ── Cấu hình GigE (chỉ dùng khi CAMERA_BACKEND = "gige") ──────────────────
#
# GIGE_CAMERA_ID:
#   • None          → tự động chọn camera đầu tiên tìm thấy
#   • "DEV_xxxxxx"  → Device ID (xem bằng: arv-tool-0.8 --list-devices)
#   • "192.168.x.x" → IP trực tiếp của camera
#
GIGE_CAMERA_ID = None

# Pixel format yêu cầu từ camera. Các giá trị phổ biến:
#   "Mono8", "Mono16", "BayerRG8", "BayerGB8", "BayerGR8", "BayerBG8",
#   "RGB8Packed", "BGR8Packed"
# Kiểm tra camera hỗ trợ format nào: arv-tool-0.8 features PixelFormat
GIGE_PIXEL_FORMAT = "BayerRG8"   # ← chỉnh theo sensor của camera bạn

# Timeout chờ frame từ stream (milliseconds)
GIGE_TIMEOUT_MS = 3000

# Packet size GigE (bytes).
#   None  → Aravis tự negotiate (khuyến nghị)
#   1500  → MTU chuẩn nếu switch không hỗ trợ Jumbo Frame
GIGE_PACKET_SIZE: int | None = None

# ── Exposure (áp dụng cho cả GigE lẫn OpenCV) ────────────────────────────────
#
# EXPOSURE_MODE:
#   "auto"   → để camera tự điều chỉnh (AutoExposure)
#   "manual" → dùng giá trị EXPOSURE_TIME_US bên dưới
#
EXPOSURE_MODE = "manual"   # ← "auto" hoặc "manual"

# Thời gian phơi sáng (micro-giây) — chỉ có hiệu lực khi EXPOSURE_MODE = "manual"
#   Giá trị tham khảo:
#     Môi trường sáng (đèn LED/ring light)  :   500 –  5_000 µs
#     Môi trường phòng bình thường           :  5_000 – 30_000 µs
#     Môi trường tối / tốc độ chậm          : 30_000 – 100_000 µs
#   Lưu ý: GigE thường giới hạn max exposure = 1 / FPS (ví dụ 30fps → max ~33_333 µs)
EXPOSURE_TIME_US: float = 20_000.0   # ← chỉnh tại đây (đơn vị: micro-giây)

# ── Cấu hình OpenCV (chỉ dùng khi CAMERA_BACKEND = "opencv") ─────────────────
OPENCV_CAMERA_INDEX = 0


# ══════════════════════════════════════════════════════════════════════════════
#  TUNING PARAMETERS — chỉnh tại đây để thay đổi độ nhạy phát hiện bụi
# ══════════════════════════════════════════════════════════════════════════════

DIFF_THRESHOLD      = 20    # [15–60]   ngưỡng diff pixel grayscale
MORPH_KERNEL        = 3     # [1–7]     kernel morphological open (xóa noise)
MORPH_CLOSE_KERNEL  = 5     # [1–11]    kernel morphological close (nối mảnh)
MIN_DUST_CONTOUR    = 8     # [3–50]    diện tích px² tối thiểu 1 hạt bụi
USE_CLAHE           = True  # True = tăng tương phản trước diff
CLAHE_CLIP          = 2.0   # [1.0–4.0] clipLimit CLAHE
CLAHE_GRID          = (8, 8)  # tileGridSize CLAHE
GAUSSIAN_BLUR_KSIZE = 3     # [1,3,5,7] blur trước diff (1 = tắt)

TARGET_FPS     = 30
FRAME_INTERVAL = 1.0 / TARGET_FPS

_clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_GRID)


# ══════════════════════════════════════════════════════════════════════════════
#  CAMERA ABSTRACTION LAYER
# ══════════════════════════════════════════════════════════════════════════════

class _GigECamera:
    """
    Wrapper GigE Vision camera dùng thư viện Aravis (gi.repository.Aravis).

    Cài đặt
    ───────
    Linux (Ubuntu/Debian):
        sudo apt install gir1.2-aravis-0.8 python3-gi

    Windows:
        Dùng MSYS2:
            pacman -S mingw-w64-x86_64-aravis
        Hoặc build từ source:
            https://github.com/AravisProject/aravis

    Kiểm tra camera đã nhận chưa:
        arv-tool-0.8 --list-devices

    Interface công khai giống OpenCV: open() → read() → release()
    """

    def __init__(self, camera_id: str | None = None):
        try:
            import gi
            gi.require_version("Aravis", "0.8")
            from gi.repository import Aravis
            self._Aravis = Aravis
        except (ImportError, ValueError) as exc:
            raise RuntimeError(
                "Không load được Aravis.\n"
                "Linux : sudo apt install gir1.2-aravis-0.8 python3-gi\n"
                "Xem   : https://github.com/AravisProject/aravis\n"
                f"Lỗi gốc: {exc}"
            ) from exc

        self._camera_id = camera_id
        self._cam       = None
        self._stream    = None
        self._opened    = False
        self._width     = 0
        self._height    = 0
        self._fmt       = ""

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def open(self) -> bool:
        """Kết nối camera, cấu hình stream và bắt đầu acquisition."""
        Aravis = self._Aravis
        try:
            # Quét mạng tìm camera
            Aravis.update_device_list()
            n = Aravis.get_n_devices()
            if n == 0:
                raise RuntimeError("Không tìm thấy camera GigE nào trên mạng.")

            # In danh sách để dễ debug
            for i in range(n):
                print(f"  [Aravis] device {i}: {Aravis.get_device_id(i)}")

            # Chọn camera theo ID hoặc lấy đầu tiên
            self._cam = Aravis.Camera.new(self._camera_id)
            cam = self._cam

            target_height = 1200
            sensor_height = 2048
            offset_y = (sensor_height - target_height) // 2

            try:
                cam.set_region(0,offset_y,2448,target_height)
            except Exception as e:
                print(f"[Aravis] can not set ROI {e}")

            # ── Pixel format ────────────────────────────────────────────────
            try:
                cam.set_pixel_format_from_string(GIGE_PIXEL_FORMAT)
            except Exception:
                print(f"[Aravis] WARNING: format '{GIGE_PIXEL_FORMAT}' "
                      "không được hỗ trợ, giữ mặc định của camera.")

            # ── Packet size ─────────────────────────────────────────────────
            if GIGE_PACKET_SIZE is not None:
                try:
                    cam.gv_set_packet_size(GIGE_PACKET_SIZE)
                except Exception:
                    pass
            else:
                try:
                    cam.gv_auto_packet_size()
                except Exception:
                    pass

            # ── Lấy thông tin kích thước frame ──────────────────────────────
            region       = cam.get_region()
            self._width  = region.width
            self._height = region.height
            self._fmt    = cam.get_pixel_format_as_string()

            print(f"[Aravis] Camera : {cam.get_model_name()}")
            print(f"[Aravis] Vendor : {cam.get_vendor_name()}")
            print(f"[Aravis] Format : {self._fmt}")
            print(f"[Aravis] Size   : {self._width} x {self._height}")

            # ── FPS ─────────────────────────────────────────────────────────
            try:
                cam.set_frame_rate(float(TARGET_FPS))
            except Exception:
                pass  # Một số camera không cho chỉnh FPS qua GenICam

            # u2500u2500 Exposure u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500
            try:
                if EXPOSURE_MODE == "auto":
                    cam.set_exposure_time_auto(1)   # 1 = Aravis.Auto.CONTINUOUS
                    print("[Aravis] Exposure: AUTO")
                else:
                    cam.set_exposure_time_auto(0)   # 0 = Aravis.Auto.OFF
                    cam.set_exposure_time(EXPOSURE_TIME_US)
                    actual = cam.get_exposure_time()
                    print(f"[Aravis] Exposure: MANUAL {actual:.0f} u00b5s ({actual/1000:.1f} ms)")
            except Exception as exc:
                print(f"[Aravis] WARNING: exposure: {exc}")

            # ── Stream + buffer pool ─────────────────────────────────────────
            self._stream = cam.create_stream(None, None)
            payload = cam.get_payload()
            for _ in range(10):   # 10 buffer vòng lặp để tránh drop frame
                self._stream.push_buffer(Aravis.Buffer.new_allocate(payload))

            cam.start_acquisition()
            self._opened = True
            return True

        except Exception as exc:
            print(f"[Aravis] Lỗi khi mở camera: {exc}")
            self._cleanup()
            return False

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        """
        Lấy 1 frame từ stream Aravis và trả về BGR numpy array.
        Trả về (True, bgr_frame) hoặc (False, None) nếu thất bại.
        """
        if not self._opened:
            return False, None

        Aravis = self._Aravis

        # timeout_pop_buffer nhận đơn vị micro-giây
        buf = self._stream.timeout_pop_buffer(GIGE_TIMEOUT_MS * 1_000)
        if buf is None:
            print("[Aravis] WARNING: timeout khi chờ frame.")
            return False, None

        if buf.get_status() != Aravis.BufferStatus.SUCCESS:
            self._stream.push_buffer(buf)
            return False, None

        raw   = np.frombuffer(buf.get_data(), dtype=np.uint8)
        frame = self._decode_frame(raw)
        

        # Trả buffer về pool ngay sau khi copy xong
        self._stream.push_buffer(buf)

        if frame is None:
            return False, None
        return True, frame

    def release(self) -> None:
        self._cleanup()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _decode_frame(self, raw: np.ndarray) -> np.ndarray | None:
        """
        Chuyển raw pixel bytes → BGR uint8.

        Hỗ trợ:
          Mono8, Mono16
          BayerRG8, BayerGB8, BayerGR8, BayerBG8  (và alias không có "8")
          RGB8Packed / RGB8
          BGR8Packed / BGR8
        """
        w, h  = self._width, self._height
        fmt   = self._fmt

        try:
            if fmt == "Mono8":
                gray = raw.reshape((h, w))
                return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

            elif fmt == "Mono16":
                gray16 = raw.view(np.uint16).reshape((h, w))
                gray8  = (gray16 >> 8).astype(np.uint8)
                return cv2.cvtColor(gray8, cv2.COLOR_GRAY2BGR)

            elif fmt in ("BayerRG8", "BayerRG"):
                # return cv2.cvtColor(raw.reshape((h, w)), cv2.COLOR_BAYER_RG2BGR)
              
                # return cv2.cvtColor(raw.reshape((h, w)), cv2.COLOR_BAYER_GR2BGR)
                return cv2.cvtColor(raw.reshape((h, w)), cv2.COLOR_BAYER_GB2RGB)

            elif fmt in ("BayerGB8", "BayerGB"):
                return cv2.cvtColor(raw.reshape((h, w)), cv2.COLOR_BAYER_GB2BGR)

            elif fmt in ("BayerGR8", "BayerGR"):
                return cv2.cvtColor(raw.reshape((h, w)), cv2.COLOR_BAYER_GR2BGR)

            elif fmt in ("BayerBG8", "BayerBG"):
                return cv2.cvtColor(raw.reshape((h, w)), cv2.COLOR_BAYER_BG2BGR)

            elif fmt in ("RGB8Packed", "RGB8"):
                return cv2.cvtColor(raw.reshape((h, w, 3)), cv2.COLOR_RGB2BGR)

            elif fmt in ("BGR8Packed", "BGR8"):
                return raw.reshape((h, w, 3)).copy()

            else:
                # Fallback: thử decode JPEG/PNG (một số camera stream compressed)
                img = cv2.imdecode(np.frombuffer(raw.tobytes(), dtype=np.uint8),
                                   cv2.IMREAD_COLOR)
                if img is not None:
                    return img
                print(f"[Aravis] Format chưa hỗ trợ: '{fmt}'. "
                      "Thêm case vào _decode_frame().")
                return None

        except Exception as exc:
            print(f"[Aravis] Lỗi decode frame (fmt={fmt}): {exc}")
            return None

    def _cleanup(self) -> None:
        try:
            if self._cam:
                self._cam.stop_acquisition()
        except Exception:
            pass
        self._cam    = None
        self._stream = None
        self._opened = False


class _OpenCVCamera:
    """Wrapper mỏng cho OpenCV VideoCapture, cùng interface với _GigECamera."""

    def __init__(self, index: int = 0):
        self._index = index
        self._cap   = None

    def open(self) -> bool:
        backend   = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(self._index, backend)
        if not self._cap.isOpened():
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2448)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2048)
        self._cap.set(cv2.CAP_PROP_FPS,          TARGET_FPS)
        # Exposure
        if EXPOSURE_MODE == "manual":
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # 0.25 = manual mode
            # OpenCV nhan don vi giay, Aravis nhan micro-giay
            self._cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE_TIME_US / 1_000_000)
        else:
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # 0.75 = auto mode
        return True

    def isOpened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.isOpened():
            return False, None
        return self._cap.read()

    def release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None


def _make_camera():
    """Factory: trả về đúng backend theo CAMERA_BACKEND."""
    if CAMERA_BACKEND == "gige":
        return _GigECamera(camera_id=GIGE_CAMERA_ID)
    return _OpenCVCamera(index=OPENCV_CAMERA_INDEX)


# ══════════════════════════════════════════════════════════════════════════════
#  CV WORKER THREAD
# ══════════════════════════════════════════════════════════════════════════════

class CVWorker(QThread):
    """
    Live preview + single-shot analysis.

    Mỗi lần nhấn SCAN:
      1. Grab 1 frame từ camera.
      2. Phân tích vs REFERENCE (ảnh sạch ban đầu của session).
      3. Phân tích vs PREV_SCAN:
           - Lần scan đầu tiên → PREV_SCAN = REFERENCE
           - Từ lần 2 trở đi  → PREV_SCAN = kết quả scan trước đó.
      4. Emit scan_result với cả 2 kết quả + annotated frames.
      5. Lưu crop hiện tại làm PREV_SCAN cho lần tiếp theo.
    """

    frame_ready = pyqtSignal(QImage)
    scan_result = pyqtSignal(dict)
    error       = pyqtSignal(str)

    IDLE           = "idle"
    CAPTURE        = "capture"
    CAPTURE_SAMPLE = "capture_sample"
    SCAN           = "scan"

    def __init__(self, camera_index: int = 0, roi: tuple | None = None):
        super().__init__()
        # camera_index giữ để tương thích API cũ; GigE dùng GIGE_CAMERA_ID.
        self.camera_index   = camera_index
        self.roi            = roi
        self.state          = self.IDLE
        self._running       = False
        self._mutex         = QMutex()
        self._reference     = None
        self._prev_scan     = None
        self._frozen_sample     = None   # crop ROI được chụp bởi capture_sample()
        self._frozen_full_frame = None   # full frame tương ứng để làm overlay base
        self._cam           = None   # set by run(), used by set_exposure()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_roi(self, roi: tuple) -> None:
        with QMutexLocker(self._mutex):
            self.roi = roi

    def set_exposure(self, exposure_us: float, mode: str = "manual") -> None:
        """
        Chỉnh exposure ngay khi đang chạy (không cần restart thread).
        exposure_us : thời gian phơi sáng tính bằng micro-giây.
        mode        : "manual" hoặc "auto" (bỏ qua exposure_us khi auto).
        """
        global EXPOSURE_MODE, EXPOSURE_TIME_US
        EXPOSURE_MODE    = mode
        EXPOSURE_TIME_US = exposure_us
        cam = self._cam
        if cam is None:
            return
        try:
            if isinstance(cam, _GigECamera) and cam.isOpened() and cam._cam:
                if mode == "auto":
                    cam._cam.set_exposure_time_auto(1)
                else:
                    cam._cam.set_exposure_time_auto(0)
                    cam._cam.set_exposure_time(exposure_us)
                    actual = cam._cam.get_exposure_time()
                    print(f"[Aravis] Exposure updated: {actual:.0f} µs ({actual/1000:.1f} ms)")
            elif isinstance(cam, _OpenCVCamera) and cam.isOpened():
                if mode == "auto":
                    cam._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
                else:
                    cam._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                    cam._cap.set(cv2.CAP_PROP_EXPOSURE, exposure_us / 1_000_000)
        except Exception as exc:
            print(f"[CVWorker] set_exposure lỗi: {exc}")

    def capture_reference(self) -> None:
        with QMutexLocker(self._mutex):
            self.state = self.CAPTURE

    def capture_sample(self) -> None:
        """Chụp 1 frame từ camera và giữ làm 'frozen sample' để scan sau."""
        with QMutexLocker(self._mutex):
            if self._reference is None:
                self.error.emit("Chưa có ảnh reference. Hãy chụp reference trước.")
                return
            self.state = self.CAPTURE_SAMPLE

    def capture_scan(self) -> None:
        with QMutexLocker(self._mutex):
            if self._reference is None:
                self.error.emit("Chưa có ảnh reference. Hãy chụp reference trước.")
                return
            self.state = self.SCAN

    def reset_session(self) -> None:
        with QMutexLocker(self._mutex):
            self._reference         = None
            self._prev_scan         = None
            self._frozen_sample     = None
            self._frozen_full_frame = None
            self.state = self.IDLE

    def stop(self) -> None:
        self._running = False

    # ── Thread loop ──────────────────────────────────────────────────────────

    def run(self) -> None:
        cam = _make_camera()

        self._cam = cam
        if not cam.open():
            if CAMERA_BACKEND == "gige":
                msg = (
                    "Không mở được camera GigE (Aravis).\n"
                    "Kiểm tra:\n"
                    "  • Camera đã bật nguồn và cắm Ethernet chưa?\n"
                    "  • Aravis cài đúng chưa? (arv-tool-0.8 --list-devices)\n"
                    "  • GIGE_CAMERA_ID / GIGE_PIXEL_FORMAT có đúng không?"
                )
            else:
                msg = f"Không mở được camera OpenCV index={OPENCV_CAMERA_INDEX}."
            self.error.emit(msg)
            return

        self._running = True

        while self._running:
            t0 = time.perf_counter()

            ok, frame = cam.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue

            frame = cv2.flip(frame,-1)

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
                    self._reference         = crop.copy()
                    self._prev_scan         = None
                    self._frozen_sample     = None
                    self._frozen_full_frame = None
                    self.state              = self.IDLE
                self.scan_result.emit({"event": "reference_captured"})

            elif state == self.CAPTURE_SAMPLE and roi:
                crop        = self._crop(frame, roi)
                full_frozen = frame.copy()  # giữ full frame để hiển thị & làm overlay base
                with QMutexLocker(self._mutex):
                    self._frozen_sample     = crop.copy()
                    self._frozen_full_frame = full_frozen
                    self.state              = self.IDLE
                self.scan_result.emit({
                    "event":        "sample_captured",
                    "sample_frame": full_frozen,  # UI dùng để freeze live feed
                })

            elif state == self.SCAN and roi:
                with QMutexLocker(self._mutex):
                    ref           = self._reference
                    prev_scan     = self._prev_scan
                    frozen_sample = self._frozen_sample
                    frozen_full   = self._frozen_full_frame

                if ref is not None:
                    # Luôn dùng frozen sample; fallback live frame nếu chưa có
                    crop      = frozen_sample if frozen_sample is not None else self._crop(frame, roi)
                    base_full = frozen_full   if frozen_full   is not None else frame
                    has_prev  = prev_scan is not None

                    result_vs_ref  = self._analyse(crop, ref, roi)
                    prev_target    = prev_scan if has_prev else ref
                    result_vs_prev = self._analyse(crop, prev_target, roi)

                    # Dùng frozen full frame làm nền overlay — không phải live frame
                    ann_vs_ref  = self._build_overlay(
                        base_full.copy(), crop, ref,         roi)
                    ann_vs_prev = self._build_overlay(
                        base_full.copy(), crop, prev_target, roi)

                    with QMutexLocker(self._mutex):
                        self._prev_scan         = crop.copy()
                        self._frozen_sample     = None   # xóa sau khi đã dùng
                        self._frozen_full_frame = None
                        self.state              = self.IDLE

                    self.scan_result.emit({
                        "event":              "scan_done",
                        "density":            result_vs_ref["density"],
                        "count":              result_vs_ref["count"],
                        "status":             result_vs_ref["status"],
                        "particles":          result_vs_ref["particles"],
                        "density_prev":       result_vs_prev["density"],
                        "count_prev":         result_vs_prev["count"],
                        "status_prev":        result_vs_prev["status"],
                        "particles_prev":     result_vs_prev["particles"],
                        "frame_vs_ref":       ann_vs_ref,
                        "frame_vs_prev":      ann_vs_prev,
                        "crop_bgr":           crop,
                        "has_prev":           has_prev,
                        "used_frozen_sample": frozen_sample is not None,
                    })

            self.frame_ready.emit(self._to_qimage(annotated))

            elapsed = time.perf_counter() - t0
            sleep   = max(0.0, FRAME_INTERVAL - elapsed)
            if sleep:
                time.sleep(sleep)

        cam.release()
        self._cam = None

    # ── CV helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _crop(frame: np.ndarray, roi: tuple) -> np.ndarray:
        x, y, w, h = roi
        return frame[y:y+h, x:x+w].copy()

    @staticmethod
    def _preprocess_gray(bgr: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if GAUSSIAN_BLUR_KSIZE > 1:
            gray = cv2.GaussianBlur(
                gray, (GAUSSIAN_BLUR_KSIZE, GAUSSIAN_BLUR_KSIZE), 0)
        if USE_CLAHE:
            gray = _clahe.apply(gray)
        return gray

    def _analyse(self, crop: np.ndarray, ref: np.ndarray,
                 roi: tuple) -> dict:
        gray_now = self._preprocess_gray(crop)
        gray_ref = self._preprocess_gray(ref)

        diff  = cv2.absdiff(gray_now, gray_ref)
        _, th = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        k_open  = cv2.getStructuringElement(
            cv2.MORPH_RECT, (MORPH_KERNEL, MORPH_KERNEL))
        opened  = cv2.morphologyEx(th, cv2.MORPH_OPEN, k_open)

        k_close = cv2.getStructuringElement(
            cv2.MORPH_RECT, (MORPH_CLOSE_KERNEL, MORPH_CLOSE_KERNEL))
        cleaned = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k_close)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) >= MIN_DUST_CONTOUR]

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