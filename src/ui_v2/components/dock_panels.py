from __future__ import annotations

import logging
from pathlib import Path
import yaml

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.system_setting import SystemSetting
from src.ui_v2.map.layers import inspection_point_color


_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
_CHEVRON_DOWN_ICON = _ASSET_DIR.joinpath("chevron_down.svg").as_posix()
_CHEVRON_UP_ICON = _ASSET_DIR.joinpath("chevron_up.svg").as_posix()


def _set_button_class(button: QPushButton, class_name: str):
    button.setProperty("class", class_name)
    styles = {
        "PrimaryAction": (
            "#0a84ff",
            "#ffffff",
            "#0a84ff",
            "#2f9bff",
        ),
        "DangerAction": (
            "#d92d20",
            "#ffffff",
            "#d92d20",
            "#ff453a",
        ),
        "DisabledAction": (
            "rgba(100, 112, 130, 50)",
            "#9ba6b5",
            "rgba(148, 163, 184, 80)",
            "rgba(100, 112, 130, 50)",
        ),
    }
    bg, fg, border, hover = styles.get(
        class_name,
        ("#172033", "#eef3fb", "rgba(100, 116, 139, 150)", "#243044"),
    )
    button.setMinimumHeight(42)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"""
        QPushButton {{
            background: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 9px 10px;
            font-size: 13px;
            font-weight: 800;
        }}
        QPushButton:hover {{
            background: {hover};
        }}
        QPushButton:disabled {{
            background: rgba(100, 112, 130, 45);
            color: #8f98a6;
            border-color: rgba(100, 116, 139, 70);
        }}
        """
    )
    button.style().unpolish(button)
    button.style().polish(button)


