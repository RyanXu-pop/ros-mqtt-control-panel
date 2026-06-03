from __future__ import annotations

import math
from typing import Iterable

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


SHELL_STYLE = """
QFrame#ShellPanel {
    background: rgba(15, 19, 25, 235);
    border: 1px solid rgba(83, 95, 114, 120);
    border-radius: 12px;
}
QPushButton.ShellButton {
    background: rgba(28, 34, 43, 220);
    color: #eef3fb;
    border: 1px solid rgba(91, 105, 128, 140);
    border-radius: 8px;
    padding: 8px 12px;
    font-weight: 700;
}
QPushButton.ShellButton:hover {
    background: rgba(45, 55, 70, 235);
    border-color: rgba(111, 132, 164, 190);
}
QPushButton.ShellButton:checked {
    color: #7db7ff;
    border-color: #1f7aff;
    background: rgba(20, 78, 167, 120);
}
QPushButton.IconButton {
    background: rgba(28, 34, 43, 225);
    color: #eef3fb;
    border: 1px solid rgba(91, 105, 128, 150);
    border-radius: 10px;
    font-size: 16px;
    font-weight: 800;
}
QPushButton.IconButton:hover {
    background: rgba(45, 55, 70, 240);
    border-color: rgba(125, 183, 255, 210);
}
QPushButton.IconButton:checked {
    color: #7db7ff;
    border-color: #1f7aff;
    background: rgba(20, 78, 167, 135);
}
"""


