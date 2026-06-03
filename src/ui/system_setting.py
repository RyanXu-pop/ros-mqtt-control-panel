# system_setting.py
# -*- coding: utf-8 -*-
"""
系统设置对话框 — 图形化编辑 config.yaml 中所有配置项

分为 4 个 Tab 页：
  1. MQTT 连接：host / port / username / password
  2. MQTT 话题：控制端 ↔ 机器人桥接用到的所有 MQTT topic
  3. SSH 连接：host / port / username / password / mock_mode
  4. ROS 话题：机器人端 ROS2 话题名称映射
  5. 显示：主题与地图图层
"""

import os
import yaml
import logging
from typing import Dict, Any

from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QFormLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QSpinBox, QCheckBox, QDialogButtonBox, QGroupBox,
    QMessageBox, QScrollArea, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


# ------------------------------------------------------------------ #
# 配置定义：每个 Tab 的字段描述
# ------------------------------------------------------------------ #

_MQTT_CONN_FIELDS = [
    ("host",     "Broker 地址",  "str",  "127.0.0.1"),
    ("port",     "Broker 端口",  "int",  1883),
    ("username", "用户名 (可选)", "str",  ""),
    ("password", "密码 (可选)",   "str",  ""),
]

_MQTT_TOPIC_FIELDS = [
    ("goal",            "导航目标",       "robot/goal"),
    ("initial_pose",    "初始位姿",       "robot/initial_pose"),
    ("pose",            "AMCL 位姿",     "robot/pose"),
    ("status",          "状态心跳",       "robot/status"),
    ("voltage",         "电池电压",       "robot/voltage"),
    ("map",             "地图数据",       "robot/map"),
    ("scan",            "激光雷达",       "robot/scan"),
    ("odom",            "主里程计",       "robot/odom"),
    ("odom_raw",        "原始里程计",     "robot/odom_raw"),
    ("tf",              "TF 变换",        "robot/tf"),
    ("tf_static",       "静态 TF",        "robot/tf_static"),
    ("path",            "全局路径",       "robot/path"),
    ("cmd_vel",         "遥控指令",       "robot/cmd_vel"),
    ("mapping_status",  "建图状态",       "robot/mapping_status"),
]

_SSH_FIELDS = [
    ("host",      "SSH 地址",     "str",   "10.42.0.1"),
    ("port",      "SSH 端口",     "int",   22),
    ("username",  "用户名",       "str",   "pi"),
    ("password",  "密码",         "str",   "yahboom"),
]

_ROS_TOPIC_FIELDS = [
    ("amcl_pose",       "AMCL 位姿话题",         "/amcl_pose"),
    ("move_base_goal",  "导航目标话题",           "/goal_pose"),
    ("initial_pose",    "初始位姿话题",           "/initialpose"),
    ("power_voltage",   "电池电压话题",           "/battery"),
    ("global_plan",     "全局路径话题",           "/plan"),
    ("laser_scan",      "激光雷达话题",           "/scan"),
    ("cmd_vel",         "遥控指令话题",           "/cmd_vel"),
    ("odom",            "主里程计话题",           "/odom"),
    ("odom_raw",        "原始里程计话题",         "/odom_raw"),
    ("map",             "地图话题",               "/map"),
    ("tf",              "TF 话题",                 "/tf"),
    ("tf_static",       "静态 TF 话题",             "/tf_static"),
]


# ------------------------------------------------------------------ #
# SystemSetting 对话框
# ------------------------------------------------------------------ #