def _label(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    color = "#9ba6b5" if muted else "#eef3fb"
    label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;")
    return label


def _card() -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(
        """
        QFrame {
            background: rgba(255, 255, 255, 18);
            border: 1px solid rgba(255, 255, 255, 42);
            border-radius: 12px;
        }
        """
    )
    return frame


def _qcolor_rgb(color: QColor) -> tuple[int, int, int]:
    return color.red(), color.green(), color.blue()


INSPECTION_INPUT_STYLE = """
QLineEdit, QComboBox, QDoubleSpinBox, QListWidget {
    background: #111927;
    color: #f1f6ff;
    border: 1px solid #506a8a;
    border-radius: 8px;
    padding: 7px 9px;
    min-height: 30px;
    selection-background-color: #1677d8;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #6fa8ff;
    background: #142033;
}
QComboBox {
    padding-right: 42px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 38px;
    border-left: 1px solid #506a8a;
    background: #23344d;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}
QComboBox::down-arrow {
    image: url("{_CHEVRON_DOWN_ICON}");
    width: 16px;
    height: 16px;
}
QComboBox::drop-down:hover {
    background: #2d4361;
}
QComboBox QAbstractItemView {
    background: #0e1624;
    color: #f1f6ff;
    border: 1px solid #6481a6;
    selection-background-color: #1677d8;
    selection-color: #ffffff;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 7px 10px;
    color: #f1f6ff;
    background: #0e1624;
}
QComboBox QAbstractItemView::item:selected {
    background: #1677d8;
    color: #ffffff;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 38px;
    background: #23344d;
    border-left: 1px solid #506a8a;
}
QDoubleSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 8px;
}
QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 8px;
}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #2d4361;
}
QDoubleSpinBox::up-arrow {
    image: url("{_CHEVRON_UP_ICON}");
    width: 13px;
    height: 13px;
}
QDoubleSpinBox::down-arrow {
    image: url("{_CHEVRON_DOWN_ICON}");
    width: 13px;
    height: 13px;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #6b84a6;
    background: #111927;
}
QCheckBox::indicator:checked {
    background: #1677d8;
    border: 1px solid #75b7ff;
}
QListWidget::item {
    padding: 5px 4px;
    color: #f1f6ff;
    border: none;
}
QListWidget::item:selected {
    background: rgba(111, 168, 255, 42);
    color: #ffffff;
}
""".replace("{_CHEVRON_DOWN_ICON}", _CHEVRON_DOWN_ICON).replace("{_CHEVRON_UP_ICON}", _CHEVRON_UP_ICON)


class _BaseDockPanel(QWidget):
    def __init__(self, control_panel, store, parent=None):
        super().__init__(parent)
        self.control_panel = control_panel
        self.store = store
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QWidget { background: transparent; }
            QPushButton {
                background: #172033;
                color: #eef3fb;
                border: 1px solid rgba(100, 116, 139, 150);
                border-radius: 8px;
                padding: 9px 10px;
                font-size: 13px;
                font-weight: 800;
                min-height: 24px;
            }
            QPushButton:hover { background: #243044; }
            QLineEdit {
                min-height: 30px;
            }
            """
        )

    def _sync_map_name_to_control_panel(self, text: str):
        if hasattr(self.control_panel, "set_map_name"):
            self.control_panel.set_map_name(text)
        elif hasattr(self.control_panel, "input_map_name"):
            self.control_panel.input_map_name.setText(text)

    def _bind_common_refresh(self):
        for signal_name in (
            "mapping_state_changed",
            "navigation_state_changed",
            "navigation_busy_changed",
            "chassis_service_changed",
            "mqtt_service_changed",
            "chassis_alive_changed",
            "map_data_changed",
            "mqtt_connection_changed",
        ):
            signal = getattr(self.store, signal_name, None)
            if signal is not None:
                signal.connect(lambda *args: self.refresh())

    def refresh(self):
        pass


class MappingDockPanel(_BaseDockPanel):
    def __init__(self, control_panel, store, parent=None):
        super().__init__(control_panel, store, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)

        status_card = _card()
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(8)
        self.status_mode = _label("建图状态：待命")
        self.status_map = _label("实时地图：等待 /map")
        self.status_scan = _label("雷达点云：等待 /scan")
        self.status_hint = _label("完成探索后停止建图，再保存地图。", muted=True)
        status_layout.addWidget(self.status_mode, 0, 0)
        status_layout.addWidget(self.status_map, 0, 1)
        status_layout.addWidget(self.status_scan, 1, 0)
        status_layout.addWidget(self.status_hint, 1, 1)
        layout.addWidget(status_card)

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_row.addWidget(_label("地图名", muted=True))
        self.input_map_name = QLineEdit(self.control_panel.get_map_name())
        self.input_map_name.textChanged.connect(self._sync_map_name_to_control_panel)
        name_row.addWidget(self.input_map_name, 1)
        layout.addLayout(name_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.btn_toggle_mapping = QPushButton("启动建图")
        self.btn_toggle_mapping.clicked.connect(self.control_panel._on_mapping_clicked)
        self.btn_save_map = QPushButton("停止并保存")
        self.btn_save_map.clicked.connect(self.control_panel.sig_save_map.emit)
        _set_button_class(self.btn_toggle_mapping, "PrimaryAction")
        _set_button_class(self.btn_save_map, "DisabledAction")
        action_row.addWidget(self.btn_toggle_mapping)
        action_row.addWidget(self.btn_save_map)
        layout.addLayout(action_row)

        layout.addStretch()

        self._bind_common_refresh()
        self.refresh()

    def refresh(self):
        mapping_enabled, reason = self.control_panel._mapping_available()
        if self.store.mapping_running:
            self.btn_toggle_mapping.setText("停止建图")
            self.btn_toggle_mapping.setEnabled(True)
            _set_button_class(self.btn_toggle_mapping, "DangerAction")
            self.btn_save_map.setEnabled(True)
            self.status_mode.setText("建图状态：运行中")
            self.status_hint.setText("地图正在从机器人端 /map 实时回传。")
        else:
            self.btn_toggle_mapping.setText("启动建图")
            self.btn_toggle_mapping.setEnabled(mapping_enabled)
            self.btn_toggle_mapping.setToolTip("" if mapping_enabled else reason)
            _set_button_class(self.btn_toggle_mapping, "PrimaryAction" if mapping_enabled else "DisabledAction")
            self.btn_save_map.setEnabled(False)
            self.status_mode.setText("建图状态：待命")
            self.status_hint.setText(reason or "启动 SLAM 后，Mac 端只显示机器人端实时地图。")

        _set_button_class(self.btn_save_map, "PrimaryAction" if self.btn_save_map.isEnabled() else "DisabledAction")
        self.status_map.setText("实时地图：已加载" if self.store.map_available else "实时地图：等待 /map")
        scan = getattr(self.store, "_state", {}).get("laser_scan")
        self.status_scan.setText("雷达点云：已接收" if scan else "雷达点云：等待 /scan")


class NavigationDockPanel(_BaseDockPanel):
    def __init__(self, control_panel, store, parent=None):
        super().__init__(control_panel, store, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)

        status_card = _card()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        self.status_label = _label("导航状态：待命")
        self.hint_label = _label("启动 Navigation2 后，可在地图上设置初始位姿和目标点。", muted=True)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.hint_label)
        layout.addWidget(status_card)

        main_row = QHBoxLayout()
        main_row.setSpacing(10)
        self.btn_toggle_navigation = QPushButton("启动导航")
        self.btn_toggle_navigation.clicked.connect(self.control_panel._on_navigation_clicked)
        self.btn_initial_pose = QPushButton("设置初始位姿")
        self.btn_initial_pose.clicked.connect(self.control_panel.sig_set_initial_pose.emit)
        self.btn_goal_pose = QPushButton("发送目标点")
        self.btn_goal_pose.clicked.connect(self.control_panel.sig_set_goal_pose.emit)
        _set_button_class(self.btn_toggle_navigation, "PrimaryAction")
        _set_button_class(self.btn_initial_pose, "DisabledAction")
        _set_button_class(self.btn_goal_pose, "DisabledAction")
        main_row.addWidget(self.btn_toggle_navigation)
        main_row.addWidget(self.btn_initial_pose)
        main_row.addWidget(self.btn_goal_pose)
        layout.addLayout(main_row)

        manual_row = QHBoxLayout()
        manual_row.setSpacing(10)
        self.btn_manual_initial = QPushButton("手动初位")
        self.btn_manual_initial.clicked.connect(self.control_panel._on_manual_initial)
        self.btn_manual_goal = QPushButton("手动目标")
        self.btn_manual_goal.clicked.connect(self.control_panel._on_manual_goal)
        self.btn_save_pose = QPushButton("保存初位")
        self.btn_save_pose.clicked.connect(self.control_panel.sig_save_initial_pose.emit)
        self.btn_recall_pose = QPushButton("恢复初位")
        self.btn_recall_pose.clicked.connect(self.control_panel.sig_recall_initial_pose.emit)
        for button in (self.btn_manual_initial, self.btn_manual_goal, self.btn_save_pose, self.btn_recall_pose):
            _set_button_class(button, "DisabledAction")
            manual_row.addWidget(button)
        layout.addLayout(manual_row)
        layout.addStretch()

        self._bind_common_refresh()
        self.refresh()

    def refresh(self):
        nav_enabled, reason = self.control_panel._navigation_available()
        if self.store.navigation_busy:
            text = "启动中..." if self.store.navigation_busy_reason == "starting" else "停止中..."
            self.btn_toggle_navigation.setText(text)
            self.btn_toggle_navigation.setEnabled(False)
            _set_button_class(self.btn_toggle_navigation, "DisabledAction")
            self.status_label.setText("导航状态：处理中")
            self.hint_label.setText("请等待当前 Navigation2 操作完成。")
        elif self.store.navigation_running:
            self.btn_toggle_navigation.setText("停止导航")
            self.btn_toggle_navigation.setEnabled(True)
            _set_button_class(self.btn_toggle_navigation, "DangerAction")
            self.status_label.setText("导航状态：运行中")
            self.hint_label.setText("可以设置初始位姿、发送目标点或停止导航。")
        else:
            self.btn_toggle_navigation.setText("启动导航")
            self.btn_toggle_navigation.setEnabled(nav_enabled)
            self.btn_toggle_navigation.setToolTip("" if nav_enabled else reason)
            _set_button_class(self.btn_toggle_navigation, "PrimaryAction" if nav_enabled else "DisabledAction")
            self.status_label.setText("导航状态：待命")
            self.hint_label.setText(reason or "系统已就绪，可启动 Navigation2。")

        nav_controls_enabled = self.store.navigation_running and not self.store.navigation_busy
        for button in (
            self.btn_initial_pose,
            self.btn_goal_pose,
            self.btn_manual_initial,
            self.btn_manual_goal,
            self.btn_save_pose,
            self.btn_recall_pose,
        ):
            button.setEnabled(nav_controls_enabled)
            button.setToolTip("" if nav_controls_enabled else "需先启动导航")
            _set_button_class(button, "PrimaryAction" if nav_controls_enabled else "DisabledAction")


class InspectionDockPanel(QWidget):
    add_map_point_requested = Signal()
    add_current_pose_requested = Signal()

    MODE_ITEMS = [
        ("Nav2 自动", "nav2"),
        ("人工遥控", "manual"),
        ("低速直控", "direct"),
        ("录制路线", "recorded"),
    ]

    def __init__(self, plan_manager, patrol_controller, parent=None):
        super().__init__(parent)
        self.manager = plan_manager
        self.patrol = patrol_controller
        self._active_waypoint_id = None
        self.setStyleSheet(
            """
            QWidget { background: transparent; color: #eef3fb; }
            QCheckBox { color: #eef3fb; font-weight: 700; }
            """
            + INSPECTION_INPUT_STYLE
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(12)

        plan_row = QHBoxLayout()
        plan_row.setSpacing(8)
        self.combo_plan = QComboBox()
        self.combo_plan.currentIndexChanged.connect(self._on_plan_selected)
        self._force_combo_popup_contrast(self.combo_plan)
        plan_row.addWidget(self.combo_plan, 1)
        self.btn_new_plan = QPushButton("新建")
        self.btn_duplicate_plan = QPushButton("复制")
        self.btn_delete_plan = QPushButton("删除")
        for button in (self.btn_new_plan, self.btn_duplicate_plan, self.btn_delete_plan):
            _set_button_class(button, "PrimaryAction" if button != self.btn_delete_plan else "DangerAction")
            plan_row.addWidget(button)
        layout.addLayout(plan_row)

        self.btn_new_plan.clicked.connect(self._create_plan)
        self.btn_duplicate_plan.clicked.connect(self.manager.duplicate_current_plan)
        self.btn_delete_plan.clicked.connect(self.manager.delete_current_plan)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        self.input_name = QLineEdit()
        self.input_desc = QLineEdit()
        self.combo_mode = QComboBox()
        for label, value in self.MODE_ITEMS:
            self.combo_mode.addItem(label, value)
        self._force_combo_popup_contrast(self.combo_mode)
        self.check_loop = QCheckBox("循环")
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.10, 3.00)
        self.spin_threshold.setSingleStep(0.05)
        self.spin_threshold.setSuffix(" m")
        self.spin_dwell = QDoubleSpinBox()
        self.spin_dwell.setRange(0.0, 60.0)
        self.spin_dwell.setSingleStep(0.5)
        self.spin_dwell.setSuffix(" s")

        form.addWidget(_label("名称", muted=True), 0, 0)
        form.addWidget(self.input_name, 0, 1)
        form.addWidget(_label("场景", muted=True), 1, 0)
        form.addWidget(self.input_desc, 1, 1)
        form.addWidget(_label("方式", muted=True), 2, 0)
        form.addWidget(self.combo_mode, 2, 1)
        form.addWidget(self.check_loop, 3, 1)
        form.addWidget(_label("到点阈值", muted=True), 4, 0)
        form.addWidget(self.spin_threshold, 4, 1)
        form.addWidget(_label("停留", muted=True), 5, 0)
        form.addWidget(self.spin_dwell, 5, 1)
        layout.addLayout(form)

        self.input_name.editingFinished.connect(self._apply_plan_fields)
        self.input_desc.editingFinished.connect(self._apply_plan_fields)
        self.combo_mode.currentIndexChanged.connect(self._apply_plan_fields)
        self.check_loop.toggled.connect(self._apply_plan_fields)
        self.spin_threshold.valueChanged.connect(self._apply_plan_fields)
        self.spin_dwell.valueChanged.connect(self._apply_plan_fields)

        point_row = QGridLayout()
        point_row.setHorizontalSpacing(8)
        point_row.setVerticalSpacing(8)
        self.btn_add_map_point = QPushButton("地图点选添加")
        self.btn_add_current_pose = QPushButton("当前位置加入")
        self.btn_rename_point = QPushButton("重命名点位")
        self.btn_toggle_point = QPushButton("启用/禁用")
        self.btn_delete_point = QPushButton("删除点位")
        self.btn_move_up = QPushButton("上移")
        self.btn_move_down = QPushButton("下移")
        for button in (
            self.btn_add_map_point,
            self.btn_add_current_pose,
            self.btn_rename_point,
            self.btn_toggle_point,
            self.btn_delete_point,
            self.btn_move_up,
            self.btn_move_down,
        ):
            _set_button_class(button, "PrimaryAction")
        point_row.addWidget(self.btn_add_map_point, 0, 0)
        point_row.addWidget(self.btn_add_current_pose, 0, 1)
        point_row.addWidget(self.btn_rename_point, 1, 0)
        point_row.addWidget(self.btn_toggle_point, 1, 1)
        point_row.addWidget(self.btn_move_up, 2, 0)
        point_row.addWidget(self.btn_move_down, 2, 1)
        point_row.addWidget(self.btn_delete_point, 3, 0, 1, 2)
        layout.addLayout(point_row)

        self.btn_add_map_point.clicked.connect(self.add_map_point_requested.emit)
        self.btn_add_current_pose.clicked.connect(self.add_current_pose_requested.emit)
        self.btn_rename_point.clicked.connect(self._rename_selected_point)
        self.btn_toggle_point.clicked.connect(self._toggle_selected_point)
        self.btn_delete_point.clicked.connect(self._delete_selected_point)
        self.btn_move_up.clicked.connect(lambda: self._move_selected_point(-1))
        self.btn_move_down.clicked.connect(lambda: self._move_selected_point(1))

        self.list_points = QListWidget()
        self.list_points.setMinimumHeight(160)
        self.list_points.setStyleSheet(INSPECTION_INPUT_STYLE)
        layout.addWidget(self.list_points, 1)

        run_grid = QGridLayout()
        run_grid.setHorizontalSpacing(8)
        run_grid.setVerticalSpacing(8)
        self.btn_start = QPushButton("开始巡检")
        self.btn_pause = QPushButton("暂停")
        self.btn_next = QPushButton("到达 / 下一点")
        self.btn_stop = QPushButton("停止")
        self.btn_record_start = QPushButton("开始录制路线")
        self.btn_record_stop = QPushButton("停止录制并保存")
        for button in (
            self.btn_start,
            self.btn_pause,
            self.btn_next,
            self.btn_stop,
            self.btn_record_start,
            self.btn_record_stop,
        ):
            _set_button_class(button, "PrimaryAction" if button != self.btn_stop else "DangerAction")
        run_grid.addWidget(self.btn_start, 0, 0)
        run_grid.addWidget(self.btn_pause, 0, 1)
        run_grid.addWidget(self.btn_next, 1, 0)
        run_grid.addWidget(self.btn_stop, 1, 1)
        run_grid.addWidget(self.btn_record_start, 2, 0)
        run_grid.addWidget(self.btn_record_stop, 2, 1)
        layout.addLayout(run_grid)

        self.status_label = _label("巡检待命", muted=True)
        layout.addWidget(self.status_label)

        self.btn_start.clicked.connect(self.patrol.start)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_next.clicked.connect(self.patrol.mark_arrived)
        self.btn_stop.clicked.connect(self.patrol.stop)
        self.btn_record_start.clicked.connect(self.patrol.start_route_recording)
        self.btn_record_stop.clicked.connect(self.patrol.stop_route_recording)

        self.manager.plans_changed.connect(lambda _plans: self.refresh_plans())
        self.manager.current_plan_changed.connect(lambda _plan: self.refresh_current_plan())
        self.patrol.running_changed.connect(self._on_running_changed)
        self.patrol.active_waypoint_changed.connect(self._on_active_waypoint)
        self.patrol.status_changed.connect(self._on_patrol_status)
        self.patrol.route_recording_changed.connect(self._on_recording_changed)
        self.refresh_plans()
        self.refresh_current_plan()
        self._on_running_changed(False, "")
        self._on_recording_changed(False)

    @staticmethod
    def _force_combo_popup_contrast(combo: QComboBox):
        popup_style = """
        QListView {
            background: #0e1624;
            color: #f1f6ff;
            border: 1px solid #6481a6;
            selection-background-color: #1677d8;
            selection-color: #ffffff;
            outline: 0;
        }
        QListView::item {
            min-height: 30px;
            padding: 7px 10px;
            color: #f1f6ff;
            background: #0e1624;
        }
        QListView::item:selected {
            background: #1677d8;
            color: #ffffff;
        }
        """
        combo.setStyleSheet(INSPECTION_INPUT_STYLE)
        if combo.view() is not None:
            combo.view().setStyleSheet(popup_style)

    def refresh_plans(self):
        current = self.manager.current_plan()
        current_id = current.get("id") if current else None
        self.combo_plan.blockSignals(True)
        self.combo_plan.clear()
        for plan in self.manager.plans():
            self.combo_plan.addItem(plan.get("name", "未命名方案"), plan.get("id"))
        if current_id:
            idx = self.combo_plan.findData(current_id)
            if idx >= 0:
                self.combo_plan.setCurrentIndex(idx)
        self.combo_plan.blockSignals(False)
        self.refresh_current_plan()

    def _point_item_widget(self, point: dict, order: int, active: bool) -> QWidget:
        enabled = bool(point.get("enabled", True))
        color = QColor(inspection_point_color(order))
        accent = QColor(color if enabled else QColor(120, 132, 150))
        r, g, b = _qcolor_rgb(accent)
        bg_alpha = 62 if active else 34
        border_alpha = 190 if active else 105

        row = QFrame()
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setStyleSheet(
            f"""
            QFrame {{
                background: rgba({r}, {g}, {b}, {bg_alpha});
                border: 1px solid rgba({r}, {g}, {b}, {border_alpha});
                border-left: 6px solid {accent.name()};
                border-radius: 7px;
            }}
            """
        )

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(10)

        badge = QLabel(f"P{order}")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(38, 26)
        badge.setStyleSheet(
            f"""
            QLabel {{
                background: {accent.name()};
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 165);
                border-radius: 13px;
                font-size: 12px;
                font-weight: 900;
            }}
            """
        )
        row_layout.addWidget(badge)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        name = str(point.get("name") or f"P{order}")
        active_suffix = "  进行中" if active else ""
        title = QLabel(f"{order}. {name}{active_suffix}")
        title.setStyleSheet("color: #f7fbff; font-size: 13px; font-weight: 900; border: none; background: transparent;")
        coords = QLabel(f"X {float(point.get('x', 0.0)):.2f}   Y {float(point.get('y', 0.0)):.2f}")
        coords.setStyleSheet("color: #d7e3f4; font-size: 12px; font-weight: 750; border: none; background: transparent;")
        text_col.addWidget(title)
        text_col.addWidget(coords)
        row_layout.addLayout(text_col, 1)

        return row

    def refresh_current_plan(self):
        plan = self.manager.current_plan()
        if not plan:
            return
        for widget in (
            self.input_name,
            self.input_desc,
            self.combo_mode,
            self.check_loop,
            self.spin_threshold,
            self.spin_dwell,
        ):
            widget.blockSignals(True)
        self.input_name.setText(plan.get("name", "未命名方案"))
        self.input_desc.setText(plan.get("description", ""))
        idx = self.combo_mode.findData(plan.get("mode", "nav2"))
        self.combo_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.check_loop.setChecked(bool(plan.get("loop", True)))
        self.spin_threshold.setValue(float(plan.get("arrival_threshold", 0.35)))
        self.spin_dwell.setValue(float(plan.get("dwell_seconds", 1.0)))
        for widget in (
            self.input_name,
            self.input_desc,
            self.combo_mode,
            self.check_loop,
            self.spin_threshold,
            self.spin_dwell,
        ):
            widget.blockSignals(False)

        selected_id = self._selected_point_id()
        self.list_points.clear()
        waypoints = sorted(plan.get("waypoints", []), key=lambda p: int(p.get("order", 0) or 0))
        for index, point in enumerate(waypoints, start=1):
            order = int(point.get("order") or index)
            active = point.get("id") == self._active_waypoint_id
            item = QListWidgetItem()
            item.setData(Qt.UserRole, point.get("id"))
            row = self._point_item_widget(point, order, active)
            item.setSizeHint(row.sizeHint())
            self.list_points.addItem(item)
            self.list_points.setItemWidget(item, row)
            if selected_id and selected_id == point.get("id"):
                self.list_points.setCurrentItem(item)

    def _on_plan_selected(self, *_args):
        plan_id = self.combo_plan.currentData()
        if plan_id:
            current = self.manager.current_plan() or {}
            if current.get("id") != plan_id and self.patrol.running:
                self.patrol.stop("巡检方案已切换，巡检停止")
            self.manager.set_current_plan(plan_id)

    def _create_plan(self, *_args):
        name, ok = QInputDialog.getText(self, "新建巡检方案", "方案名称：")
        if ok:
            self.manager.create_plan(name.strip() or "新巡检方案")

    def _apply_plan_fields(self, *_args):
        mode = self.combo_mode.currentData() or "nav2"
        current = self.manager.current_plan() or {}
        if current.get("mode") != mode and self.patrol.running:
            self.patrol.stop("巡检方式已切换，巡检停止")
        self.manager.update_current_plan(
            name=self.input_name.text().strip() or "未命名方案",
            description=self.input_desc.text().strip(),
            mode=mode,
            loop=self.check_loop.isChecked(),
            arrival_threshold=self.spin_threshold.value(),
            dwell_seconds=self.spin_dwell.value(),
        )

    def _selected_point_id(self):
        item = self.list_points.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _rename_selected_point(self):
        point_id = self._selected_point_id()
        if not point_id:
            return
        point = self.manager._find_waypoint(point_id)
        current_name = point.get("name", "") if point else ""
        name, ok = QInputDialog.getText(self, "重命名点位", "点位名称：", text=current_name)
        if ok:
            self.manager.update_waypoint(point_id, name=name.strip() or current_name or "巡检点")

    def _toggle_selected_point(self):
        point_id = self._selected_point_id()
        point = self.manager._find_waypoint(point_id) if point_id else None
        if point:
            self.manager.update_waypoint(point_id, enabled=not point.get("enabled", True))

    def _delete_selected_point(self):
        point_id = self._selected_point_id()
        if point_id:
            self.manager.remove_waypoint(point_id)

    def _move_selected_point(self, delta: int):
        row = self.list_points.currentRow()
        point_id = self._selected_point_id()
        if point_id is None or row < 0:
            return
        self.manager.move_waypoint(point_id, row + delta)
        self.list_points.setCurrentRow(max(0, min(self.list_points.count() - 1, row + delta)))

    def _toggle_pause(self, *_args):
        if self.patrol.paused:
            self.patrol.resume()
        else:
            self.patrol.pause()

    def _on_running_changed(self, running: bool, _mode: str):
        self.btn_start.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_next.setEnabled(running)
        self.btn_stop.setEnabled(running)
        self.btn_pause.setText("继续" if self.patrol.paused else "暂停")

    def _on_active_waypoint(self, point):
        self._active_waypoint_id = point.get("id") if point else None
        self.refresh_current_plan()

    def _on_patrol_status(self, message: str, tone: str):
        self.status_label.setText(message)

    def _on_recording_changed(self, recording: bool):
        self.btn_record_start.setEnabled(not recording)
        self.btn_record_stop.setEnabled(recording)
        self.status_label.setText("正在录制巡检路线" if recording else "路线录制已停止")


class MapFilesDockPanel(_BaseDockPanel):
    def __init__(self, control_panel, store, parent=None):
        super().__init__(control_panel, store, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)

        layout.addWidget(_label("地图文件只负责上传、下载和命名，不参与建图计算。", muted=True))
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_row.addWidget(_label("地图名", muted=True))
        self.input_map_name = QLineEdit(self.control_panel.get_map_name())
        self.input_map_name.textChanged.connect(self._sync_map_name_to_control_panel)
        name_row.addWidget(self.input_map_name, 1)
        layout.addLayout(name_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.btn_download_map = QPushButton("下载地图")
        self.btn_download_map.clicked.connect(self.control_panel.sig_download_map.emit)
        self.btn_upload_map = QPushButton("上传地图")
        self.btn_upload_map.clicked.connect(self.control_panel.sig_upload_map.emit)
        _set_button_class(self.btn_download_map, "PrimaryAction")
        _set_button_class(self.btn_upload_map, "PrimaryAction")
        action_row.addWidget(self.btn_download_map)
        action_row.addWidget(self.btn_upload_map)
        layout.addLayout(action_row)
        layout.addStretch()


class LayersDockPanel(QWidget):
    def __init__(self, map_view, map_tools, parent=None):
        super().__init__(parent)
        self.map_view = map_view
        self.map_tools = map_tools
        self.settings = QSettings("RobotPanel", "LayerPreferences")
        self.setStyleSheet("QWidget { background: transparent; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)
        layout.addWidget(_label("地图图层只控制显示隐藏，不修改机器人端数据。", muted=True))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.btn_map = self._toggle("地图", self._saved_layer_state("map", True))
        self.btn_grid = self._toggle("网格", self._saved_layer_state("grid", True))
        self.btn_scan = self._toggle("红色点云", self._saved_layer_state("scan", True))
        self.btn_path = self._toggle("全局路径", self._saved_layer_state("path", True))
        grid.addWidget(self.btn_map, 0, 0)
        grid.addWidget(self.btn_grid, 0, 1)
        grid.addWidget(self.btn_scan, 1, 0)
        grid.addWidget(self.btn_path, 1, 1)
        layout.addLayout(grid)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.btn_fit = QPushButton("适配视图")
        self.btn_fit.clicked.connect(self.map_view.fit_to_content)
        self.btn_follow = QPushButton("跟随机器人")
        self.btn_follow.clicked.connect(self.map_tools.locate_requested.emit)
        _set_button_class(self.btn_fit, "PrimaryAction")
        _set_button_class(self.btn_follow, "PrimaryAction")
        action_row.addWidget(self.btn_fit)
        action_row.addWidget(self.btn_follow)
        layout.addLayout(action_row)
        layout.addStretch()

        self.map_view.map_layer.setVisible(self.btn_map.isChecked())
        self.map_view.grid_layer.setVisible(self.btn_grid.isChecked())
        self.map_view.path_layer.setVisible(self.btn_path.isChecked())
        self.map_view.set_scan_visible(self.btn_scan.isChecked())
        if self.map_tools.btn_layers.isChecked() != self.btn_scan.isChecked():
            self.map_tools.btn_layers.setChecked(self.btn_scan.isChecked())

        self.btn_map.toggled.connect(lambda checked: self._set_layer_visible("map", self.map_view.map_layer.setVisible, checked))
        self.btn_grid.toggled.connect(lambda checked: self._set_layer_visible("grid", self.map_view.grid_layer.setVisible, checked))
        self.btn_path.toggled.connect(lambda checked: self._set_layer_visible("path", self.map_view.path_layer.setVisible, checked))
        self.btn_scan.toggled.connect(self._on_scan_toggled)
        self.map_tools.btn_layers.toggled.connect(self._sync_scan_button)

    def _saved_layer_state(self, key: str, default: bool) -> bool:
        value = self.settings.value(f"layers/{key}", default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}

    def _remember_layer_state(self, key: str, checked: bool):
        self.settings.setValue(f"layers/{key}", bool(checked))
        self.settings.sync()

    def _set_layer_visible(self, key: str, setter, checked: bool):
        setter(bool(checked))
        self._remember_layer_state(key, checked)

    def _toggle(self, text: str, checked: bool) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setChecked(checked)
        _set_button_class(button, "PrimaryAction" if checked else "DisabledAction")
        button.toggled.connect(lambda is_checked, b=button: _set_button_class(b, "PrimaryAction" if is_checked else "DisabledAction"))
        return button

    def _on_scan_toggled(self, checked: bool):
        self._remember_layer_state("scan", checked)
        if self.map_tools.btn_layers.isChecked() != checked:
            self.map_tools.btn_layers.setChecked(checked)
        self.map_view.set_scan_visible(checked)

    def _sync_scan_button(self, checked: bool):
        if self.btn_scan.isChecked() != checked:
            self.btn_scan.setChecked(checked)
        else:
            self._remember_layer_state("scan", checked)


class DockSettingsPanel(SystemSetting):
    settings_saved = Signal(dict)

    def __init__(self, current_config, parent=None):
        super().__init__(current_config=current_config, parent=parent)
        self._tab_wheel_accumulator = 0
        self.setWindowFlags(Qt.Widget)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(0, 0)
        self.setStyleSheet("QDialog { background: transparent; border: none; }")
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.tabBar().installEventFilter(self)
        self.tabs.installEventFilter(self)
        self.tabs.setStyleSheet(
            """
            QTabBar::tab {
                min-width: 78px;
                padding: 8px 10px;
                font-size: 12px;
                font-weight: 800;
            }
            QTabWidget::pane {
                border: 1px solid rgba(100, 116, 139, 120);
            }
            """
        )

    def eventFilter(self, obj, event):
        if obj in (self.tabs, self.tabs.tabBar()) and event.type() == QEvent.Wheel:
            if self._handle_tab_wheel(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_tab_wheel(self, event) -> bool:
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        delta_x = pixel_delta.x() if not pixel_delta.isNull() else angle_delta.x()
        delta_y = pixel_delta.y() if not pixel_delta.isNull() else angle_delta.y()
        if abs(delta_x) < abs(delta_y) or abs(delta_x) < 8:
            return False

        self._tab_wheel_accumulator += delta_x
        if abs(self._tab_wheel_accumulator) < 60:
            event.accept()
            return True

        step = 1 if self._tab_wheel_accumulator < 0 else -1
        self._tab_wheel_accumulator = 0
        current = self.tabs.currentIndex()
        next_index = max(0, min(self.tabs.count() - 1, current + step))
        if next_index != current:
            self.tabs.setCurrentIndex(next_index)
        event.accept()
        return True

    def _on_save(self):
        try:
            config = self._collect_values()
            for section in ("paths",):
                if section in self._config:
                    config[section] = self._config[section]

            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            self._config = config
            logging.info("[系统设置] 配置已保存到 %s", self.CONFIG_PATH)
            self.settings_saved.emit(self.get_settings())
        except Exception as exc:
            logging.error("[系统设置] 保存配置失败: %s", exc)
            self.settings_saved.emit({"error": str(exc)})
