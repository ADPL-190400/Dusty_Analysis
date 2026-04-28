# from PyQt6.QtWidgets import QLabel
# from PyQt6.QtCore import pyqtSignal, Qt, QPoint, QRect, QSize
# from PyQt6.QtGui import QMouseEvent, QPainter, QPen, QColor

# class ClickableLabel(QLabel):
#     clicked = pyqtSignal(QPoint)
#     roi_selected = pyqtSignal(QRect)
#     roi_drawing = pyqtSignal(QRect)

#     def __init__(self, parent=None):
#         super().__init__(parent)
#         self._p0: QPoint | None = None
#         self._p1: QPoint | None = None
#         self._dragging = False
#         self._confirmed = False
#         self._frame_size = QSize(0, 0) # Sử dụng QSize để gọn hơn

#         self.setCursor(Qt.CursorShape.CrossCursor)
#         self.setMouseTracking(True)
#         self.setAlignment(Qt.AlignmentFlag.AlignCenter) # Quan trọng để tính offset

#     def set_frame_size(self, w: int, h: int):
#         self._frame_size = QSize(w, h)
#         self.update()

#     def _displayed_image_rect(self) -> QRect:
#         """
#         TÍNH TOÁN VỊ TRÍ ẢNH THỰC SỰ TRONG LABEL.
#         Đây là nơi duy nhất xác định vùng được phép thao tác.
#         """
#         if self._frame_size.isEmpty():
#             return self.rect()

#         # Tính tỉ lệ giữ nguyên AspectRatio
#         fw, fh = self._frame_size.width(), self._frame_size.height()
#         lw, lh = self.width(), self.height()
        
#         scale = min(lw / fw, lh / fh)
#         iw, ih = int(fw * scale), int(fh * scale)
        
#         # Offset (letterbox)
#         ox = (lw - iw) // 2
#         oy = (lh - ih) // 2
        
#         return QRect(ox, oy, iw, ih)

#     def _clamp_point(self, pt: QPoint) -> QPoint:
#         """Ép tọa độ chuột luôn nằm trong vùng ảnh thực."""
#         ir = self._displayed_image_rect()
#         x = max(ir.left(), min(pt.x(), ir.right()))
#         y = max(ir.top(), min(pt.y(), ir.bottom()))
#         return QPoint(x, y)

#     def mousePressEvent(self, event: QMouseEvent):
#         if event.button() == Qt.MouseButton.LeftButton:
#             ir = self._displayed_image_rect()
#             if ir.contains(event.position().toPoint()):
#                 pt = self._clamp_point(event.position().toPoint())
#                 self._p0 = pt
#                 self._p1 = pt
#                 self._dragging = True
#                 self._confirmed = False
#                 self.update()
#         super().mousePressEvent(event)

#     def mouseMoveEvent(self, event: QMouseEvent):
#         if self._dragging:
#             self._p1 = self._clamp_point(event.position().toPoint())
#             self.update()
#             self.roi_drawing.emit(self._to_frame(self._current_rect()))
#         super().mouseMoveEvent(event)

#     def mouseReleaseEvent(self, event: QMouseEvent):
#         if self._dragging:
#             self._dragging = False
#             self._confirmed = True
#             self.update()
#             r = self._current_rect()
#             if r.width() > 5 and r.height() > 5:
#                 self.roi_selected.emit(self._to_frame(r))
#         super().mouseReleaseEvent(event)

#     def _current_rect(self) -> QRect:
#         if not self._p0 or not self._p1: return QRect()
#         return QRect(self._p0, self._p1).normalized()

#     def _to_frame(self, display_rect: QRect) -> QRect:
#         """Quy đổi tọa độ Label -> Frame Gốc."""
#         ir = self._displayed_image_rect()
#         if self._frame_size.isEmpty() or ir.width() == 0: return display_rect

#         # Tỉ lệ scale thực tế
#         sx = self._frame_size.width() / ir.width()
#         sy = self._frame_size.height() / ir.height()

#         # Tính offset trừ đi và nhân scale
#         fx = int((display_rect.left() - ir.left()) * sx)
#         fy = int((display_rect.top() - ir.top()) * sy)
#         fw = int(display_rect.width() * sx)
#         fh = int(display_rect.height() * sy)

#         return QRect(fx, fy, fw, fh)

#     def paintEvent(self, event):
#         super().paintEvent(event) # Vẽ Pixmap trước
#         if not self._p0 or not self._p1: return

#         r = self._current_rect()
#         p = QPainter(self)
#         p.setRenderHint(QPainter.RenderHint.Antialiasing)

#         # Draw ROI
#         p.fillRect(r, QColor(0, 200, 255, 30))
#         pen = QPen(QColor(0, 200, 255, 255), 2)
#         pen.setStyle(Qt.PenStyle.SolidLine if self._confirmed else Qt.PenStyle.DashLine)
#         p.setPen(pen)
#         p.drawRect(r)
        
#         # Draw dimensions
#         fr = self._to_frame(r)
#         p.drawText(r.topLeft() + QPoint(5, -5), f"{fr.width()}x{fr.height()}")
#         p.end()

#     def clear_roi(self):
#         self._p0 = self._p1 = None
#         self._confirmed = False
#         self.update()

#     def restore_roi(self, frame_rect: QRect):
#         """Vẽ lại ROI từ tọa độ frame gốc (gọi khi Reset)."""
#         if self._frame_size.isEmpty() or frame_rect.isNull():
#             return

#         ir = self._displayed_image_rect()
        