class SystemSetting(QDialog):
    """图形化系统设置 — 读取 / 编辑 / 保存 config.yaml"""

    CONFIG_PATH = os.path.join("config", "config.yaml")

    def __init__(self, current_config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统设置")
        self.setMinimumSize(520, 480)
        self.resize(580, 560)

        self._config = current_config  # 当前配置快照
        self._editors: Dict[str, QWidget] = {}  # key → 编辑控件

        self._init_ui()

    # ------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------ #

    def _init_ui(self):
        root_layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_mqtt_conn_tab(),   "MQTT 连接")
        self.tabs.addTab(self._build_mqtt_topics_tab(), "MQTT 话题")
        self.tabs.addTab(self._build_ssh_tab(),         "SSH 连接")
        self.tabs.addTab(self._build_ros_topics_tab(),  "ROS 话题")
        self.tabs.addTab(self._build_display_tab(),     "显示")
        root_layout.addWidget(self.tabs)

        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Save).setText("保存并关闭")
        btn_box.button(QDialogButtonBox.Cancel).setText("取消")
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        root_layout.addWidget(btn_box)

    # ---------- Tab 1: MQTT 连接 ---------- #

    def _build_mqtt_conn_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)
        mqtt_cfg = self._config.get("mqtt", {})

        for key, label, typ, default in _MQTT_CONN_FIELDS:
            val = mqtt_cfg.get(key, default)
            if typ == "int":
                editor = QSpinBox()
                editor.setRange(1, 65535)
                editor.setValue(int(val) if val else default)
            else:
                editor = QLineEdit(str(val) if val else "")
                if key == "password":
                    editor.setEchoMode(QLineEdit.Password)
            layout.addRow(label + ":", editor)
            self._editors[f"mqtt.{key}"] = editor

        return widget

    # ---------- Tab 2: MQTT 话题 ---------- #

    def _build_mqtt_topics_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(8)
        topics = self._config.get("mqtt", {}).get("topics", {})

        header = QLabel("控制端 ↔ 桥接脚本之间的 MQTT 话题名称")
        header.setStyleSheet("color: #888; font-size: 11px;")
        layout.addRow(header)

        for key, label, default in _MQTT_TOPIC_FIELDS:
            editor = QLineEdit(str(topics.get(key, default)))
            editor.setPlaceholderText(default)
            layout.addRow(f"{label} ({key}):", editor)
            self._editors[f"mqtt.topics.{key}"] = editor

        return self._wrap_scrollable(widget)

    # ---------- Tab 5: Display ---------- #

    def _build_display_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)
        params = self._config.get("params", {})

        theme_combo = QComboBox()
        theme_combo.addItem("跟随系统", "auto")
        theme_combo.addItem("深色", "dark")
        theme_combo.addItem("浅色", "light")
        current_theme = str(params.get("theme", "auto")).lower()
        theme_idx = max(0, theme_combo.findData(current_theme))
        theme_combo.setCurrentIndex(theme_idx)
        layout.addRow("界面主题:", theme_combo)
        self._editors["params.theme"] = theme_combo

        scan_overlay = QCheckBox("建图时显示红色雷达点云")
        scan_overlay.setChecked(bool(params.get("show_mapping_scan_overlay", True)))
        layout.addRow("地图图层:", scan_overlay)
        self._editors["params.show_mapping_scan_overlay"] = scan_overlay

        return widget

    # ---------- Tab 3: SSH 连接 ---------- #

    def _build_ssh_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)
        ssh_cfg = self._config.get("ssh", {})

        for key, label, typ, default in _SSH_FIELDS:
            val = ssh_cfg.get(key, default)
            if typ == "int":
                editor = QSpinBox()
                editor.setRange(1, 65535)
                editor.setValue(int(val) if val else default)
            elif typ == "bool":
                editor = QCheckBox()
                editor.setChecked(bool(val))
            else:
                editor = QLineEdit(str(val) if val else "")
                if key == "password":
                    editor.setEchoMode(QLineEdit.Password)
            layout.addRow(label + ":", editor)
            self._editors[f"ssh.{key}"] = editor

        # (由于模拟模式已移交给左侧的统一"启动仿真"按钮控制，此处去掉了相关提示)

        return widget

    # ---------- Tab 4: ROS 话题 ---------- #

    def _build_ros_topics_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(8)
        topics = self._config.get("topics", {})

        header = QLabel("机器人端 ROS2 话题名称 (与 mqtt_bridge_ros2.py 对应)")
        header.setStyleSheet("color: #888; font-size: 11px;")
        layout.addRow(header)

        for key, label, default in _ROS_TOPIC_FIELDS:
            editor = QLineEdit(str(topics.get(key, default)))
            editor.setPlaceholderText(default)
            layout.addRow(f"{label} ({key}):", editor)
            self._editors[f"topics.{key}"] = editor

        # ROS 消息类型 (只读展示)
        layout.addRow(QLabel(""))  # 分隔
        msg_header = QLabel("ROS 消息类型映射 (高级)")
        msg_header.setStyleSheet("color: #888; font-size: 11px;")
        layout.addRow(msg_header)
        msg_types = [
            ("amcl_pose_msg_type",        "AMCL 消息类型"),
            ("pose_stamped_msg_type",     "PoseStamped 消息类型"),
            ("power_voltage_msg_type",    "电压消息类型"),
        ]
        for key, label in msg_types:
            editor = QLineEdit(str(topics.get(key, "")))
            layout.addRow(f"{label}:", editor)
            self._editors[f"topics.{key}"] = editor

        return self._wrap_scrollable(widget)

    # ------------------------------------------------------------ #
    # 保存逻辑
    # ------------------------------------------------------------ #

    def _on_save(self):
        """收集所有编辑器的值，写回 config.yaml"""
        try:
            config = self._collect_values()
            # 保留未编辑的配置段
            for section in ("paths",):
                if section in self._config:
                    config[section] = self._config[section]

            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)

            logging.info(f"[系统设置] 配置已保存到 {self.CONFIG_PATH}")
            QMessageBox.information(self, "保存成功",
                                    "配置已保存。\n部分设置需要重启应用后生效。")
            self.accept()
        except Exception as e:
            logging.error(f"[系统设置] 保存配置失败: {e}")
            QMessageBox.critical(self, "保存失败", f"写入配置文件失败:\n{e}")

    def _collect_values(self) -> Dict[str, Any]:
        """从 UI 编辑器收集值，构建新的 config dict"""
        config: Dict[str, Any] = {}

        # MQTT 连接
        mqtt_section: Dict[str, Any] = {}
        for key, _, typ, default in _MQTT_CONN_FIELDS:
            editor = self._editors[f"mqtt.{key}"]
            if typ == "int":
                mqtt_section[key] = editor.value()
            else:
                val = editor.text().strip()
                mqtt_section[key] = val if val else None
        # MQTT 话题
        mqtt_topics: Dict[str, str] = {}
        for key, _, default in _MQTT_TOPIC_FIELDS:
            editor = self._editors[f"mqtt.topics.{key}"]
            mqtt_topics[key] = editor.text().strip() or default
        mqtt_section["topics"] = mqtt_topics
        config["mqtt"] = mqtt_section

        # SSH
        ssh_section: Dict[str, Any] = {}
        for key, _, typ, default in _SSH_FIELDS:
            editor = self._editors[f"ssh.{key}"]
            if typ == "int":
                ssh_section[key] = editor.value()
            elif typ == "bool":
                ssh_section[key] = editor.isChecked()
            else:
                val = editor.text().strip()
                ssh_section[key] = val if val else default
        config["ssh"] = ssh_section

        # ROS 话题
        topics_section: Dict[str, str] = {}
        for key, _, default in _ROS_TOPIC_FIELDS:
            editor = self._editors[f"topics.{key}"]
            topics_section[key] = editor.text().strip() or default
        # 消息类型
        for key in ("amcl_pose_msg_type", "pose_stamped_msg_type", "power_voltage_msg_type"):
            editor = self._editors.get(f"topics.{key}")
            if editor:
                topics_section[key] = editor.text().strip()
        config["topics"] = topics_section

        params_section = dict(self._config.get("params", {}))
        theme_editor = self._editors.get("params.theme")
        if isinstance(theme_editor, QComboBox):
            params_section["theme"] = theme_editor.currentData()
        scan_editor = self._editors.get("params.show_mapping_scan_overlay")
        if isinstance(scan_editor, QCheckBox):
            params_section["show_mapping_scan_overlay"] = scan_editor.isChecked()
        config["params"] = params_section

        return config

    # ------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------ #

    @staticmethod
    def _wrap_scrollable(inner_widget: QWidget) -> QScrollArea:
        """包装为可滚动区域（话题列表较长时支持滚动）"""
        scroll = QScrollArea()
        scroll.setWidget(inner_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        return scroll

    def get_settings(self) -> Dict[str, str]:
        """兼容旧接口：返回 MQTT host/port"""
        return {
            "ip": self._editors.get("mqtt.host", QLineEdit()).text(),
            "port": str(self._editors.get("mqtt.port", QSpinBox()).value()
                        if isinstance(self._editors.get("mqtt.port"), QSpinBox)
                        else "1883"),
            "theme": self._editors.get("params.theme", QComboBox()).currentData()
                     if isinstance(self._editors.get("params.theme"), QComboBox)
                     else "auto",
        }
