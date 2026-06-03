# ui.py
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QFrame,
    QPushButton,
    QLabel,
    QLineEdit,
    QListWidget,
    QSlider,
    QScrollArea,
    QSizePolicy,
    QProgressBar,
)
from PySide6.QtGui import QFont, QPixmap, QPainter, QPen, QColor, QImage, QMouseEvent, QPalette
from PySide6.QtCore import Qt, Signal, QPoint, QPointF, QRectF, QSize
from scipy.ndimage import rotate
import numpy as np
import os
import logging
import yaml
import sys
from typing import Tuple, List
from src.core.constants import PATHS_CONFIG, PARAMS_CONFIG
class MapLabel(QLabel):
    """
    自定义QLabel，用于显示地图并处理所有视图交互（平移、缩放）和鼠标事件。
    该控件自己管理缩放比例(scale_factor)和平移偏移量(pan_offset)。
    """
    # 发送点击事件的信号，参数为鼠标事件对象
    clicked = Signal(QMouseEvent)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 400)
        self.setAlignment(Qt.AlignCenter)
        
        # 视图控制状态
        self.pan_zoom_mode = False
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 5.0
        self.pan_offset = QPointF(0.0, 0.0)
        self.drag_start_position = QPoint()

        # 存储原始、未经缩放和绘制的Pixmap
        self.base_pixmap = None
        self.dynamic_elements = {}
        self.scan_data = None
        self.path_data = None  # 全局路径规划：[{"x": float, "y": float}, ...]
        
        # 建图模式标志
        self.mapping_mode = False
        self.live_map_data = None  # 实时地图数据（numpy array）
        self.live_map_info = None  # 地图元数据

    def set_base_pixmap(self, pixmap):
        """设置最基础的、不带任何机器人/目标绘制的地图Pixmap"""
        self.base_pixmap = pixmap
        # 根据当前可用区域自动拟合缩放
        self.scale_factor = 1.0
        self.pan_offset = QPointF(0.0, 0.0)
        self.update_auto_fit_scale()

    def set_dynamic_elements(self, elements):
        self.dynamic_elements = elements
        self.update()

    def set_scan_data(self, scan_data: dict):
        """缓存最新的雷达数据，并在下一帧重绘"""
        self.scan_data = scan_data
        self.update()

    def set_path_data(self, path_points: list):
        """缓存全局路径规划数据，并触发重绘"""
        self.path_data = path_points
        self.update()

    def set_mapping_mode(self, enabled: bool):
        """切换建图模式"""
        self.mapping_mode = enabled
        if not enabled:
            self.live_map_data = None
            self.live_map_info = None
        self.update()

    def update_live_map(self, map_data: dict):
        """
        更新实时建图数据
        map_data: {"width", "height", "resolution", "origin_x", "origin_y", "data"}
        其中 data 是 numpy array (height, width)
        """
        if not self.mapping_mode:
            return
        
        self.live_map_data = map_data.get('data')
        self.live_map_info = {
            'width': map_data.get('width', 0),
            'height': map_data.get('height', 0),
            'resolution': map_data.get('resolution', 0.05),
            'origin_x': map_data.get('origin_x', 0.0),
            'origin_y': map_data.get('origin_y', 0.0),
        }
        
        # 将 OccupancyGrid 数据转换为 QPixmap
        if self.live_map_data is not None:
            self._convert_map_to_pixmap()
        
        self.update()

    def _convert_map_to_pixmap(self):
        """将实时地图数据转换为 QPixmap 并设置为 base_pixmap"""
        if self.live_map_data is None or self.live_map_info is None:
            return
        
        try:
            data = self.live_map_data
            height, width = data.shape
            
            # OccupancyGrid 值：255=未知（灰色），0=空闲（白色），100=障碍（黑色）
            # 转换为灰度图像：未知=128, 空闲=255, 障碍=0
            img_data = np.zeros((height, width), dtype=np.uint8)
            img_data[data == 255] = 128  # 未知 -> 灰色
            img_data[data == 0] = 255     # 空闲 -> 白色
            img_data[data == 100] = 0     # 障碍 -> 黑色
            # 中间值按比例映射
            mask_other = (data != 255) & (data != 0) & (data != 100)
            img_data[mask_other] = 255 - (data[mask_other] * 255 / 100).astype(np.uint8)
            
            # 翻转 Y 轴（ROS 地图原点在左下，Qt 原点在左上）
            # 使用 np.ascontiguousarray 确保内存是 C 连续的，否则 QImage 会报错
            img_data = np.ascontiguousarray(np.flipud(img_data))
            
            # 转换为 QImage
            qimg = QImage(img_data.data, width, height, width, QImage.Format_Grayscale8)
            pixmap = QPixmap.fromImage(qimg.copy())  # copy() 确保数据独立
            
            # 更新 base_pixmap
            self.base_pixmap = pixmap
            self.update_auto_fit_scale()
        except Exception as e:
            logging.warning(f"转换地图数据失败: {e}")

    def set_pan_zoom_mode(self, enabled):
        """切换平移/缩放模式"""
        self.pan_zoom_mode = enabled
        self.setCursor(Qt.OpenHandCursor if enabled else Qt.ArrowCursor)

    def wheelEvent(self, event: QMouseEvent):
        """处理鼠标滚轮事件以进行缩放（无级调节，并以鼠标为中心缩放）"""
        if not self.pan_zoom_mode:
            return

        try:
            import math
            old_scale = self.scale_factor
            # 使用指数因子实现无级平滑缩放；120 为典型一格
            factor = math.exp(event.angleDelta().y() * 0.0015)
            new_scale = old_scale * factor
            # 约束范围
            new_scale = max(self.min_scale, min(self.max_scale, new_scale))

            # 以鼠标为中心缩放，调整平移量使鼠标所指地图点保持不动
            mouse_pos = QPointF(event.pos())
            center_offset = self.get_map_center_offset()
            # 鼠标对应到缩放前的地图局部坐标（像素）
            local_before = (mouse_pos - self.pan_offset - center_offset) / old_scale
            # 应用新缩放后，计算需要的平移使该点仍位于鼠标处
            self.scale_factor = new_scale
            self.pan_offset = mouse_pos - center_offset - local_before * self.scale_factor

            self.update()
        except Exception:
            # 回退到简单缩放
            if event.angleDelta().y() > 0:
                self.scale_factor *= 1.05
            else:
                self.scale_factor /= 1.05
            self.scale_factor = max(self.min_scale, min(self.max_scale, self.scale_factor))
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.pan_zoom_mode:
                self.drag_start_position = event.pos()
                self.setCursor(Qt.ClosedHandCursor)
            else:
                # 在非平移模式下，发出点击信号
                self.clicked.emit(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.pan_zoom_mode and (event.buttons() & Qt.LeftButton):
            delta = QPointF(event.pos() - self.drag_start_position)
            self.pan_offset += delta
            self.drag_start_position = event.pos()
            self.update() # 触发重绘
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.pan_zoom_mode and event.button() == Qt.LeftButton:
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)
        
    def get_map_center_offset(self):
        if not self.base_pixmap: return QPointF(0,0)
        scaled_width = self.base_pixmap.width() * self.scale_factor
        scaled_height = self.base_pixmap.height() * self.scale_factor
        return QPointF((self.width() - scaled_width) / 2.0, (self.height() - scaled_height) / 2.0)

    def update_auto_fit_scale(self):
        """根据当前控件尺寸自动计算缩放，使地图尽量铺满可视区域（保持比例）"""
        if not self.base_pixmap:
            return
        if self.width() <= 0 or self.height() <= 0:
            return

        pix_w = self.base_pixmap.width()
        pix_h = self.base_pixmap.height()
        if pix_w <= 0 or pix_h <= 0:
            return

        # 预留少量内边距，避免紧贴边框
        margin_ratio = 0.96
        scale_x = (self.width() * margin_ratio) / pix_w
        scale_y = (self.height() * margin_ratio) / pix_h
        scale = min(scale_x, scale_y)

        # 约束在允许范围内
        scale = max(self.min_scale, min(self.max_scale, scale))
        self.scale_factor = scale
        self.pan_offset = QPointF(0.0, 0.0)
        self.update()

    def resizeEvent(self, event):
        """随窗口尺寸变化自动适配缩放（非平移/缩放模式下）"""
        super().resizeEvent(event)
        if not self.pan_zoom_mode:
            self.update_auto_fit_scale()

    def get_map_pixel_from_mouse_pos(self, mouse_pos: QPoint):
        if not self.base_pixmap: return None
        map_center_offset = self.get_map_center_offset()
        
        pos_on_scaled_map = QPointF(mouse_pos) - self.pan_offset - map_center_offset
        
        map_x = pos_on_scaled_map.x() / self.scale_factor
        map_y = pos_on_scaled_map.y() / self.scale_factor
        
        if 0 <= map_x < self.base_pixmap.width() and 0 <= map_y < self.base_pixmap.height():
            return QPointF(map_x, map_y)
        return None

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.base_pixmap: return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        map_center_offset = self.get_map_center_offset()
        transform_origin = self.pan_offset + map_center_offset
        
        painter.translate(transform_origin)
        painter.scale(self.scale_factor, self.scale_factor)
        
        painter.drawPixmap(QPointF(0,0), self.base_pixmap)

        if self.dynamic_elements:
            map_info = self.dynamic_elements.get('map_info', {})
            if not map_info: return
            
            resolution = map_info['resolution']
            origin = map_info['origin']
            height = map_info['height']
            
            # Draw robot
            robot_x, robot_y, robot_angle = self.dynamic_elements.get('robot_pos', (None, None, None))
            enable_shared_origin = self.dynamic_elements.get('enable_shared_origin', False)
            
            if enable_shared_origin:
                # 额外绘制一个原点标记
                origin_pixel_x = int((0.0 - origin[0]) / resolution)
                origin_pixel_y = int((0.0 - origin[1]) / resolution)
                origin_pixel_y = height - origin_pixel_y
                painter.setPen(QPen(QColor(100, 100, 100), 1 / self.scale_factor))
                painter.setBrush(QColor(100, 100, 100, 150))
                painter.drawEllipse(QPointF(origin_pixel_x, origin_pixel_y), 4 / self.scale_factor, 4 / self.scale_factor)
                font = painter.font()
                font.setPixelSize(int(10 / self.scale_factor))
                painter.setFont(font)
                painter.setPen(QPen(QColor(100, 100, 100)))
                painter.drawText(QPointF(origin_pixel_x + 6 / self.scale_factor, origin_pixel_y), "(0,0)")

            if robot_x is not None and robot_y is not None:
                robot_pixel_x = int((robot_x - origin[0]) / resolution)
                robot_pixel_y = int((robot_y - origin[1]) / resolution)
                robot_pixel_y = height - robot_pixel_y
                
                painter.setPen(QPen(QColor(255, 0, 0), 3 / self.scale_factor))
                painter.setBrush(QColor(255, 0, 0))
                painter.drawEllipse(QPointF(robot_pixel_x, robot_pixel_y), 8 / self.scale_factor, 8 / self.scale_factor)
                
                angle_rad = np.deg2rad(robot_angle if robot_angle is not None else 0.0)
                arrow_length = 20 / self.scale_factor
                end_x = robot_pixel_x + arrow_length * np.cos(angle_rad)
                end_y = robot_pixel_y - arrow_length * np.sin(angle_rad)
                painter.setPen(QPen(QColor(255, 0, 0), 2 / self.scale_factor))
                painter.drawLine(QPointF(robot_pixel_x, robot_pixel_y), QPointF(end_x, end_y))

            # Draw target
            target_x, target_y = self.dynamic_elements.get('target_pos', (None, None))
            if target_x is not None and target_y is not None:
                target_pixel_x = int((target_x - origin[0]) / resolution)
                target_pixel_y = int((target_y - origin[1]) / resolution)
                target_pixel_y = height - target_pixel_y
                
                painter.setPen(QPen(QColor(0, 0, 255), 2 / self.scale_factor))
                painter.setBrush(QColor(0, 0, 255, 150))
                rect_size = 10 / self.scale_factor
                painter.drawRect(QRectF(target_pixel_x - rect_size / 2, target_pixel_y - rect_size / 2, rect_size, rect_size))

            # --- Draw Global Path ---
            if self.path_data and len(self.path_data) >= 2:
                try:
                    pen = QPen(QColor(0, 200, 80, 180), max(1.5, 2.5 / self.scale_factor))
                    pen.setStyle(Qt.SolidLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)

                    prev_point = None
                    for pt in self.path_data:
                        px = (pt.get('x', 0.0) - origin[0]) / resolution
                        py = height - (pt.get('y', 0.0) - origin[1]) / resolution
                        cur_point = QPointF(px, py)
                        if prev_point is not None:
                            painter.drawLine(prev_point, cur_point)
                        prev_point = cur_point
                except Exception:
                    pass

            # --- Draw LiDAR Scan Points ---
            if self.scan_data and robot_x is not None and robot_y is not None and robot_angle is not None:
                try:
                    angle_min = self.scan_data.get('angle_min', 0.0)
                    angle_inc = self.scan_data.get('angle_increment', 0.0)
                    ranges = self.scan_data.get('ranges', [])
                    
                    if ranges:
                        # 配置雷达点笔刷：极细的红点，加一点透明度叠加显示
                        painter.setPen(QPen(QColor(255, 40, 40, 200), max(1.0, 2 / self.scale_factor)))
                        
                        # 小车的世界朝向(弧度)
                        robot_yaw = np.deg2rad(robot_angle)
                        
                        # 批量计算优化 (使用 numpy)
                        ranges_arr = np.array(ranges)
                        # 滤除异常值: 雷达最小感应距离大约0.05，最大通常不会超过30米，无穷大或0都是无效点
                        valid_mask = (ranges_arr > 0.05) & (ranges_arr < 30.0) 
                        valid_indices = np.where(valid_mask)[0]
                        
                        if len(valid_indices) > 0:
                            # 获取有效的距离和对应的激光束角度
                            valid_ranges = ranges_arr[valid_indices]
                            ray_angles = angle_min + valid_indices * angle_inc
                            
                            # 激光束角度转换为世界坐标系下的绝对角度
                            absolute_angles = robot_yaw + ray_angles
                            
                            # 极坐标 -> 世界笛卡尔坐标
                            world_points_x = robot_x + valid_ranges * np.cos(absolute_angles)
                            world_points_y = robot_y + valid_ranges * np.sin(absolute_angles)
                            
                            # 世界笛卡尔坐标 -> UI 像素坐标
                            pixel_x_arr = (world_points_x - origin[0]) / resolution
                            pixel_y_arr = height - ((world_points_y - origin[1]) / resolution)
                            
                            # 批量绘制点云
                            points_to_draw = [QPointF(x, y) for x, y in zip(pixel_x_arr, pixel_y_arr)]
                            painter.drawPoints(points_to_draw)
                            
                except Exception as e:
                    # 忽略绘制错误以免导致UI崩溃
                    pass


class UIManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.central_widget = QWidget()
        self.map_label = None  # 地图显示标签
        self.shared_origin_mode = False  # 共同原点设置模式标志
        self.target_x_label = None
        self.target_y_label = None
        self.label_x = None  # 当前目标 X 显示
        self.label_y = None  # 当前目标 Y 显示
        self.label_angle = None  # 当前目标角度显示
        self.x_edit = None
        self.y_edit = None
        self.angle_edit = None
        self.buttonST = None
        self.buttonSA = None
        self.label_rx = None
        self.label_ry = None
        self.label_rz = None
        self.label_rd = None
        self.initial_x_edit = None
        self.initial_y_edit = None
        self.initial_yaw_edit = None
        self.button_set_initial = None
        self.button_save_initial = None
        self.button_recall_initial = None
        self.status_label = None
        self.start_bridge_button = None
        self.start_chassis_button = None
        self.start_navigation_button = None
        self.button_settings = None
        self.button_record_position_xlsx_start = None
        self.button_record_position_xlsx_stop = None
        self.button_record_position = None
        self.button_delete_selected_record = None
        self.recorded_positions_display = None
        self.battery_progress_bar = None
        self.pan_zoom_mode = False
        self.target_x_edit = None
        self.target_y_edit = None
        # 视图（缩放/平移）是否已根据config初始化
        self.view_initialized_from_config = False
        
        # 提前创建MapLabel实例，确保它在任何UI设置和数据加载前都已存在
        self.map_label = MapLabel()
        # 将信号连接也移到此处
        self.map_label.clicked.connect(self.main_window.on_canvas_click)

    def setup_ui(self):
        """设置主界面（沉浸式地图 + 右侧检查器，macOS HIG 风格）"""
        central_widget = QWidget()
        self.main_window.setCentralWidget(central_widget)

        root = QHBoxLayout(central_widget)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # --- Left: Stage (Map) ---
        stage = QFrame()
        stage.setObjectName("stageFrame")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)
        stage_layout.addWidget(self.map_label, 1)
        root.addWidget(stage, 1)  # stretch=1 -> occupy most space

        # --- Right: Inspector (Sidebar) ---
        # 右侧整体采用滚动区域以适配小屏
        scroll = QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        root.addWidget(scroll, 0)

        sidebar_container = QWidget()
        sidebar_container.setObjectName("inspectorSidebar")
        sidebar_container.setFixedWidth(320)
        scroll.setWidget(sidebar_container)

        sidebar_layout = QVBoxLayout(sidebar_container)
        sidebar_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_layout.setSpacing(12)

        # ===== 引入独立组件模块 =====
        from src.ui.telemetry_widget import TelemetryWidget
        from src.ui.navigation_widget import NavigationWidget
        from src.ui.control_panel_widget import ControlPanelWidget

        # ===== Component 1: 遥测与状态盘 =====
        self.telemetry_widget = TelemetryWidget()
        sidebar_layout.addWidget(self.telemetry_widget)

        # 兼容旧版 my_main_window 里的硬编码引用（过渡期保留）
        # 实际更推荐逐步改写 main_window 使用 self.ui.telemetry_widget.update_voltage()
        self.label_voltage = self.telemetry_widget.label_voltage
        self.label_battery_percent = self.telemetry_widget.label_battery_percent
        self.battery_progress_bar = self.telemetry_widget.battery_progress_bar
        self.connection_dot = self.telemetry_widget.connection_dot
        self.connection_text = self.telemetry_widget.connection_text
        self.label_chassis_status = self.telemetry_widget.label_chassis_status
        self.status_label = self.telemetry_widget.status_label
        
        self.label_rx = self.telemetry_widget.label_rx
        self.label_ry = self.telemetry_widget.label_ry
        self.label_rz = self.telemetry_widget.label_rz
        self.label_rd = self.telemetry_widget.label_rd

        # ===== Component 2: 导航控制盘 =====
        self.navigation_widget = NavigationWidget()
        
        # 将内部信号直接连到 main_window 的具体执行方法
        self.navigation_widget.signal_target_changed.connect(self.on_target_coords_changed)
        self.navigation_widget.signal_send_target.connect(self.main_window.send_coordinates)
        self.navigation_widget.signal_send_angle.connect(self.main_window.send_angle)
        
        sidebar_layout.addWidget(self.navigation_widget)
        
        # 兼容旧版引用
        self.x_edit = self.navigation_widget.x_edit
        self.y_edit = self.navigation_widget.y_edit
        self.angle_edit = self.navigation_widget.angle_edit

        # ===== Card 3: 初始位姿 (这部分较薄，暂时保留) =====
        init_card, init_layout = self.create_card_frame("初始位姿")
        init_grid = QGridLayout()
        init_grid.setHorizontalSpacing(10)
        init_grid.setVerticalSpacing(10)

        self.initial_x_edit = QLineEdit("0.014")
        self.initial_y_edit = QLineEdit("-0.005")
        self.initial_yaw_edit = QLineEdit("0")
        
        self.initial_x_edit.setPlaceholderText("例如 0.00")
        self.initial_y_edit.setPlaceholderText("例如 0.00")
        self.initial_yaw_edit.setPlaceholderText("例如 0")
        
        self.initial_x_edit.textChanged.connect(self.on_initial_position_changed)
        self.initial_y_edit.textChanged.connect(self.on_initial_position_changed)
        self.initial_yaw_edit.textChanged.connect(self.on_initial_position_changed)

        init_grid.addWidget(QLabel("初始 X"), 0, 0)
        init_grid.addWidget(self.initial_x_edit, 0, 1)
        init_grid.addWidget(QLabel("初始 Y"), 1, 0)
        init_grid.addWidget(self.initial_y_edit, 1, 1)
        init_grid.addWidget(QLabel("朝向(度)"), 2, 0)
        init_grid.addWidget(self.initial_yaw_edit, 2, 1)
        init_layout.addLayout(init_grid)

        init_btns = QHBoxLayout()
        init_btns.setSpacing(10)
        self.button_set_initial = QPushButton("设置")
        self.button_save_initial = QPushButton("保存")
        self.button_recall_initial = QPushButton("恢复")
        self.button_set_initial.clicked.connect(self.main_window.set_initial_pose)
        self.button_save_initial.clicked.connect(self.main_window.save_initial_pose)
        self.button_recall_initial.clicked.connect(self.main_window.recall_initial_pose)
        init_btns.addWidget(self.button_set_initial, 1)
        init_btns.addWidget(self.button_save_initial, 1)
        init_btns.addWidget(self.button_recall_initial, 1)
        init_layout.addLayout(init_btns)

        # 可选：共同原点 + 平移/缩放模式（依 config）
        try:
            from src.core.constants import PARAMS_CONFIG
            if PARAMS_CONFIG.get("show_set_origin_button", True):
                self.button_set_shared_origin = QPushButton("设置共同原点")
                self.button_set_shared_origin.setCheckable(True)
                self.button_set_shared_origin.clicked.connect(self.toggle_shared_origin_mode)
            else:
                self.button_set_shared_origin = None
        except Exception:
            self.button_set_shared_origin = None

        try:
            from src.core.constants import PARAMS_CONFIG
            if PARAMS_CONFIG.get("show_pan_zoom_button", True):
                self.button_pan_zoom = QPushButton("平移/缩放模式")
                self.button_pan_zoom.setCheckable(True)
                self.button_pan_zoom.toggled.connect(self.toggle_pan_zoom_mode)
            else:
                self.button_pan_zoom = None
        except Exception:
            self.button_pan_zoom = None

        if self.button_set_shared_origin or self.button_pan_zoom:
            tool_row = QHBoxLayout()
            tool_row.setSpacing(10)
            if self.button_set_shared_origin:
                tool_row.addWidget(self.button_set_shared_origin, 1)
            if self.button_pan_zoom:
                tool_row.addWidget(self.button_pan_zoom, 1)
            init_layout.addLayout(tool_row)

        sidebar_layout.addWidget(init_card)

        # ===== Component 4: 系统功能控制台 =====
        self.control_panel_widget = ControlPanelWidget()
        
        # 连接系统操作逻辑
        self.control_panel_widget.signal_start_chassis.connect(self.main_window.start_chassis_action)
        self.control_panel_widget.signal_start_navigation.connect(self.main_window.start_navigation_action)
        self.control_panel_widget.signal_start_mqtt.connect(self.main_window.start_mqtt_node_action)
        
        # 连接建图逻辑
        self.control_panel_widget.signal_start_mapping.connect(self.main_window.start_mapping_action)
        self.control_panel_widget.signal_save_map.connect(self.main_window.save_map_action)
        self.control_panel_widget.signal_download_map.connect(self.main_window.download_map_action)
        self.control_panel_widget.signal_upload_map.connect(self.main_window.upload_map_action)
        
        # 连接轨迹记录逻辑
        self.control_panel_widget.signal_start_record.connect(self.main_window.start_record_position)
        self.control_panel_widget.signal_stop_record.connect(self.main_window.stop_record_position)
        
        # 连接工具按钮（缩放/共同原点）
        self.control_panel_widget.signal_set_shared_origin.connect(self.toggle_shared_origin_mode)
        self.control_panel_widget.signal_pan_zoom.connect(self.toggle_pan_zoom_mode)
        
        sidebar_layout.addWidget(self.control_panel_widget)
        
        # 兼容旧版本引用映射
        self.label_mapping_status = self.control_panel_widget.label_mapping_status
        self.start_mapping_button = self.control_panel_widget.start_mapping_button
        self.input_map_name = self.control_panel_widget.input_map_name
        self.save_map_button = self.control_panel_widget.save_map_button
        self.download_map_button = self.control_panel_widget.download_map_button
        
        self.start_chassis_button = self.control_panel_widget.start_chassis_button
        self.start_navigation_button = self.control_panel_widget.start_navigation_button
        
        self.button_record_position_xlsx_start = self.control_panel_widget.button_record_position_xlsx_start
        self.button_record_position_xlsx_stop = self.control_panel_widget.button_record_position_xlsx_stop
        
        # (工具按钮兼容检查)
        if hasattr(self.control_panel_widget, "button_set_shared_origin"):
            self.button_set_shared_origin = self.control_panel_widget.button_set_shared_origin
        if hasattr(self.control_panel_widget, "button_pan_zoom"):
            self.button_pan_zoom = self.control_panel_widget.button_pan_zoom

        # 底部工具栏：系统设置 + 仿真模式
        bottom_tools = QHBoxLayout()
        bottom_tools.setSpacing(8)

        self.button_settings = QPushButton("系统设置")
        self.button_settings.clicked.connect(self.main_window.system_setting)
        bottom_tools.addWidget(self.button_settings)

        self.button_simulation = QPushButton("🟢 启动仿真")
        self.button_simulation.setCheckable(True)
        self.button_simulation.setStyleSheet("""
            QPushButton { padding: 6px 12px; }
            QPushButton:checked { background-color: #2d7d46; color: white; }
        """)
        self.button_simulation.toggled.connect(self.main_window.toggle_simulation)
        bottom_tools.addWidget(self.button_simulation)

        sidebar_layout.addLayout(bottom_tools)

        # ===== Optional: Recorded positions list =====
        record_list_card, record_list_layout = self.create_card_frame("位置记录")
        list_btns = QHBoxLayout()
        list_btns.setSpacing(10)
        self.button_record_position = QPushButton("记录当前位置")
        self.button_delete_selected_record = QPushButton("删除选中")
        self.button_record_position.clicked.connect(self.main_window.record_current_position)
        self.button_delete_selected_record.clicked.connect(self.main_window.delete_selected_record)
        list_btns.addWidget(self.button_record_position, 1)
        list_btns.addWidget(self.button_delete_selected_record, 1)
        record_list_layout.addLayout(list_btns)

        self.recorded_positions_display = QListWidget()
        self.recorded_positions_display.setSelectionMode(QListWidget.SingleSelection)
        record_list_layout.addWidget(self.recorded_positions_display, 1)
        sidebar_layout.addWidget(record_list_card, 1)

        sidebar_layout.addStretch(1)

    def create_card_frame(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        """创建 macOS HIG 风格卡片容器（白底、圆角、轻微描边）"""
        frame = QFrame()
        frame.setObjectName("cardFrame")
        frame.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("cardTitle")
            layout.addWidget(title_label)

        return frame, layout

    # 旧版布局函数已弃用（保留逻辑在新 setup_ui 中重组）

    def apply_styles(self):
        """应用全局 V2 卓越架构：暗黑机甲风 (Cyber-Modern Dark Theme)"""
        # 不再区分 macOS / Windows，全部强上顶级极客暗黑风！
        self.main_window.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
                color: #E0E0E0;
                font-family: -apple-system, 'Segoe UI', 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', sans-serif;
            }
            QWidget#inspectorSidebar { background-color: #121212; }
            QScrollArea#inspectorScroll { border: none; background-color: transparent; }
            
            /* ======== ScrollBar 赛博朋克细线风格 ======== */
            QScrollBar:vertical {
                background: #1A1A1A;
                width: 6px;
                margin: 0px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #424242;
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover { background: #0A84FF; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
            
            /* ======== 卡片与地图边框 ======== */
            QFrame {
                border: 1px solid #2C2C2E;
                border-radius: 12px;
                background-color: #1E1E1E;
            }
            /* 地图黑底去边框更纯净 */
            QFrame#stageFrame { background-color: #0A0A0A; border: 1px solid #333333; border-radius: 12px; }
            
            /* 卡片高亮边框渐变感（由边框颜色体现） */
            QFrame#cardFrame { background-color: #1E1E1E; border: 1px solid #3A3A3C; border-radius: 12px; }
            
            /* ======== 排版与文字 ======== */
            QLabel {
                padding: 2px;
                font-size: 13px;
                color: #CCCCCC;
            }
            QLabel#cardTitle { font-size: 13px; font-weight: 800; color: #FFFFFF; padding-bottom: 4px; border-bottom: 1px solid #333333; }
            QLabel#telemetryValue { font-weight: 700; color: #0A84FF; font-family: 'SF Mono', 'Consolas', monospace; }
            QLabel#batteryVoltage { font-size: 16px; font-weight: 800; color: #FFFFFF; }
            QLabel#batteryPercent { font-size: 14px; font-weight: 800; color: #30D158; }
            QLabel#chassisStatus { font-size: 12px; color: #A0A0A5; }
            QLabel#statusLabel { font-size: 12px; color: #FF9F0A; font-family: 'SF Mono', 'Consolas', monospace; }
            
            /* ======== 状态指示灯 ======== */
            QLabel#connectionDot[state="connected"] { background-color: #30D158; border-radius: 5px; border: 1px solid #28A745; }
            QLabel#connectionDot[state="disconnected"] { background-color: #FF453A; border-radius: 5px; border: 1px solid #D73A49; }
            
            /* ======== 机甲风输入框 ======== */
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #444446;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 600;
                background-color: #2C2C2E;
                color: #FFFFFF;
                selection-background-color: #0A84FF;
                font-family: 'SF Mono', 'Consolas', monospace;
            }
            QLineEdit:focus { border: 1px solid #0A84FF; background-color: #3A3A3C; }
            
            /* ======== 机甲风按钮 ======== */
            QPushButton {
                padding: 8px 16px;
                border-radius: 8px;
                background-color: #2C2C2E;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 700;
                border: 1px solid #3A3A3C;
                font-family: -apple-system, 'SF Pro Text', 'PingFang SC', sans-serif;
            }
            QPushButton:hover { background-color: #3A3A3C; border: 1px solid #555555; }
            QPushButton:pressed { background-color: #000000; border: 1px solid #0A84FF; color: #0A84FF; }
            QPushButton:disabled { background-color: #1A1A1A; color: #444446; border: 1px solid #2C2C2E; }
            
            /* 强调按钮 (Highlight Accent Button) */
            QPushButton#accentButton { background-color: #0A84FF; color: #FFFFFF; border: none; }
            QPushButton#accentButton:hover { background-color: #339CFF; }
            QPushButton#accentButton:pressed { background-color: #0066CC; }
            QPushButton#accentButton:disabled { background-color: #0A84FF; opacity: 0.5; }
            
            /* 首要操作按钮 (Primary Action) */
            QPushButton#togglePrimary { background-color: #1a4f1e; color: #32D74B; border: 1px solid #32D74B; border-radius: 8px;}
            QPushButton#togglePrimary:hover { background-color: #32D74B; color: #000000; }
            
            /* 危险按钮 (Danger Button) */
            QPushButton#dangerButton { background-color: #3A3A3C; color: #FF453A; border: 1px solid #FF453A; }
            QPushButton#dangerButton:hover { background-color: #FF453A; color: #FFFFFF; }
            
            /* ======== 进度条/列表 ======== */
            QListWidget {
                border: 1px solid #3A3A3C;
                border-radius: 8px;
                font-size: 12px;
                font-family: 'SF Mono', 'Consolas', monospace;
                background-color: #1A1A1A;
                color: #A0A0A5;
                padding: 4px;
            }
            QListWidget::item:selected { background-color: #0A84FF; color: #FFFFFF; border-radius: 4px; }
            
            QProgressBar {
                border: 1px solid #3A3A3C;
                border-radius: 5px;
                background-color: #2C2C2E;
                color: #FFFFFF;
                font-size: 10px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #30D158, stop:1 #32D74B);
                border-radius: 4px;
            }
        """)

    def set_connection_state(self, connected: bool, text: str | None = None):
        """更新侧边栏连接状态小圆点与文字（main.py 仍可继续直接写 status_label）"""
        try:
            if hasattr(self, "connection_dot") and self.connection_dot:
                self.connection_dot.setProperty("state", "connected" if connected else "disconnected")
                # 触发 QSS 重新应用
                self.connection_dot.style().unpolish(self.connection_dot)
                self.connection_dot.style().polish(self.connection_dot)
                self.connection_dot.update()
            if hasattr(self, "connection_text") and self.connection_text:
                self.connection_text.setText(
                    ("已连接" if connected else "未连接") if text is None else text
                )
        except Exception:
            pass

    # 已废弃：MapLabel 在 __init__ 中创建并在 setup_ui 使用，不再单独提供工厂方法
    # def create_map_label(self) -> MapLabel:
    #     ...

    def update_map_display(self, map_data, robot_x=None, robot_y=None, robot_angle=None, target_x=None, target_y=None):
        try:
            if map_data is None or "image" not in map_data:
                self.map_label.setText("等待地图数据...")
                return

            image_np = map_data["image"]
            height, width = image_np.shape[:2]

            # 在建图模式下，不要重置地图图片（保持实时地图显示）
            # 只更新动态元素（机器人位置等）
            if not self.map_label.mapping_mode:
                # Set base pixmap if not set or changed
                if self.map_label.base_pixmap is None or self.map_label.base_pixmap.size() != QSize(width, height):
                    base_qimage = self.numpy_to_qimage(image_np)
                    self.map_label.set_base_pixmap(QPixmap.fromImage(base_qimage))
                    # 首次有了基础地图后，应用config中的视图设置
                    if not self.view_initialized_from_config:
                        self.apply_view_from_config()

            # Pass all dynamic info to the map label for it to draw
            elements = {
                "robot_pos": (robot_x, robot_y, robot_angle),
                "target_pos": (target_x, target_y),
                "map_info": {
                    "resolution": map_data.get("resolution", 0.05),
                    "origin": map_data.get("origin", [0, 0, 0]),
                    "height": height, "width": width
                },
                "enable_shared_origin": self.main_window.config.get('enable_shared_origin', False)
            }
            self.map_label.set_dynamic_elements(elements)
            
        except Exception as e:
            logging.error(f"更新地图显示失败: {e}", exc_info=True)
            self.map_label.setText("地图加载或更新失败")

    def apply_view_from_config(self):
        """从config加载缩放与平移并应用到MapLabel（仅一次）"""
        try:
            cfg = getattr(self.main_window, 'config', PARAMS_CONFIG)
            scale = cfg.get('map_scale', None)
            pan_x = cfg.get('map_pan_x', None)
            pan_y = cfg.get('map_pan_y', None)
            if scale is not None:
                try:
                    s = float(scale)
                    self.map_label.scale_factor = max(self.map_label.min_scale, min(self.map_label.max_scale, s))
                except Exception:
                    pass
            if pan_x is not None and pan_y is not None:
                try:
                    self.map_label.pan_offset = QPointF(float(pan_x), float(pan_y))
                except Exception:
                    pass
            self.view_initialized_from_config = True
            self.map_label.update()
        except Exception as e:
            logging.error(f"应用视图配置失败: {e}")

    def save_view_config(self):
        """将当前缩放与平移写入config.yaml，并更新内存中的config"""
        try:
            path = 'config.yaml'
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
            else:
                cfg = {}
            if 'params' not in cfg:
                cfg['params'] = {}
            cfg['params']['map_scale'] = float(self.map_label.scale_factor)
            cfg['params']['map_pan_x'] = float(self.map_label.pan_offset.x())
            cfg['params']['map_pan_y'] = float(self.map_label.pan_offset.y())
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            # 同步到内存配置
            try:
                self.main_window.config['map_scale'] = cfg['params']['map_scale']
                self.main_window.config['map_pan_x'] = cfg['params']['map_pan_x']
                self.main_window.config['map_pan_y'] = cfg['params']['map_pan_y']
            except Exception:
                pass
            self.status_label.setText("状态: 视图已保存至 config.yaml")
        except Exception as e:
            logging.error(f"保存视图到配置失败: {e}")
            self.status_label.setText(f"状态: 保存视图失败 - {e}")
    
    # 删除：旧的缩放相关辅助方法（已由平移/缩放模式与自动保存取代）
    # def zoom_in(self): ...
    # def zoom_out(self): ...
    # def reset_zoom(self): ...
    # def on_scale_changed(self, scale_factor): ...
    # def on_slider_changed(self, value): ...
    # def save_zoom_config(self): ...

    def on_target_coords_changed(self):
        """当目标坐标输入框内容改变时，实时更新地图上的蓝色目标点"""
        try:
            # 获取输入框中的坐标值
            x_text = self.x_edit.text().strip()
            y_text = self.y_edit.text().strip()
            
            # 检查输入是否为有效数字
            if x_text and y_text:
                try:
                    x = float(x_text)
                    y = float(y_text)
                    
                    # 直接使用输入的真实世界坐标，不进行缩放变换
                    # 缩放只影响显示效果，不影响坐标值本身
                    self.main_window.target_x = x
                    self.main_window.target_y = y
                    
                    # 实时更新地图显示
                    if hasattr(self.main_window, 'map_data') and self.main_window.map_data:
                        self.update_map_display(
                            self.main_window.map_data,
                            self.main_window.robot_x,
                            self.main_window.robot_y,
                            self.main_window.robot_angle,
                            self.main_window.target_x,
                            self.main_window.target_y
                        )
                    
                except ValueError:
                    # 输入不是有效数字时，不更新显示
                    pass
        except Exception as e:
            # 忽略错误，避免影响用户输入体验
            pass
    
    def on_initial_position_changed(self):
        """当初始位置输入框内容改变时，实时更新地图上的红色小车点"""
        try:
            # 检查UI组件是否已经初始化
            if not hasattr(self, 'initial_x_edit') or not hasattr(self, 'initial_y_edit'):
                return
                
            # 获取输入框中的坐标值
            x_text = self.initial_x_edit.text().strip()
            y_text = self.initial_y_edit.text().strip()
            yaw_text = self.initial_yaw_edit.text().strip()
            
            # 检查输入是否为有效数字
            if x_text and y_text:
                try:
                    x = float(x_text)
                    y = float(y_text)
                    yaw = float(yaw_text) if yaw_text else 0.0
                    
                    # 实时更新地图显示，红色小车点会移动到新位置
                    if hasattr(self, 'map_label') and self.map_label:
                        if hasattr(self.main_window, 'map_data') and self.main_window.map_data:
                            self.update_map_display(
                                self.main_window.map_data,
                                x,
                                y,
                                yaw,
                                self.main_window.target_x,
                                self.main_window.target_y
                            )
                    
                except ValueError:
                    # 输入不是有效数字时，不更新显示
                    pass
        except Exception as e:
            # 忽略错误，避免影响用户输入体验
            pass
    
    # 移除了错误的 get_scaled_coordinates 方法
    # 缩放只影响显示效果，不应该影响真实世界坐标值
    
    def numpy_to_qimage(self, array):
        """将numpy数组转换为QImage"""
        # 确保数组是连续的
        array = np.ascontiguousarray(array)
        
        if len(array.shape) == 3:
            # 彩色图像
            height, width, channels = array.shape
            bytes_per_line = channels * width
            
            # 如果图像是RGBA格式，转换为RGB
            if channels == 4:
                # 创建RGB图像
                rgb_array = np.zeros((height, width, 3), dtype=np.uint8)
                rgb_array[:, :, 0] = array[:, :, 0]  # R
                rgb_array[:, :, 1] = array[:, :, 1]  # G
                rgb_array[:, :, 2] = array[:, :, 2]  # B
                array = rgb_array
                channels = 3
                bytes_per_line = channels * width
            
            if array.dtype == np.uint8:
                return QImage(array.data, width, height, bytes_per_line, QImage.Format_RGB888)
            else:
                # 转换为uint8
                array = (array * 255).astype(np.uint8)
                array = np.ascontiguousarray(array)
                return QImage(array.data, width, height, bytes_per_line, QImage.Format_RGB888)
        else:
            # 灰度图像
            height, width = array.shape
            bytes_per_line = width
            if array.dtype == np.uint8:
                return QImage(array.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
            else:
                # 转换为uint8
                array = (array * 255).astype(np.uint8)
                array = np.ascontiguousarray(array)
                return QImage(array.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
    
    def toggle_shared_origin_mode(self, checked):
        """切换设置共同原点模式"""
        # 检查配置是否启用此功能
        try:
            from src.core.constants import PARAMS_CONFIG
            if not PARAMS_CONFIG.get('enable_shared_origin', True):
                self.main_window.ui.status_label.setText("状态: 共同原点设置功能已禁用")
                return
        except:
            pass
            
        self.shared_origin_mode = checked
        
        if checked:
            # 进入模式时，自动退出平移缩放模式
            if self.pan_zoom_mode:
                self.button_pan_zoom.setChecked(False)
            self.button_set_shared_origin.setText("取消设置原点")
            self.status_label.setText("状态: 请在地图上点击以设置共同原点")
            self.map_label.setCursor(Qt.CrossCursor)
        else:
            self.button_set_shared_origin.setText("设置共同原点")
            self.status_label.setText("状态: 已退出共同原点设置模式")
            self.map_label.setCursor(Qt.ArrowCursor)

    def toggle_pan_zoom_mode(self, checked):
        """切换平移/缩放模式"""
        self.pan_zoom_mode = checked
        self.map_label.set_pan_zoom_mode(checked) # 通知MapLabel模式已改变
        if checked:
            # 进入模式时，自动退出原点设置模式
            if self.shared_origin_mode:
                self.button_set_shared_origin.setChecked(False)
            self.button_pan_zoom.setText("退出平移缩放")
            self.status_label.setText("状态: 进入平移/缩放模式. 可拖动和缩放地图.")
        else:
            self.button_pan_zoom.setText("平移/缩放模式")
            # 退出时自动保存当前视图到配置
            self.save_view_config()
            self.status_label.setText("状态: 退出平移/缩放模式并已保存视图")