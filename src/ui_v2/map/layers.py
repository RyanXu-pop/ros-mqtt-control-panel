import math
from typing import List

import numpy as np
from PySide6.QtCore import QPointF, Property, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsObject, QGraphicsPixmapItem

from src.core.models import MapMetadata


INSPECTION_POINT_COLORS = [
    "#0a84ff",
    "#ff9f0a",
    "#30d158",
    "#bf5af2",
    "#ff375f",
    "#64d2ff",
    "#ffd60a",
    "#5e5ce6",
]


def inspection_point_color(index: int) -> str:
    return INSPECTION_POINT_COLORS[(max(1, int(index)) - 1) % len(INSPECTION_POINT_COLORS)]


class GridLayer(QGraphicsObject):
    """Background grid layer."""

    def __init__(self, size: float = 1.0, color: str = "#292d33"):
        super().__init__()
        self.grid_size = size
        self.color = QColor(color)
        self.setZValue(-10)

    def boundingRect(self) -> QRectF:
        return QRectF(-100, -100, 200, 200)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(self.color, 0.035))
        rect = option.exposedRect
        x_start = math.floor(rect.left() / self.grid_size) * self.grid_size
        y_start = math.floor(rect.top() / self.grid_size) * self.grid_size

        x = x_start
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += self.grid_size

        y = y_start
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += self.grid_size


class OccupancyMapLayer(QGraphicsPixmapItem):
    """Map raster layer for OccupancyGrid and static images."""

    def __init__(self):
        super().__init__()
        self.setZValue(0)
        self.setTransformationMode(Qt.FastTransformation)
        self._resolution = 0.05
        self._origin_x = 0.0
        self._origin_y = 0.0
        self._origin_yaw = 0.0

    def set_map_data(self, map_meta: MapMetadata):
        if map_meta.data is None:
            return

        self._resolution = map_meta.resolution
        self._origin_x = map_meta.origin_x
        self._origin_y = map_meta.origin_y
        self._origin_yaw = map_meta.origin_yaw

        w, h = map_meta.width, map_meta.height
        data = np.asarray(map_meta.data)
        if data.ndim == 1:
            data = data.reshape((h, w))

        if getattr(map_meta, "encoding", "image") == "occupancy_grid":
            img_data = self._occupancy_to_rgba(data)
        else:
            img_data = self._image_to_rgba(data)

        # Static image files are top-down rasters, while occupancy grids are stored
        # bottom-up in map coordinates. Only image rasters need a vertical flip here.
        if getattr(map_meta, "encoding", "image") != "occupancy_grid":
            img_data = np.flipud(img_data)
        img_data = np.ascontiguousarray(img_data)

        qimage = QImage(img_data.data, w, h, w * 4, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)
        self.setPixmap(pixmap)

        transform = QTransform()
        transform.scale(self._resolution, self._resolution)
        transform.rotateRadians(self._origin_yaw)
        self.setTransform(transform)
        self.setPos(self._origin_x, self._origin_y)

    def clear_map(self):
        self.setPixmap(QPixmap())
        self.setTransform(QTransform())
        self.setPos(0.0, 0.0)
        self.update()

    @staticmethod
    def _occupancy_to_rgba(data: np.ndarray) -> np.ndarray:
        img_data = np.full(data.shape + (4,), [242, 244, 247, 255], dtype=np.uint8)
        free_mask = (data >= 0) & (data <= 25)
        occupied_mask = (data >= 65) & (data <= 100)

        img_data[free_mask] = [255, 255, 255, 255]
        img_data[occupied_mask] = [0, 0, 0, 255]

        return img_data

    @staticmethod
    def _image_to_rgba(data: np.ndarray) -> np.ndarray:
        if data.dtype in (np.float32, np.float64):
            img_data = (np.clip(data, 0.0, 1.0) * 255).astype(np.uint8)
        else:
            img_data = data.astype(np.uint8)

        if img_data.ndim == 2:
            img_data = np.stack((img_data,) * 3, axis=-1)

        if img_data.shape[2] == 3:
            alpha = np.full(img_data.shape[:2] + (1,), 255, dtype=np.uint8)
            img_data = np.concatenate((img_data, alpha), axis=2)

        return img_data


class PathLayer(QGraphicsObject):
    """Global path rendering layer."""

    def __init__(self, color: str = "#00ff00", width: float = 0.05):
        super().__init__()
        self.path_points: List[dict] = []
        self.pen = QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.setZValue(1)

    def set_path(self, path: List[dict]):
        self.path_points = path
        self.update()

    def clear_path(self):
        self.set_path([])

    def boundingRect(self) -> QRectF:
        if not self.path_points:
            return QRectF(0, 0, 0, 0)
        min_x = min(p["x"] for p in self.path_points)
        max_x = max(p["x"] for p in self.path_points)
        min_y = min(p["y"] for p in self.path_points)
        max_y = max(p["y"] for p in self.path_points)
        margin = 0.5
        return QRectF(
            min_x - margin,
            min_y - margin,
            max_x - min_x + 2 * margin,
            max_y - min_y + 2 * margin,
        )

    def paint(self, painter: QPainter, option, widget=None):
        if len(self.path_points) < 2:
            return
        painter.setPen(self.pen)
        for i in range(len(self.path_points) - 1):
            p1 = QPointF(self.path_points[i]["x"], self.path_points[i]["y"])
            p2 = QPointF(self.path_points[i + 1]["x"], self.path_points[i + 1]["y"])
            painter.drawLine(p1, p2)


