import math
from typing import Optional
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from PySide6.QtCore import QEvent, Qt, Signal, QPointF
from PySide6.QtGui import QBrush, QPainter, QMouseEvent, QWheelEvent, QColor

from .layers import GridLayer, OccupancyMapLayer, PathLayer, InspectionLayer, LidarLayer, RobotItem, ArrowItem

class MapGraphicsView(QGraphicsView):
    """
    基于硬件加速的高性能地图视图部件。
    负责管理场景(Scene)、承载所有图层(Layers)，并处理缩放、平移和交互点击。
    """
    
    # 交互回调信号：(x, y, yaw, type)
    # type: 'goal' = 设定目标, 'initial_pose' = 设定初始位姿
    interaction_triggered = Signal(float, float, float, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. 场景初始化
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # 优化渲染参数
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        # 隐藏滚动条
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#171818")))
        
        # 由于 ROS 的地图坐标系是 Y 朝上，而 Qt 屏幕坐标系 Y 朝下
        # 为了符合直觉，我们反转 View 的 Y 轴 (Scale Y = -1)
        self.scale(1, -1)
        # 默认拉近一点
        self.scale(30, 30) 

        # 2. 注册图层
        self.grid_layer = GridLayer(size=1.0, color="#292d33")
        self.map_layer = OccupancyMapLayer()
        self.path_layer = PathLayer()
        self.inspection_layer = InspectionLayer()
        self.robot_item = RobotItem(size=0.4)
        self.lidar_layer = LidarLayer()
        
        # 按照 Z-Value 顺序添加至场景
        self.scene.addItem(self.grid_layer)
        self.scene.addItem(self.map_layer)
        self.scene.addItem(self.path_layer)
        self.scene.addItem(self.inspection_layer)
        self.scene.addItem(self.lidar_layer)
        self.scene.addItem(self.robot_item)
        
        # 3. 交互模式状态机
        self.interaction_mode: Optional[str] = None  # None, 'goal', 'initial'
        self._drag_start_pos: Optional[QPointF] = None
        self._scan_visible = True
        self._preview_arrow = ArrowItem(color="#FF9600")
        self.scene.addItem(self._preview_arrow)
        self._preview_arrow.setVisible(False)
        
    # ---------- API (供 Controller/Store 调用) ----------
    
    def update_map(self, map_meta):
        """收到新地图数据时调用"""
        self.map_layer.set_map_data(map_meta)

    def clear_map(self):
        self.map_layer.clear_map()
        
    def update_robot_pose(self, x: float, y: float, yaw: float):
        """更新机器人及其挂载雷达的位置"""
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            return
        self.robot_item.setPos(x, y)
        # yaw 是弧度，QGraphicsItem 的 rotation 是角度
        self.robot_item.setRotation(math.degrees(yaw))
        
    def update_scan(self, scan_data: dict, rx: float, ry: float, ryaw: float):
        self.lidar_layer.set_scan(scan_data, rx, ry, ryaw)

    def clear_scan(self):
        self.lidar_layer.clear_scan()

    def set_scan_visible(self, visible: bool):
        self._scan_visible = bool(visible)
        self.lidar_layer.setVisible(self._scan_visible)

    def zoom_in(self):
        self._zoom_at(self.viewport().rect().center(), 1.18)

    def zoom_out(self):
        self._zoom_at(self.viewport().rect().center(), 1.0 / 1.18)

    def fit_to_content(self):
        rect = self.map_layer.sceneBoundingRect()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            rect = self.scene.itemsBoundingRect()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return
        self.resetTransform()
        self.scale(1, -1)
        padded = rect.adjusted(-1.0, -1.0, 1.0, 1.0)
        self.fitInView(padded, Qt.KeepAspectRatio)
        if self.transform().m22() > 0:
            self.scale(1, -1)
        
    def update_path(self, path_points: list):
        self.path_layer.set_path(path_points)

    def clear_path(self):
        self.path_layer.clear_path()

    def update_inspection_points(self, points: list, active_id=None):
        self.inspection_layer.set_points(points or [], active_id)

    def clear_inspection_points(self):
        self.inspection_layer.clear()
        
    def set_interaction_mode(self, mode: Optional[str]):
        """开启地图交互模式 ('goal' 或 'initial_pose')"""
        self.interaction_mode = mode
        if mode:
            self.setDragMode(QGraphicsView.NoDrag)  # 禁用平移以让出左键拖拽
            self.setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(Qt.ArrowCursor)

    # ---------- 交互事件覆盖 ----------

    def viewportEvent(self, event):
        if event.type() == QEvent.NativeGesture:
            try:
                gesture_type = event.gestureType()
                zoom_gesture = getattr(Qt, "ZoomNativeGesture", None)
                if zoom_gesture is not None and gesture_type == zoom_gesture:
                    value = float(event.value())
                    factor = max(0.80, min(1.25, 1.0 + value))
                    self._zoom_at(self._event_view_pos(event), factor)
                    event.accept()
                    return True
            except Exception:
                pass
        return super().viewportEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        """Mac trackpad scroll pans; wheel / control-scroll zooms around cursor."""
        pixel_delta = event.pixelDelta()
        if not pixel_delta.isNull() and not (event.modifiers() & Qt.ControlModifier):
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - pixel_delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - pixel_delta.y())
            event.accept()
            return

        angle_delta = event.angleDelta().y()
        if angle_delta == 0:
            event.ignore()
            return
        steps = angle_delta / 120.0
        factor = 1.12 ** steps
        self._zoom_at(self._event_view_pos(event), factor)
        event.accept()

    def _zoom_at(self, view_pos, factor: float):
        if not math.isfinite(factor) or factor <= 0:
            return
        scene_before = self.mapToScene(view_pos)
        self.scale(factor, factor)
        scene_after = self.mapToScene(view_pos)
        delta = scene_after - scene_before
        self.translate(delta.x(), delta.y())

    @staticmethod
    def _event_view_pos(event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        if hasattr(event, "pos"):
            return event.pos()
        return QPointF(0, 0).toPoint()

    def mousePressEvent(self, event: QMouseEvent):
        if self.interaction_mode and event.button() == Qt.LeftButton:
            # 记录起点世界坐标
            self._drag_start_pos = self.mapToScene(event.pos())
            self._preview_arrow.setLine(self._drag_start_pos.x(), self._drag_start_pos.y(),
                                      self._drag_start_pos.x(), self._drag_start_pos.y())
            self._preview_arrow.setVisible(True)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.interaction_mode and self._drag_start_pos is not None:
            # 实时更新箭头终点
            curr_pos = self.mapToScene(event.pos())
            self._preview_arrow.setLine(self._drag_start_pos.x(), self._drag_start_pos.y(),
                                      curr_pos.x(), curr_pos.y())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.interaction_mode and event.button() == Qt.LeftButton and self._drag_start_pos:
            end_pos = self.mapToScene(event.pos())
            dx = end_pos.x() - self._drag_start_pos.x()
            dy = end_pos.y() - self._drag_start_pos.y()
            
            # 计算拖拽的朝向角 (Yaw)
            yaw = math.atan2(dy, dx)
            
            # 触发信号
            self.interaction_triggered.emit(
                self._drag_start_pos.x(),
                self._drag_start_pos.y(),
                yaw,
                self.interaction_mode
            )
            
            # 清理状态
            self._preview_arrow.setVisible(False)
            self._drag_start_pos = None
            
            # 用完后自动重置为 None
            self.set_interaction_mode(None)
        else:
            super().mouseReleaseEvent(event)