class StatusPill(QFrame):
    clicked = Signal()

    def __init__(self, title: str, value: str = "--", parent=None):
        super().__init__(parent)
        self._actionable = False
        self.setObjectName("ShellPanel")
        self.setFixedHeight(42)
        self.setMinimumWidth(96)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #7a8391; font-size: 13px;")
        layout.addWidget(self.dot)

        self.text = QLabel(f"{title}  {value}")
        self.text.setStyleSheet("color: #eef3fb; font-size: 12px; font-weight: 700;")
        layout.addWidget(self.text)

        self.title = title
        self.set_state(value)

    def set_actionable(self, actionable: bool):
        self._actionable = bool(actionable)
        self.setCursor(Qt.PointingHandCursor if actionable else Qt.ArrowCursor)

    def set_state(self, value: str, tone: str = "idle"):
        colors = {
            "ok": "#30d158",
            "warn": "#ffbf2f",
            "bad": "#ff453a",
            "active": "#1f7aff",
            "idle": "#9ba6b5",
        }
        self.text.setText(f"{self.title}  {value}")
        self.dot.setStyleSheet(f"color: {colors.get(tone, colors['idle'])}; font-size: 13px;")

    def mousePressEvent(self, event):
        if self._actionable and self.isEnabled() and event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TopStatusBar(QWidget):
    mqtt_toggle_requested = Signal()
    chassis_toggle_requested = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setStyleSheet(SHELL_STYLE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 8)
        layout.setSpacing(12)

        self.pill_mqtt = StatusPill("Broker", "断开")
        self.pill_bridge = StatusPill("MQTT节点", "启动")
        self.pill_chassis = StatusPill("底盘", "启动")
        self.pill_map = StatusPill("地图", "未载")
        self.pill_mode = StatusPill("模式", "待命")
        self.pill_pose = StatusPill("位置", "--")
        self.pill_pose.setMinimumWidth(188)
        self.pill_pose.setToolTip("当前小车在地图坐标系中的位置")
        self.pill_voltage = StatusPill("电量", "N/A")
        for pill in (
            self.pill_mqtt,
            self.pill_bridge,
            self.pill_chassis,
            self.pill_map,
            self.pill_mode,
            self.pill_pose,
            self.pill_voltage,
        ):
            layout.addWidget(pill)
        self.pill_bridge.set_actionable(True)
        self.pill_chassis.set_actionable(True)
        self.pill_bridge.setToolTip("启动或关闭机器人端 MQTT 桥接节点")
        self.pill_chassis.setToolTip("启动或关闭底盘")
        self.pill_bridge.clicked.connect(self.mqtt_toggle_requested.emit)
        self.pill_chassis.clicked.connect(self.chassis_toggle_requested.emit)

        layout.addStretch()

        self.btn_simulation = QPushButton("仿真")
        self.btn_simulation.setCheckable(True)
        self.btn_fullscreen = QPushButton("全屏")
        self.btn_settings = QPushButton("设置")
        for button in (self.btn_simulation, self.btn_fullscreen, self.btn_settings):
            button.setProperty("class", "ShellButton")
            button.setCursor(Qt.PointingHandCursor)
            button.hide()

        self._bind_store()
        self.refresh()

    def _bind_store(self):
        self.store.mqtt_connection_changed.connect(lambda *_: self.refresh())
        if hasattr(self.store, "robot_link_changed"):
            self.store.robot_link_changed.connect(lambda *_: self.refresh())
        self.store.chassis_alive_changed.connect(lambda *_: self.refresh())
        self.store.chassis_service_changed.connect(lambda *_: self.refresh())
        self.store.mqtt_service_changed.connect(lambda *_: self.refresh())
        self.store.map_data_changed.connect(lambda *_: self.refresh())
        self.store.service_busy_changed.connect(lambda *_: self.refresh())
        self.store.mapping_state_changed.connect(lambda *_: self.refresh())
        self.store.navigation_state_changed.connect(lambda *_: self.refresh())
        self.store.navigation_busy_changed.connect(lambda *_: self.refresh())
        self.store.voltage_changed.connect(lambda *_: self.refresh())
        self.store.robot_pose_changed.connect(lambda *_: self.refresh())

    def refresh(self):
        self.pill_mqtt.set_state("已连接" if self.store.mqtt_broker_connected else "断开", "ok" if self.store.mqtt_broker_connected else "bad")

        mqtt_busy = self.store.service_busy("mqtt")
        mqtt_action = self.store.service_busy_action("mqtt")
        if mqtt_busy:
            self.pill_bridge.set_state("关闭中" if mqtt_action == "stopping" else "启动中", "warn")
            self.pill_bridge.setEnabled(False)
        elif self.store.mqtt_running and getattr(self.store, "robot_link_alive", False):
            self.pill_bridge.set_state("在线", "ok")
            self.pill_bridge.setEnabled(True)
        elif self.store.mqtt_running or self.store.mqtt_broker_connected:
            self.pill_bridge.set_state("离线", "bad")
            self.pill_bridge.setEnabled(True)
        else:
            self.pill_bridge.set_state("启动", "idle")
            self.pill_bridge.setEnabled(True)

        chassis_busy = self.store.service_busy("chassis")
        chassis_action = self.store.service_busy_action("chassis")
        if chassis_busy:
            self.pill_chassis.set_state("关闭中" if chassis_action == "stopping" else "启动中", "warn")
            self.pill_chassis.setEnabled(False)
        elif self.store.chassis_running:
            self.pill_chassis.set_state("关闭", "ok" if self.store.chassis_alive else "warn")
            self.pill_chassis.setEnabled(True)
        else:
            self.pill_chassis.set_state("启动", "idle")
            self.pill_chassis.setEnabled(True)

        self.pill_map.set_state("已载" if self.store.map_available else "未载", "ok" if self.store.map_available else "idle")

        if self.store.mapping_running:
            self.pill_mode.set_state("建图中", "active")
        elif self.store.navigation_running:
            self.pill_mode.set_state("导航中", "active")
        elif self.store.navigation_busy:
            self.pill_mode.set_state("处理中", "warn")
        else:
            self.pill_mode.set_state("待命", "idle")

        pose = self.store.current_pose
        if pose is not None and all(
            math.isfinite(value)
            for value in (float(pose.x), float(pose.y), float(pose.angle))
        ):
            self.pill_pose.set_state(f"X {pose.x:.2f}  Y {pose.y:.2f}  {pose.angle:.0f}°", "ok")
        else:
            self.pill_pose.set_state("--", "idle")

        voltage = getattr(self.store, "_state", {}).get("voltage", 0.0)
        if voltage:
            self.pill_voltage.set_state(f"{voltage:.1f}V", "ok" if voltage >= 24.0 else "warn")
        else:
            self.pill_voltage.set_state("N/A", "idle")


