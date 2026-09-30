"""The map canvas and the scene items drawn on it.

Separated from the window so that file is only orchestration: what to render, when to
refresh, and what the toolbar does.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsSimpleTextItem, QGraphicsView

# Zoom at which POI names appear. Below it the dots alone stay readable; above it there is
# room for text without the labels colliding.
LABEL_ZOOM = 1.6
ZOOM_STEP = 1.25
MIN_ZOOM = 0.05
MAX_ZOOM = 40.0

FOUND_POI = QColor(120, 230, 190)
PLAYER = QColor(90, 200, 255)
LABEL = QColor(180, 245, 215)


class MapView(QGraphicsView):
    """Pan by dragging, zoom on the wheel, and report the world position on hover."""

    hovered = Signal(QPointF)
    zoomed = Signal(float)

    def __init__(self, scene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor(8, 12, 14)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)

    def wheelEvent(self, event) -> None:
        step = ZOOM_STEP if event.angleDelta().y() > 0 else 1.0 / ZOOM_STEP
        target = self.transform().m11() * step
        if MIN_ZOOM <= target <= MAX_ZOOM:
            self.scale(step, step)
            self.zoomed.emit(target)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self.hovered.emit(self.mapToScene(event.position().toPoint()))


def to_pixmap(rgb: np.ndarray) -> QPixmap:
    contiguous = np.ascontiguousarray(rgb)
    height, width, _ = contiguous.shape
    image = QImage(contiguous.data, width, height, 3 * width, QImage.Format_RGB888)
    return QPixmap.fromImage(image.copy())  # copy: the numpy buffer is temporary


def dot(scene, col, row, radius, colour, ring=False) -> QGraphicsEllipseItem:
    """A marker that keeps a constant on-screen size at any zoom."""
    item = QGraphicsEllipseItem(-radius, -radius, radius * 2, radius * 2)
    item.setPos(col, row)
    item.setBrush(QBrush(QColor(0, 0, 0, 0) if ring else colour))
    item.setPen(QPen(colour, 2.0 if ring else 1.0))
    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
    item.setZValue(10)
    scene.addItem(item)
    return item


def label(scene, col, row, text) -> QGraphicsSimpleTextItem:
    item = QGraphicsSimpleTextItem(text)
    item.setPos(col + 5, row - 6)
    item.setBrush(QBrush(LABEL))
    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
    item.setZValue(11)
    scene.addItem(item)
    return item
