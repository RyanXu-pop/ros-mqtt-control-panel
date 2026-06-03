from collections import deque
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..components.manual_pose_dialog import ManualPoseDialog


class _StatusChip(QLabel):
    COLORS = {
        "ok": ("#163820", "#30d158", "#9df0aa"),
        "warn": ("#3a2d12", "#ffbf2f", "#ffe3a3"),
        "bad": ("#3b1717", "#ff453a", "#ffb3af"),
        "idle": ("#26292c", "#5b6068", "#d6d8dc"),
    }

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(30)
        self.set_state("idle", "待命")

    def set_state(self, tone: str, value: str):
        bg, border, fg = self.COLORS.get(tone, self.COLORS["idle"])
        self.setText(f"{self.title}  {value}")
        self.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 700;
            }}
            """
        )


class _Section(QWidget):
    def __init__(self, title: str, tag: str = "", expanded: bool = False):
        super().__init__()
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QPushButton()
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                color: #f2f4f8;
                text-align: left;
                font-weight: 700;
                padding: 10px 0 8px 0;
            }
            QPushButton:hover {
                color: white;
            }
            """
        )
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)

        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 12)
        self.body.setSpacing(8)
        layout.addWidget(self.content)

        self.title = title
        self.tag = tag
        self._sync()

    def toggle(self):
        self._expanded = not self._expanded
        self._sync()

    def _sync(self):
        arrow = "⌄" if self._expanded else "›"
        tag = f"   {self.tag}" if self.tag else ""
        self.header.setText(f"{arrow}  {self.title}{tag}")
        self.content.setVisible(self._expanded)