class InspectionLayer(QGraphicsObject):
    """Local inspection waypoint and route overlay."""

    INACTIVE_CORE_RADIUS_PX = 5.5
    ACTIVE_CORE_RADIUS_PX = 7.0
    INACTIVE_RING_RADIUS_PX = 9.0
    ACTIVE_RING_RADIUS_PX = 11.0
    INACTIVE_HALO_RADIUS_PX = 14.0
    ACTIVE_HALO_RADIUS_PX = 17.0

    def __init__(self):
        super().__init__()
        self.points: List[dict] = []
        self.active_id = None
        self.setZValue(4)

    def set_points(self, points: List[dict], active_id=None):
        self.prepareGeometryChange()
        self.points = sorted(list(points or []), key=lambda p: int(p.get("order", 0) or 0))
        self.active_id = active_id
        self.update()

    def clear(self):
        self.set_points([], None)

    def boundingRect(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [float(p.get("x", 0.0)) for p in self.points]
        ys = [float(p.get("y", 0.0)) for p in self.points]
        margin = 4.0
        return QRectF(
            min(xs) - margin,
            min(ys) - margin,
            max(xs) - min(xs) + margin * 2,
            max(ys) - min(ys) + margin * 2,
        )

    def paint(self, painter: QPainter, option, widget=None):
        if not self.points:
            return
        painter.setRenderHint(QPainter.Antialiasing)

        enabled_points = [p for p in self.points if p.get("enabled", True)]
        if len(enabled_points) > 1:
            path = QPainterPath(
                QPointF(float(enabled_points[0].get("x", 0.0)), float(enabled_points[0].get("y", 0.0)))
            )
            for point in enabled_points[1:]:
                path.lineTo(QPointF(float(point.get("x", 0.0)), float(point.get("y", 0.0))))
            painter.setPen(QPen(QColor(65, 140, 255, 175), 0.045, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)

        scene_to_view = painter.transform()
        for index, point in enumerate(self.points, start=1):
            x = float(point.get("x", 0.0))
            y = float(point.get("y", 0.0))
            enabled = bool(point.get("enabled", True))
            active = point.get("id") == self.active_id
            order = int(point.get("order") or index)
            marker_color = QColor(inspection_point_color(order))
            label = f"P{order}"
            core_radius = self.ACTIVE_CORE_RADIUS_PX if active else self.INACTIVE_CORE_RADIUS_PX
            ring_radius = self.ACTIVE_RING_RADIUS_PX if active else self.INACTIVE_RING_RADIUS_PX
            halo_radius = self.ACTIVE_HALO_RADIUS_PX if active else self.INACTIVE_HALO_RADIUS_PX
            fill = QColor(marker_color)
            halo = QColor(marker_color)
            halo.setAlpha(64 if active else 46)
            if not enabled:
                fill = QColor(120, 132, 150, 150)
                halo = QColor(120, 132, 150, 35)

            view_pos = scene_to_view.map(QPointF(x, y))
            painter.save()
            painter.resetTransform()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(view_pos, halo_radius, halo_radius)

            painter.setPen(QPen(QColor("#ffffff"), 2.0))
            painter.setBrush(QBrush(QColor(255, 255, 255, 235)))
            painter.drawEllipse(view_pos, ring_radius, ring_radius)

            painter.setPen(QPen(QColor(18, 28, 42, 210), 1.2))
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(view_pos, core_radius, core_radius)

            font = QFont()
            font.setPointSizeF(8.2 if active else 7.6)
            font.setBold(True)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            label_width = max(28.0, float(metrics.horizontalAdvance(label) + 14))
            label_height = 20.0
            label_rect = QRectF(
                view_pos.x() - label_width / 2.0,
                view_pos.y() - halo_radius - label_height - 5.0,
                label_width,
                label_height,
            )
            label_bg = QColor(marker_color if enabled else QColor(120, 132, 150))
            label_bg.setAlpha(235)
            painter.setPen(QPen(QColor("#ffffff"), 1.2 if active else 0.8))
            painter.setBrush(QBrush(label_bg))
            painter.drawRoundedRect(label_rect, 5.0, 5.0)
            painter.setPen(QPen(QColor("#ffffff")))
            painter.drawText(label_rect, Qt.AlignCenter, label)
            painter.restore()


class LidarLayer(QGraphicsObject):
    """Lidar point cloud layer for the current frame only."""

    def __init__(self):
        super().__init__()
        self.points: List[QPointF] = []
        self.pen = QPen(QColor(255, 59, 48, 230), 0.07)
        self.setZValue(2)

    def set_scan(self, scan_data: dict, robot_x: float, robot_y: float, robot_yaw: float):
        # Replace the previous frame so the PC stays a viewer, not a local mapper.
        self.prepareGeometryChange()
        self.points.clear()
        if not scan_data:
            self.update()
            return

        angle_min = scan_data.get("angle_min", 0.0)
        angle_increment = scan_data.get("angle_increment", 0.0)
        ranges = scan_data.get("ranges", [])

        for i, distance in enumerate(ranges):
            if distance is None or math.isnan(distance) or distance <= 0.05 or distance > 20.0:
                continue

            angle = robot_yaw + angle_min + i * angle_increment
            px = robot_x + distance * math.cos(angle)
            py = robot_y + distance * math.sin(angle)
            self.points.append(QPointF(px, py))

        self.update()

    def clear_scan(self):
        self.prepareGeometryChange()
        self.points.clear()
        self.update()

    def boundingRect(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(self.pen)
        painter.drawPoints(self.points)


class RobotItem(QGraphicsObject):
    """Robot marker with a pulsing location aura."""

    def __init__(self, size: float = 0.5):
        super().__init__()
        self.size = size
        self.setZValue(10)

        self.radius = size / 2
        self._pulse_radius = self.radius * 1.5

        self.anim = QPropertyAnimation(self, b"pulseRadius")
        self.anim.setDuration(2000)
        self.anim.setStartValue(self.radius * 1.2)
        self.anim.setEndValue(self.radius * 4.0)
        self.anim.setLoopCount(-1)
        self.anim.start()

    @Property(float)
    def pulseRadius(self) -> float:
        return self._pulse_radius

    @pulseRadius.setter
    def pulseRadius(self, value: float):
        self._pulse_radius = value
        self.update()

    def boundingRect(self) -> QRectF:
        max_pulse = self.radius * 4.5
        return QRectF(-max_pulse, -max_pulse, max_pulse * 2, max_pulse * 2)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        progress = (self._pulse_radius - (self.radius * 1.2)) / (self.radius * 4.0 - self.radius * 1.2)
        progress = max(0.0, min(1.0, progress))
        alpha = int(120 * (1.0 - progress))

        painter.setBrush(QColor(0, 122, 204, alpha))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(0, 0), self._pulse_radius, self._pulse_radius)

        painter.setBrush(QColor(0, 122, 204, 60))
        painter.drawEllipse(QPointF(0, 0), self.radius * 1.2, self.radius * 1.2)

        painter.setBrush(QBrush(QColor("#007acc")))
        painter.setPen(QPen(Qt.white, 0.03, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        from PySide6.QtGui import QPolygonF

        poly = QPolygonF(
            [
                QPointF(self.radius * 1.5, 0),
                QPointF(-self.radius * 0.8, -self.radius),
                QPointF(-self.radius * 0.4, 0),
                QPointF(-self.radius * 0.8, self.radius),
            ]
        )
        painter.drawPolygon(poly)

        painter.setBrush(QBrush(QColor("#111111")))
        painter.setPen(QPen(QColor("#333333"), 0.01))
        painter.drawEllipse(QPointF(0, 0), self.radius * 0.4, self.radius * 0.4)


class ArrowItem(QGraphicsObject):
    """Interactive drag arrow layer."""

    def __init__(self, color: str = "#FF9600"):
        super().__init__()
        self.p1 = QPointF(0, 0)
        self.p2 = QPointF(0, 0)
        self._color = QColor(color)
        self.setZValue(20)

    def setLine(self, x1, y1, x2, y2):
        self.p1 = QPointF(x1, y1)
        self.p2 = QPointF(x2, y2)
        self.update()

    def boundingRect(self) -> QRectF:
        x_min = min(self.p1.x(), self.p2.x())
        x_max = max(self.p1.x(), self.p2.x())
        y_min = min(self.p1.y(), self.p2.y())
        y_max = max(self.p1.y(), self.p2.y())
        margin = 0.5
        return QRectF(x_min - margin, y_min - margin, x_max - x_min + 2 * margin, y_max - y_min + 2 * margin)

    def paint(self, painter: QPainter, option, widget=None):
        dx = self.p2.x() - self.p1.x()
        dy = self.p2.y() - self.p1.y()
        length = math.hypot(dx, dy)
        if length < 0.05:
            return

        painter.setRenderHint(QPainter.Antialiasing)

        main_pen = QPen(self._color, 0.05, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(main_pen)
        painter.drawLine(self.p1, self.p2)

        angle = math.atan2(dy, dx)
        arrow_size = 0.3

        arrow_p1 = self.p2 - QPointF(
            math.cos(angle + math.pi / 6) * arrow_size,
            math.sin(angle + math.pi / 6) * arrow_size,
        )
        arrow_p2 = self.p2 - QPointF(
            math.cos(angle - math.pi / 6) * arrow_size,
            math.sin(angle - math.pi / 6) * arrow_size,
        )

        from PySide6.QtGui import QPolygonF

        polygon = QPolygonF([self.p2, arrow_p1, arrow_p2])

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawPolygon(polygon)
