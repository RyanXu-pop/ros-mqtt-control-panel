from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from src.core.constants import CONFIG
from src.ui_v2.components.dock_panels import (
    DockSettingsPanel,
    LayersDockPanel,
    MapFilesDockPanel,
    MappingDockPanel,
    NavigationDockPanel,
)
from src.ui_v2.components.vehicle_shell import (
    BottomNavigation,
    MapToolDock,
    SideDockPanelHost,
    ToastHost,
    TopStatusBar,
)
from src.ui_v2.map.map_view import MapGraphicsView
from src.ui_v2.panels.control_panel import ControlPanel
from src.ui_v2.panels.pose_panel import PoseRecordPanel
from src.ui_v2.panels.telemetry_panel import TelemetryPanel
from src.ui_v2.panels.teleop_panel import TeleopPanel


class MainLayoutWidget(QWidget):
    """
    V2 shell layout: top status, persistent map stage, right task summary and
    Tesla-style bottom dock. Business signals remain owned by existing panels.
    """

    def __init__(self, store, inspection_manager=None, patrol_controller=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.inspection_manager = inspection_manager
        self.patrol_controller = patrol_controller
        self._setup_ui()

    def _setup_ui(self):
        self.setObjectName("RobotShell")
        self.setStyleSheet(
            """
            QWidget#RobotShell {
                background: #0b0f15;
            }
            QFrame#MapFrame {
                background: #101720;
                border: 1px solid rgba(84, 96, 116, 120);
                border-radius: 12px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_status = TopStatusBar(self.store)
        root.addWidget(self.top_status)
        self.btn_simulation = self.top_status.btn_simulation
        self.btn_fullscreen = self.top_status.btn_fullscreen
        self.btn_settings = self.top_status.btn_settings

        center_row = QHBoxLayout()
        center_row.setContentsMargins(12, 8, 12, 8)
        center_row.setSpacing(12)
        root.addLayout(center_row, 1)

        self.map_frame = QFrame()
        self.map_frame.setObjectName("MapFrame")
        map_layout = QVBoxLayout(self.map_frame)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(0)
        self.map_view = MapGraphicsView()
        self.map_view.setParent(self.map_frame)
        map_layout.addWidget(self.map_view)
        center_row.addWidget(self.map_frame, 1)

        self.control_panel = ControlPanel(self.store)
        self.control_panel.setParent(self)
        self.control_panel.hide()
        self.telemetry_panel = TelemetryPanel(self.store)
        self.telemetry_panel.setParent(self)
        self.telemetry_panel.hide()
        self.pose_panel = PoseRecordPanel(dock_mode=True)
        self.teleop_panel = TeleopPanel(dock_mode=True)

        self.bottom_nav = BottomNavigation()
        self.bottom_nav.panel_requested.connect(self.toggle_dock_panel)
        root.addWidget(self.bottom_nav)

        self.mapping_panel = MappingDockPanel(self.control_panel, self.store)
        self.navigation_panel = NavigationDockPanel(self.control_panel, self.store)
        self.inspection_panel = None
        self.map_files_panel = MapFilesDockPanel(self.control_panel, self.store)
        self.settings_panel = DockSettingsPanel(CONFIG, self)
        self.control_panel.input_map_name.textChanged.connect(self._sync_dock_map_names)

        self.map_tools = MapToolDock(self.map_view)
        self.map_tools.initial_pose_requested.connect(self.control_panel.sig_set_initial_pose.emit)
        self.map_tools.goal_pose_requested.connect(self.control_panel.sig_set_goal_pose.emit)
        self.map_tools.zoom_in_requested.connect(self.map_view.zoom_in)
        self.map_tools.zoom_out_requested.connect(self.map_view.zoom_out)
        self.map_tools.fit_requested.connect(self.map_view.fit_to_content)
        self.map_tools.fullscreen_requested.connect(self.btn_fullscreen.click)
        self.map_tools.scan_visibility_changed.connect(self.map_view.set_scan_visible)
        self.map_tools.hide()

        self.btn_locate_me = self.map_tools.btn_locate

        self.layers_panel = LayersDockPanel(self.map_view, self.map_tools)

        self.dock_panel_host = SideDockPanelHost(panel_width=480)
        self.dock_panel_host.add_panel("mapping", "建图", "SLAM Mapping / 实时地图回传", self.mapping_panel)
        self.dock_panel_host.add_panel("navigation", "导航", "Navigation2 / 位姿与目标点", self.navigation_panel)
        self.dock_panel_host.add_panel("teleop", "遥控", "键盘遥控说明与急停", self.teleop_panel)
        self.dock_panel_host.add_panel("trace", "轨迹", "位姿记录与轨迹表入口", self.pose_panel)
        self.dock_panel_host.add_panel("maps", "地图", "上传、下载与地图命名", self.map_files_panel)
        self.dock_panel_host.add_panel("layers", "图层", "地图、点云与路径显示", self.layers_panel)
        self.dock_panel_host.add_panel("settings", "设置", "显示、MQTT、SSH 与 ROS 话题", self.settings_panel)
        self.dock_panel_host.closed.connect(lambda: self.bottom_nav.set_active_panel(None))
        self.dock_panel_host.width_anim.valueChanged.connect(lambda *_: self._position_overlays())
        center_row.addWidget(self.dock_panel_host)

        self.toast_host = ToastHost(self)

    def _sync_dock_map_names(self, name: str):
        for editor in (
            getattr(self.mapping_panel, "input_map_name", None),
            getattr(self.map_files_panel, "input_map_name", None),
        ):
            if editor is not None and editor.text() != name:
                editor.setText(name)

    def toggle_dock_panel(self, key: str):
        if self.dock_panel_host.active_key() == key:
            self.dock_panel_host.hide_panel()
        else:
            self.open_dock_panel(key)

    def open_dock_panel(self, key: str):
        self._position_overlays()
        self.dock_panel_host.show_panel(key)
        self.bottom_nav.set_active_panel(key)

    def show_toast(self, message: str, tone: str = "success", timeout_ms: int = 2800):
        self.toast_host.show_message(message, tone=tone, timeout_ms=timeout_ms)
        self._position_overlays()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self):
        if not hasattr(self, "map_tools"):
            return

        self.toast_host.adjustSize()
        side_width = self.dock_panel_host.width() + 18 if self.dock_panel_host.isVisible() else 0
        toast_x = max(20, self.width() - side_width - self.toast_host.width() - 24)
        toast_y = self.top_status.height() + 20
        self.toast_host.move(toast_x, toast_y)
        self.toast_host.raise_()