class ControlPanel(QWidget):
    sig_start_mapping = Signal()
    sig_stop_mapping = Signal()
    sig_save_map = Signal()

    sig_start_navigation = Signal()
    sig_stop_navigation = Signal()

    sig_set_initial_pose = Signal()
    sig_set_goal_pose = Signal()

    sig_manual_initial_pose = Signal(float, float, float)
    sig_manual_goal = Signal(float, float, float)

    sig_start_chassis = Signal()
    sig_start_mqtt_node = Signal()

    sig_download_map = Signal()
    sig_upload_map = Signal()

    sig_save_initial_pose = Signal()
    sig_recall_initial_pose = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._primary_action: Optional[str] = None
        self._events = deque(maxlen=5)
        self._map_loaded = bool(getattr(store, "map_available", False))
        self._mqtt_broker_connected = bool(getattr(store, "mqtt_broker_connected", False))

        self.setProperty("class", "PanelWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(330)

        self.setup_ui()
        self.bind_store()
        self.add_event("控制台已就绪")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self.task_title = QLabel("建图 / SLAM Mapping")
        self.task_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 800;")
        layout.addWidget(self.task_title)

        self.task_badge = QLabel("待命")
        self.task_badge.setAlignment(Qt.AlignLeft)
        self.task_badge.setStyleSheet("color: #7db7ff; font-size: 12px; font-weight: 800;")
        layout.addWidget(self.task_badge)

        self.summary_label = QLabel("等待连接")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #a7adb8; font-size: 12px; line-height: 1.35;")
        layout.addWidget(self.summary_label)

        chip_grid = QGridLayout()
        chip_grid.setHorizontalSpacing(8)
        chip_grid.setVerticalSpacing(8)
        self.chip_mqtt = _StatusChip("MQTT")
        self.chip_bridge = _StatusChip("本机桥接")
        self.chip_chassis = _StatusChip("底盘")
        self.chip_map = _StatusChip("地图")
        chip_grid.addWidget(self.chip_mqtt, 0, 0)
        chip_grid.addWidget(self.chip_bridge, 0, 1)
        chip_grid.addWidget(self.chip_chassis, 1, 0)
        chip_grid.addWidget(self.chip_map, 1, 1)
        layout.addLayout(chip_grid)

        self.main_action_card = QFrame()
        self.main_action_card.setObjectName("mainActionCard")
        self.main_action_card.setStyleSheet(
            """
            QFrame#mainActionCard {
                background: #171a1f;
                border: 1px solid #2f343c;
                border-radius: 8px;
            }
            """
        )
        action_layout = QVBoxLayout(self.main_action_card)
        action_layout.setContentsMargins(12, 12, 12, 12)
        action_layout.setSpacing(8)

        action_title = QLabel("推荐动作")
        action_title.setStyleSheet("color: #7f8793; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        action_layout.addWidget(action_title)

        self.primary_reason_label = QLabel("根据当前状态选择下一步")
        self.primary_reason_label.setWordWrap(True)
        self.primary_reason_label.setStyleSheet("color: #d8dde6; font-size: 12px;")
        action_layout.addWidget(self.primary_reason_label)

        self.btn_primary_action = QPushButton("启动底盘")
        self.btn_primary_action.setMinimumHeight(38)
        self.btn_primary_action.clicked.connect(self._on_primary_action_clicked)
        action_layout.addWidget(self.btn_primary_action)
        layout.addWidget(self.main_action_card)

        self.workflow_feedback = QLabel("准备就绪")
        self.workflow_feedback.setWordWrap(True)
        self.workflow_feedback.setStyleSheet("color: #dce4ef; font-size: 12px; font-weight: 700;")
        layout.addWidget(self.workflow_feedback)

        self.workflow_progress = QProgressBar()
        self.workflow_progress.setRange(0, 0)
        self.workflow_progress.setTextVisible(False)
        self.workflow_progress.setFixedHeight(5)
        self.workflow_progress.setStyleSheet(
            """
            QProgressBar {
                background: rgba(255,255,255,0.08);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #1f7aff;
                border-radius: 2px;
            }
            """
        )
        self.workflow_progress.hide()
        layout.addWidget(self.workflow_progress)

        dock_hint = QLabel("建图、导航、遥控、轨迹和地图文件已移到底部 Dock。")
        dock_hint.setWordWrap(True)
        dock_hint.setStyleSheet("color: #9ba6b5; font-size: 12px; font-weight: 700;")
        layout.addWidget(dock_hint)

        self.hidden_controls = QWidget(self)
        self.hidden_controls.hide()
        hidden_layout = QVBoxLayout(self.hidden_controls)
        hidden_layout.setContentsMargins(0, 0, 0, 0)
        hidden_layout.setSpacing(0)
        self._build_workflow_section(hidden_layout)
        self._build_map_section(hidden_layout)
        self._build_system_section(hidden_layout)

        self.events_title = QLabel("最近事件")
        self.events_title.setStyleSheet("color: #7f8793; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        layout.addWidget(self.events_title)

        self.event_labels = []
        for _ in range(5):
            label = QLabel("")
            label.setWordWrap(True)
            label.setStyleSheet("color: #d8dde6; font-size: 11px; padding: 1px 0;")
            self.event_labels.append(label)
            layout.addWidget(label)

    def _build_workflow_section(self, layout: QVBoxLayout):
        self.mapping_hint = QLabel("")
        self.mapping_hint.setWordWrap(True)
        self.mapping_hint.setStyleSheet("color: #8f98a6; font-size: 11px;")

        self.btn_toggle_mapping = QPushButton("启动建图")
        self.btn_toggle_mapping.clicked.connect(self._on_mapping_clicked)
        layout.addWidget(self.btn_toggle_mapping)
        layout.addWidget(self.mapping_hint)

        self.btn_save_map = QPushButton("保存地图到机器人")
        self.btn_save_map.clicked.connect(self.sig_save_map.emit)
        layout.addWidget(self.btn_save_map)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background: #2f343c; max-height: 1px;")
        layout.addWidget(divider)

        self.navigation_hint = QLabel("")
        self.navigation_hint.setWordWrap(True)
        self.navigation_hint.setStyleSheet("color: #8f98a6; font-size: 11px;")

        self.btn_toggle_navigation = QPushButton("启动导航")
        self.btn_toggle_navigation.clicked.connect(self._on_navigation_clicked)
        layout.addWidget(self.btn_toggle_navigation)
        layout.addWidget(self.navigation_hint)

        nav_action_layout = QHBoxLayout()
        nav_action_layout.setSpacing(8)
        self.btn_initial_pose = QPushButton("设置位姿")
        self.btn_initial_pose.clicked.connect(self.sig_set_initial_pose.emit)
        self.btn_initial_pose.setToolTip("在地图上点击并拖拽以设定小车的初始位姿")
        self.btn_goal_pose = QPushButton("发送目标")
        self.btn_goal_pose.clicked.connect(self.sig_set_goal_pose.emit)
        self.btn_goal_pose.setToolTip("在地图上点击并拖拽以设定导航目标")
        nav_action_layout.addWidget(self.btn_initial_pose)
        nav_action_layout.addWidget(self.btn_goal_pose)
        layout.addLayout(nav_action_layout)

        manual_action_layout = QHBoxLayout()
        manual_action_layout.setSpacing(8)
        self.btn_manual_initial = QPushButton("手动初位")
        self.btn_manual_initial.clicked.connect(self._on_manual_initial)
        self.btn_manual_goal = QPushButton("手动目标")
        self.btn_manual_goal.clicked.connect(self._on_manual_goal)
        manual_action_layout.addWidget(self.btn_manual_initial)
        manual_action_layout.addWidget(self.btn_manual_goal)
        layout.addLayout(manual_action_layout)

        pose_save_layout = QHBoxLayout()
        pose_save_layout.setSpacing(8)
        self.btn_save_pose = QPushButton("保存位姿")
        self.btn_save_pose.clicked.connect(self.sig_save_initial_pose.emit)
        self.btn_recall_pose = QPushButton("恢复位姿")
        self.btn_recall_pose.clicked.connect(self.sig_recall_initial_pose.emit)
        pose_save_layout.addWidget(self.btn_save_pose)
        pose_save_layout.addWidget(self.btn_recall_pose)
        layout.addLayout(pose_save_layout)

    def _build_map_section(self, layout: QVBoxLayout):
        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)
        name_label = QLabel("名称")
        name_label.setStyleSheet("color: #8f98a6; font-size: 11px;")
        self.input_map_name = QLineEdit("my_map")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.input_map_name)
        layout.addLayout(name_layout)

        map_io_layout = QHBoxLayout()
        map_io_layout.setSpacing(8)
        self.btn_download_map = QPushButton("下载地图")
        self.btn_download_map.clicked.connect(self.sig_download_map.emit)
        self.btn_upload_map = QPushButton("上传地图")
        self.btn_upload_map.clicked.connect(self.sig_upload_map.emit)
        map_io_layout.addWidget(self.btn_download_map)
        map_io_layout.addWidget(self.btn_upload_map)
        layout.addLayout(map_io_layout)

    def _build_system_section(self, layout: QVBoxLayout):
        self.btn_start_chassis = QPushButton("启动底盘")
        self.btn_start_chassis.clicked.connect(self._on_chassis_clicked)
        layout.addWidget(self.btn_start_chassis)

        self.btn_start_mqtt = QPushButton("启动 MQTT 节点")
        self.btn_start_mqtt.clicked.connect(self._on_mqtt_clicked)
        layout.addWidget(self.btn_start_mqtt)

    def bind_store(self):
        self.store.mapping_state_changed.connect(lambda _running: self._refresh_all())
        self.store.navigation_state_changed.connect(lambda _running: self._refresh_all())
        self.store.chassis_service_changed.connect(lambda _running: self._refresh_all())
        self.store.mqtt_service_changed.connect(lambda _running: self._refresh_all())
        self.store.navigation_busy_changed.connect(lambda _busy, _reason: self._refresh_all())
        self.store.chassis_alive_changed.connect(lambda _alive: self._refresh_all())
        self.store.map_data_changed.connect(self._on_map_data_changed)
        if hasattr(self.store, "mqtt_connection_changed"):
            self.store.mqtt_connection_changed.connect(self._on_mqtt_connection_changed)
        self._refresh_all()

    def _on_map_data_changed(self, _map_meta):
        self._map_loaded = True
        self._refresh_all()

    def _on_mqtt_connection_changed(self, connected: bool, message: str):
        self._mqtt_broker_connected = connected
        if message:
            self.add_event(message)
        self._refresh_all()

    def add_event(self, message: str):
        clean = " ".join(str(message or "").split())
        if not clean:
            return
        self._events.appendleft(clean)
        for idx, label in enumerate(self.event_labels):
            label.setText(self._events[idx] if idx < len(self._events) else "")

    def _set_button_class(self, button: QPushButton, class_name: str):
        button.setProperty("class", class_name)
        button.style().unpolish(button)
        button.style().polish(button)

    def _set_button_state(
        self,
        button: QPushButton,
        text: str,
        class_name: str,
        enabled: bool = True,
        reason: str = "",
    ):
        button.setText(text)
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else reason)
        self._set_button_class(button, class_name)

    def _refresh_all(self):
        self._refresh_task_title()
        self._refresh_status_chips()
        self._refresh_primary_action()
        self._refresh_workflow_controls()
        self._refresh_system_controls()

    def _refresh_task_title(self):
        if self.store.mapping_running:
            self.task_title.setText("建图 / SLAM Mapping")
            self.task_badge.setText("建图中")
        elif self.store.navigation_running or self.store.navigation_busy:
            self.task_title.setText("导航 / Navigation2")
            self.task_badge.setText("导航运行" if self.store.navigation_running else "导航处理中")
        else:
            self.task_title.setText("任务控制")
            self.task_badge.setText("待命")

    def _refresh_status_chips(self):
        if self._mqtt_broker_connected:
            self.chip_mqtt.set_state("ok", "已连")
        else:
            self.chip_mqtt.set_state("bad", "断开")

        if self.store.mqtt_running:
            self.chip_bridge.set_state("ok", "运行")
        else:
            self.chip_bridge.set_state("idle", "未启")

        chassis_alive = bool(getattr(self.store, "chassis_alive", False))
        if chassis_alive:
            self.chip_chassis.set_state("ok", "在线")
        elif self.store.chassis_running:
            self.chip_chassis.set_state("warn", "等待")
        else:
            self.chip_chassis.set_state("idle", "未启")

        if self.store.mapping_running:
            self.chip_map.set_state("warn", "建图中")
        elif self._map_loaded:
            self.chip_map.set_state("ok", "已载")
        else:
            self.chip_map.set_state("idle", "未载")

    def _refresh_primary_action(self):
        action, label, reason, class_name, enabled = self._recommend_action()
        self._primary_action = action
        self.primary_reason_label.setText(reason)
        self._set_button_state(self.btn_primary_action, label, class_name, enabled, reason)
        self.summary_label.setText(self._build_summary_text())

    def _recommend_action(self):
        if self.store.navigation_busy:
            reason = "导航正在处理，请等待当前操作完成。"
            return None, "处理中", "导航处理中", "DisabledAction", False
        if self.store.mapping_running:
            return "stop_mapping", "停止建图", "建图正在运行，完成探索后停止并保存地图。", "DangerAction", True
        if self.store.navigation_running:
            return "stop_navigation", "停止导航", "导航正在运行，可设置目标或停止导航。", "DangerAction", True
        if not self.store.chassis_running:
            return "chassis", "启动底盘", "先启动 Bringup，让机器人底层数据上线。", "PrimaryAction", True
        if not self.store.mqtt_running:
            return "mqtt", "启动 MQTT 节点", "开启机器人端 MQTT 桥接后，地图和遥测会回传到本机。", "PrimaryAction", True
        if not self._map_loaded:
            return "mapping", "开始建图", "当前没有可用地图，建议先进入 SLAM 建图。", "PrimaryAction", True
        return "navigation", "启动导航", "系统已就绪，可启动 Navigation2 并发送目标点。", "PrimaryAction", True

    def set_workflow_feedback(self, message: str, busy: bool = False, tone: str = "info"):
        clean = " ".join(str(message or "").split()) or "准备就绪"
        colors = {
            "info": "#dce4ef",
            "success": "#9df0aa",
            "warning": "#ffe3a3",
            "error": "#ffb3af",
        }
        self.workflow_feedback.setText(clean)
        self.workflow_feedback.setStyleSheet(
            f"color: {colors.get(tone, colors['info'])}; font-size: 12px; font-weight: 800;"
        )
        self.workflow_progress.setVisible(bool(busy))
        self.add_event(clean)

    def _build_summary_text(self) -> str:
        if self.store.mapping_running:
            return "SLAM 建图模式运行中"
        if self.store.navigation_running:
            return "Navigation2 导航模式运行中"
        if self.store.chassis_running and self.store.mqtt_running:
            return "机器人服务已就绪"
        return "按推荐动作完成启动顺序"

    def _refresh_workflow_controls(self):
        mapping_enabled, mapping_reason = self._mapping_available()
        nav_enabled, nav_reason = self._navigation_available()

        if self.store.mapping_running:
            self._set_button_state(self.btn_toggle_mapping, "停止建图", "DangerAction", True)
            self.btn_save_map.setEnabled(True)
            self.mapping_hint.setText("SLAM 正在运行，地图回传后可保存。")
        else:
            self._set_button_state(self.btn_toggle_mapping, "启动建图", "PrimaryAction", mapping_enabled, mapping_reason)
            self.btn_save_map.setEnabled(False)
            self.mapping_hint.setText(mapping_reason or "启动 SLAM 生成或刷新地图。")

        self.btn_save_map.setToolTip("" if self.btn_save_map.isEnabled() else "需先启动建图")

        if self.store.navigation_busy:
            text = "启动中..." if self.store.navigation_busy_reason == "starting" else "停止中..."
            self._set_button_state(self.btn_toggle_navigation, text, "DisabledAction", False, "导航处理中")
            self.navigation_hint.setText("Navigation2 正在处理，请等待结果。")
        elif self.store.navigation_running:
            self._set_button_state(self.btn_toggle_navigation, "停止导航", "DangerAction", True)
            self.navigation_hint.setText("导航运行中，可设置初始位姿或发送目标。")
        else:
            self._set_button_state(self.btn_toggle_navigation, "启动导航", "PrimaryAction", nav_enabled, nav_reason)
            self.navigation_hint.setText(nav_reason or "启动后可设置初始位姿并发送导航目标。")

        self._set_nav_controls_enabled(self.store.navigation_running and not self.store.navigation_busy)

    def _mapping_available(self):
        if self.store.navigation_running or self.store.navigation_busy:
            return False, "需先停止导航"
        if not self.store.chassis_running:
            return False, "需先启动底盘"
        if not self.store.mqtt_running:
            return False, "需先启动 MQTT 节点"
        return True, ""

    def _navigation_available(self):
        if self.store.mapping_running:
            return False, "需先停止建图"
        if self.store.navigation_busy:
            return False, "导航处理中"
        if not self.store.chassis_running:
            return False, "需先启动底盘"
        if not self.store.mqtt_running:
            return False, "需先启动 MQTT 节点"
        if not self._map_loaded:
            return False, "需先加载或保存地图"
        return True, ""

    def _refresh_system_controls(self):
        if self.store.chassis_running:
            self._set_button_state(self.btn_start_chassis, "关闭底盘", "DangerAction", True)
        else:
            self._set_button_state(self.btn_start_chassis, "启动底盘", "PrimaryAction", True)

        if self.store.mqtt_running:
            self._set_button_state(self.btn_start_mqtt, "关闭 MQTT 节点", "DangerAction", True)
        else:
            self._set_button_state(self.btn_start_mqtt, "启动 MQTT 节点", "PrimaryAction", True)

    def _set_nav_controls_enabled(self, enabled: bool):
        reason = "" if enabled else "需先启动导航"
        for button in (
            self.btn_initial_pose,
            self.btn_goal_pose,
            self.btn_manual_initial,
            self.btn_manual_goal,
            self.btn_save_pose,
            self.btn_recall_pose,
        ):
            button.setEnabled(enabled)
            button.setToolTip(reason)

    def _on_primary_action_clicked(self):
        actions = {
            "chassis": self.sig_start_chassis.emit,
            "mqtt": self.sig_start_mqtt_node.emit,
            "mapping": self.sig_start_mapping.emit,
            "stop_mapping": self.sig_stop_mapping.emit,
            "navigation": self.sig_start_navigation.emit,
            "stop_navigation": self.sig_stop_navigation.emit,
        }
        handler = actions.get(self._primary_action)
        if handler:
            handler()

    def _on_mapping_clicked(self):
        if self.store.mapping_running:
            self.sig_stop_mapping.emit()
        else:
            self.sig_start_mapping.emit()

    def _on_navigation_clicked(self):
        if self.store.navigation_busy:
            return
        if self.store.navigation_running:
            self.sig_stop_navigation.emit()
        else:
            self.sig_start_navigation.emit()

    def _on_chassis_clicked(self):
        self.sig_start_chassis.emit()

    def _on_mqtt_clicked(self):
        self.sig_start_mqtt_node.emit()

    def _on_manual_initial(self):
        dlg = ManualPoseDialog(mode="initial", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            x, y, yaw = dlg.get_values()
            self.sig_manual_initial_pose.emit(x, y, yaw)

    def _on_manual_goal(self):
        dlg = ManualPoseDialog(mode="goal", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            x, y, yaw = dlg.get_values()
            self.sig_manual_goal.emit(x, y, yaw)

    def get_map_name(self) -> str:
        return self.input_map_name.text()

    def set_map_name(self, name: str):
        if self.input_map_name.text() != name:
            self.input_map_name.setText(name)