#         # Tính tỉ lệ scale xuôi: frame -> display
#         sx = ir.width() / self._frame_size.width()
#         sy = ir.height() / self._frame_size.height()

#         # Quy đổi ngược lại tọa độ trên Label
#         x = int(frame_rect.x() * sx) + ir.left()
#         y = int(frame_rect.y() * sy) + ir.top()
#         w = int(frame_rect.width() * sx)
#         h = int(frame_rect.height() * sy)

#         self._p0 = QPoint(x, y)
#         self._p1 = QPoint(x + w, y + h)
#         self._confirmed = True
#         self.update()



from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import pyqtSignal, Qt, QPoint, QRect, QSize
from PyQt6.QtGui import QMouseEvent, QPainter, QPen, QColor

class ClickableLabel(QLabel):
    clicked = pyqtSignal(QPoint)
    roi_selected = pyqtSignal(QRect)
    roi_drawing = pyqtSignal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._p0: QPoint | None = None
        self._p1: QPoint | None = None
        self._dragging = False
        self._confirmed = False
        self._frame_size = QSize(0, 0) # Sử dụng QSize để gọn hơn

        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter) # Quan trọng để tính offset

    def set_frame_size(self, w: int, h: int):
        self._frame_size = QSize(w, h)
        self.update()

    def _displayed_image_rect(self) -> QRect:
        """
        TÍNH TOÁN VỊ TRÍ ẢNH THỰC SỰ TRONG LABEL.
        Đây là nơi duy nhất xác định vùng được phép thao tác.
        """
        if self._frame_size.isEmpty():
            return self.rect()

        # Tính tỉ lệ giữ nguyên AspectRatio
        fw, fh = self._frame_size.width(), self._frame_size.height()
        lw, lh = self.width(), self.height()
        
        scale = min(lw / fw, lh / fh)
        iw, ih = int(fw * scale), int(fh * scale)
        
        # Offset (letterbox)
        ox = (lw - iw) // 2
        oy = (lh - ih) // 2
        
        return QRect(ox, oy, iw, ih)

    def _clamp_point(self, pt: QPoint) -> QPoint:
        """Ép tọa độ chuột luôn nằm trong vùng ảnh thực."""
        ir = self._displayed_image_rect()
        x = max(ir.left(), min(pt.x(), ir.right()))
        y = max(ir.top(), min(pt.y(), ir.bottom()))
        return QPoint(x, y)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            ir = self._displayed_image_rect()
            if ir.contains(event.position().toPoint()):
                pt = self._clamp_point(event.position().toPoint())
                self._p0 = pt
                self._p1 = pt
                self._dragging = True
                self._confirmed = False
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._p1 = self._clamp_point(event.position().toPoint())
            self.update()
            self.roi_drawing.emit(self._to_frame(self._current_rect()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging:
            self._dragging = False
            self._confirmed = True
            self.update()
            r = self._current_rect()
            if r.width() > 5 and r.height() > 5:
                self.roi_selected.emit(self._to_frame(r))
            else:
                # Drag quá nhỏ → coi là click thường, emit clicked
                self.clicked.emit(event.position().toPoint())
        super().mouseReleaseEvent(event)

    def _current_rect(self) -> QRect:
        if not self._p0 or not self._p1: return QRect()
        return QRect(self._p0, self._p1).normalized()

    def _to_frame(self, display_rect: QRect) -> QRect:
        """Quy đổi tọa độ Label -> Frame Gốc."""
        ir = self._displayed_image_rect()
        if self._frame_size.isEmpty() or ir.width() == 0: return display_rect

        # Tỉ lệ scale thực tế
        sx = self._frame_size.width() / ir.width()
        sy = self._frame_size.height() / ir.height()

        # Tính offset trừ đi và nhân scale
        fx = int((display_rect.left() - ir.left()) * sx)
        fy = int((display_rect.top() - ir.top()) * sy)
        fw = int(display_rect.width() * sx)
        fh = int(display_rect.height() * sy)

        return QRect(fx, fy, fw, fh)

    def paintEvent(self, event):
        super().paintEvent(event) # Vẽ Pixmap trước
        if not self._p0 or not self._p1: return

        r = self._current_rect()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw ROI
        p.fillRect(r, QColor(0, 200, 255, 30))
        pen = QPen(QColor(0, 200, 255, 255), 2)
        pen.setStyle(Qt.PenStyle.SolidLine if self._confirmed else Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(r)
        
        # Draw dimensions
        fr = self._to_frame(r)
        p.drawText(r.topLeft() + QPoint(5, -5), f"{fr.width()}x{fr.height()}")
        p.end()

    def clear_roi(self):
        self._p0 = self._p1 = None
        self._confirmed = False
        self.update()

    def restore_roi(self, frame_rect: QRect):
        """Vẽ lại ROI từ tọa độ frame gốc (gọi khi Reset)."""
        if self._frame_size.isEmpty() or frame_rect.isNull():
            return

        ir = self._displayed_image_rect()
        
        # Tính tỉ lệ scale xuôi: frame -> display
        sx = ir.width() / self._frame_size.width()
        sy = ir.height() / self._frame_size.height()

        # Quy đổi ngược lại tọa độ trên Label
        x = int(frame_rect.x() * sx) + ir.left()
        y = int(frame_rect.y() * sy) + ir.top()
        w = int(frame_rect.width() * sx)
        h = int(frame_rect.height() * sy)

        self._p0 = QPoint(x, y)
        self._p1 = QPoint(x + w, y + h)
        self._confirmed = True
        self.update()