class NavButton(QPushButton):
    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(f"{icon}\n{text}", parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("class", "ShellButton")
        self.setMinimumHeight(66)
        self.setStyleSheet(
            """
            QPushButton {
                text-align: center;
                line-height: 1.25;
            }
            """
        )


class SideNavigation(QFrame):
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ShellPanel")
        self.setStyleSheet(SHELL_STYLE)
        self.setFixedWidth(126)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 18, 10, 18)
        layout.setSpacing(10)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        items = [
            ("⌂", "总览"),
            ("✣", "建图"),
            ("⌁", "导航"),
            ("⌘", "遥控"),
            ("▧", "地图"),
            ("⚙", "设置"),
        ]
        for idx, (icon, label) in enumerate(items):
            button = NavButton(icon, label)
            self.group.addButton(button, idx)
            layout.addWidget(button)
            if label == "设置":
                button.clicked.connect(self.settings_requested.emit)

        self.group.button(1).setChecked(True)
        layout.addStretch()


class BottomNavigation(QFrame):
    settings_requested = Signal()
    panel_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ShellPanel")
        self.setStyleSheet(SHELL_STYLE)
        self.setFixedHeight(88)
        self._wheel_accumulator = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(54, 8, 54, 8)
        layout.setSpacing(12)

        self.group = QButtonGroup(self)
        self.group.setExclusive(False)
        self.buttons_by_key = {}
        self.panel_keys = [
            "mapping",
            "navigation",
            "teleop",
            "trace",
            "maps",
            "layers",
            "settings",
        ]
        items = [
            ("✣", "建图", "mapping"),
            ("⌁", "导航", "navigation"),
            ("⌘", "遥控", "teleop"),
            ("▤", "轨迹", "trace"),
            ("▧", "地图", "maps"),
            ("●", "图层", "layers"),
            ("⚙", "设置", "settings"),
        ]
        for idx, (icon, label, key) in enumerate(items):
            button = NavButton(icon, label)
            button.setMinimumWidth(92)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.group.addButton(button, idx)
            self.buttons_by_key[key] = button
            layout.addWidget(button)
            button.clicked.connect(lambda _checked=False, panel_key=key: self.panel_requested.emit(panel_key))
            if key == "settings":
                button.clicked.connect(self.settings_requested.emit)

    def set_active_panel(self, key: str | None):
        for panel_key, button in self.buttons_by_key.items():
            button.blockSignals(True)
            button.setChecked(bool(key) and panel_key == key)
            button.blockSignals(False)

    def wheelEvent(self, event: QWheelEvent):
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        delta_x = pixel_delta.x() if not pixel_delta.isNull() else angle_delta.x()
        delta_y = pixel_delta.y() if not pixel_delta.isNull() else angle_delta.y()
        if abs(delta_x) < abs(delta_y) or abs(delta_x) < 8:
            super().wheelEvent(event)
            return

        self._wheel_accumulator += delta_x
        if abs(self._wheel_accumulator) < 70:
            event.accept()
            return

        checked_key = next((key for key, button in self.buttons_by_key.items() if button.isChecked()), None)
        current_index = self.panel_keys.index(checked_key) if checked_key in self.panel_keys else 0
        step = 1 if self._wheel_accumulator < 0 else -1
        self._wheel_accumulator = 0
        next_index = max(0, min(len(self.panel_keys) - 1, current_index + step))
        next_key = self.panel_keys[next_index]
        self.panel_requested.emit(next_key)
        if next_key == "settings":
            self.settings_requested.emit()
        event.accept()


