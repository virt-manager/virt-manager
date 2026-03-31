from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen

from .lib.i18n import _


class Sparkline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._max_points = 50
        self._color = QColor(0, 150, 0)
        self.setMinimumHeight(30)

    def set_data_array(self, data):
        self._data = list(data)
        if len(self._data) > self._max_points:
            self._data = self._data[-self._max_points:]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        painter.fillRect(0, 0, w, h, QColor(255, 255, 255))
        
        if not self._data:
            return
        
        pen = QPen(self._color, 1.5)
        painter.setPen(pen)
        
        max_val = max(self._data) if self._data else 1
        min_val = min(self._data) if self._data else 0
        
        if max_val == min_val:
            max_val = min_val + 1
        
        points = []
        for i, val in enumerate(self._data):
            x = int((i / (len(self._data) - 1)) * (w - 1)) if len(self._data) > 1 else w // 2
            y = int(h - ((val - min_val) / (max_val - min_val)) * (h - 4) - 2)
            points.append((x, max(2, min(h - 2, y))))
        
        for i in range(len(points) - 1):
            painter.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