class DockPanelHost(QFrame):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DockPanelHost")
        self.setStyleSheet(
            SHELL_STYLE
            + """
            QFrame#DockPanelHost {
                background: rgba(13, 17, 23, 246);
                border: 1px solid rgba(100, 116, 139, 140);
                border-radius: 16px;
            }
            QLabel#DockPanelTitle {
                color: #f7f9fc;
                font-size: 22px;
                font-weight: 850;
            }
            QLabel#DockPanelSubtitle {
                color: #9ba6b5;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#DockCloseButton {
                background: rgba(255, 255, 255, 22);
                color: #eef3fb;
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 18px;
                font-size: 18px;
                font-weight: 800;
                padding: 0;
            }
            QPushButton#DockCloseButton:hover {
                background: rgba(255, 255, 255, 38);
            }
            """
        )
        self.hide()
        self._panels = {}
        self._metadata = {}
        self._active_key = None
        self._is_open = False
        self._target_pos = QPoint(0, 0)
        self._hidden_pos = QPoint(0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_label = QLabel("")
        self.title_label.setObjectName("DockPanelTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("DockPanelSubtitle")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header.addLayout(title_col, 1)

        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("DockCloseButton")
        self.btn_close.setFixedSize(36, 36)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide_panel)
        header.addWidget(self.btn_close)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        layout.addWidget(self.stack, 1)

        self.slide = QPropertyAnimation(self, b"pos", self)
        self.slide.setDuration(220)
        self.slide.setEasingCurve(QEasingCurve.OutCubic)
        self.slide.finished.connect(self._on_slide_finished)

    def add_panel(self, key: str, title: str, subtitle: str, widget: QWidget):
        self._panels[key] = widget
        self._metadata[key] = (title, subtitle)
        self.stack.addWidget(widget)

    def active_key(self) -> str | None:
        return self._active_key if self._is_open else None

    def set_panel_geometry(self, x: int, y: int, width: int, height: int):
        self.setFixedSize(width, height)
        self._target_pos = QPoint(x, y)
        self._hidden_pos = QPoint(x, y + height + 24)
        if self._is_open:
            self.move(self._target_pos)
        elif not self.isVisible():
            self.move(self._hidden_pos)

    def show_panel(self, key: str):
        if key not in self._panels:
            return
        title, subtitle = self._metadata[key]
        self._active_key = key
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.stack.setCurrentWidget(self._panels[key])
        was_open = self._is_open and self.isVisible()
        self._is_open = True
        self.show()
        self.raise_()
        self.slide.stop()
        if not was_open:
            self.move(self._hidden_pos)
        self.slide.setStartValue(self.pos())
        self.slide.setEndValue(self._target_pos)
        self.slide.start()

    def hide_panel(self):
        if not self._is_open and not self.isVisible():
            return
        self._is_open = False
        self.slide.stop()
        self.slide.setStartValue(self.pos())
        self.slide.setEndValue(self._hidden_pos)
        self.slide.start()
        self.closed.emit()

    def _on_slide_finished(self):
        if not self._is_open:
            self.hide()
            self._active_key = None


class SideDockPanelHost(QFrame):
    closed = Signal()

    def __init__(self, panel_width: int = 380, parent=None):
        super().__init__(parent)
        self._panel_width = panel_width
        self._active_key = None
        self._is_open = False
        self._panels = {}
        self._metadata = {}
        self.setObjectName("SideDockPanelHost")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.hide()
        self.setStyleSheet(
            SHELL_STYLE
            + """
            QFrame#SideDockPanelHost {
                background: rgba(13, 17, 23, 246);
                border: 1px solid rgba(100, 116, 139, 150);
                border-radius: 14px;
            }
            QLabel#DockPanelTitle {
                color: #f7f9fc;
                font-size: 20px;
                font-weight: 850;
            }
            QLabel#DockPanelSubtitle {
                color: #9ba6b5;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#DockCloseButton {
                background: rgba(255, 255, 255, 22);
                color: #eef3fb;
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 18px;
                font-size: 18px;
                font-weight: 800;
                padding: 0;
            }
            QPushButton#DockCloseButton:hover {
                background: rgba(255, 255, 255, 38);
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        self.title_label = QLabel("")
        self.title_label.setObjectName("DockPanelTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("DockPanelSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.hide()
        header.addWidget(self.title_label, 1)

        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("DockCloseButton")
        self.btn_close.setFixedSize(36, 36)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide_panel)
        header.addWidget(self.btn_close)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.stack)
        layout.addWidget(self.scroll, 1)

        self.width_anim = QPropertyAnimation(self, b"maximumWidth", self)
        self.width_anim.setDuration(220)
        self.width_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.width_anim.valueChanged.connect(lambda value: self.setMinimumWidth(int(value)))
        self.width_anim.finished.connect(self._on_width_anim_finished)

    def add_panel(self, key: str, title: str, subtitle: str, widget: QWidget):
        self._panels[key] = widget
        self._metadata[key] = (title, subtitle)
        self.stack.addWidget(widget)

    def active_key(self) -> str | None:
        return self._active_key if self._is_open else None

    def show_panel(self, key: str):
        if key not in self._panels:
            return
        title, _subtitle = self._metadata[key]
        self._active_key = key
        self.title_label.setText(title)
        self.subtitle_label.clear()
        self.stack.setCurrentWidget(self._panels[key])
        was_open = self._is_open and self.isVisible()
        self._is_open = True
        self.show()
        self.raise_()
        if was_open:
            self.setMinimumWidth(self._panel_width)
            self.setMaximumWidth(self._panel_width)
            return
        self.width_anim.stop()
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.width_anim.setStartValue(0)
        self.width_anim.setEndValue(self._panel_width)
        self.width_anim.start()

    def hide_panel(self):
        if not self._is_open and not self.isVisible():
            return
        self._is_open = False
        self.width_anim.stop()
        self.setMinimumWidth(0)
        self.width_anim.setStartValue(self.width())
        self.width_anim.setEndValue(0)
        self.width_anim.start()
        self.closed.emit()

    def _on_width_anim_finished(self):
        if self._is_open:
            self.setMinimumWidth(self._panel_width)
            self.setMaximumWidth(self._panel_width)
        else:
            self.hide()
            self._active_key = None


class MapToolDock(QFrame):
    locate_requested = Signal()
    initial_pose_requested = Signal()
    goal_pose_requested = Signal()
    fit_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    fullscreen_requested = Signal()
    scan_visibility_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ShellPanel")
        self.setStyleSheet(SHELL_STYLE)
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.btn_locate = self._make_button("◎ 定位", "跟随机器人", 72)
        self.btn_initial = self._make_button("⌖ 初位", "设置初始位姿", 72)
        self.btn_goal = self._make_button("➤ 目标", "发送导航目标", 72)
        self.btn_layers = self._make_button("● 点云", "显示/隐藏雷达点云", 72)
        self.btn_layers.setCheckable(True)
        self.btn_layers.setChecked(True)
        self.btn_zoom_out = self._make_button("−", "缩小地图")
        self.btn_zoom_in = self._make_button("+", "放大地图")
        self.btn_fit = self._make_button("适配", "适配地图", 56)
        self.btn_fullscreen = self._make_button("全屏", "全屏", 56)

        for button in (
            self.btn_locate,
            self.btn_initial,
            self.btn_goal,
            self.btn_layers,
            self.btn_zoom_out,
            self.btn_zoom_in,
            self.btn_fit,
            self.btn_fullscreen,
        ):
            layout.addWidget(button)

        self.btn_locate.clicked.connect(self.locate_requested.emit)
        self.btn_initial.clicked.connect(self.initial_pose_requested.emit)
        self.btn_goal.clicked.connect(self.goal_pose_requested.emit)
        self.btn_layers.toggled.connect(self.scan_visibility_changed.emit)
        self.btn_zoom_out.clicked.connect(self.zoom_out_requested.emit)
        self.btn_zoom_in.clicked.connect(self.zoom_in_requested.emit)
        self.btn_fit.clicked.connect(self.fit_requested.emit)
        self.btn_fullscreen.clicked.connect(self.fullscreen_requested.emit)

    def _make_button(self, text: str, tooltip: str, width: int = 40) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(width, 40)
        button.setProperty("class", "IconButton")
        return button


class ToastHost(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ShellPanel")
        self.setStyleSheet(SHELL_STYLE)
        self.setFixedHeight(52)
        self.setMinimumWidth(320)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        self.icon = QLabel("●")
        self.icon.setStyleSheet("color: #30d158; font-size: 15px;")
        layout.addWidget(self.icon)

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #eef3fb; font-size: 13px; font-weight: 700;")
        layout.addWidget(self.label, 1)

        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.fade = QPropertyAnimation(self.opacity, b"opacity", self)
        self.fade.setDuration(180)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.finished.connect(self._on_fade_finished)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)

    def show_message(self, message: str, tone: str = "success", timeout_ms: int = 2800):
        colors = {"success": "#30d158", "info": "#7db7ff", "warning": "#ffbf2f", "error": "#ff453a"}
        marks = {"success": "●", "info": "●", "warning": "!", "error": "!"}
        self.icon.setText(marks.get(tone, "●"))
        self.icon.setStyleSheet(f"color: {colors.get(tone, colors['info'])}; font-size: 15px; font-weight: 900;")
        self.label.setText(message)
        self.opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self.fade.stop()
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.start()
        self.timer.start(timeout_ms)

    def _fade_out(self):
        self.fade.stop()
        self.fade.setStartValue(self.opacity.opacity())
        self.fade.setEndValue(0.0)
        self.fade.start()

    def _on_fade_finished(self):
        if self.opacity.opacity() <= 0.01:
            self.hide()


def set_buttons_class(buttons: Iterable[QPushButton], class_name: str):
    for button in buttons:
        button.setProperty("class", class_name)
        button.style().unpolish(button)
        button.style().polish(button)
