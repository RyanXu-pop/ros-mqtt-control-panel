# src/ui/telemetry_widget.py
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QProgressBar, QFormLayout
)
from PySide6.QtCore import Qt, Slot

class TelemetryWidget(QFrame):
    """
    状态与遥测面板 (Telemetry Widget)
    负责解耦顶部电池状态、连接状态底盘信息，以及中间的精确实时遥测坐标。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame") # 复用全局 QSS 样式
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # --- 第一部分：顶部状态栏 (Battery, Connection, Status) ---
        title_status = QLabel("状态与电量")
        title_status.setObjectName("cardTitle")
        layout.addWidget(title_status)

        # 1. 电池行
        battery_row = QHBoxLayout()
        battery_row.setSpacing(10)
        
        self.label_voltage = QLabel("电压: -- V")
        self.label_voltage.setObjectName("batteryVoltage")
        self.label_voltage.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        battery_right = QVBoxLayout()
        battery_right.setSpacing(6)
        battery_top = QHBoxLayout()
        battery_top.setSpacing(8)
        self.label_battery_percent = QLabel("--%")
        self.label_battery_percent.setObjectName("batteryPercent")
        self.label_battery_icon = QLabel("🔋")
        self.label_battery_icon.setObjectName("batteryIcon")
        self.label_battery_icon.setFixedWidth(28)
        self.label_battery_icon.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        battery_top.addWidget(self.label_battery_percent, 1)
        battery_top.addWidget(self.label_battery_icon, 0)

        self.battery_progress_bar = QProgressBar()
        self.battery_progress_bar.setRange(0, 100)
        self.battery_progress_bar.setValue(0)
        self.battery_progress_bar.setTextVisible(False)
        self.battery_progress_bar.setFixedHeight(8)

        battery_right.addLayout(battery_top)
        battery_right.addWidget(self.battery_progress_bar)

        battery_row.addWidget(self.label_voltage, 1)
        battery_row.addLayout(battery_right, 1)
        layout.addLayout(battery_row)

        # 2. 连接状态行
        conn_row = QHBoxLayout()
        conn_row.setSpacing(8)
        self.connection_dot = QLabel("")
        self.connection_dot.setObjectName("connectionDot")
        self.connection_dot.setFixedSize(10, 10)
        self.connection_dot.setProperty("state", "disconnected")
        self.connection_text = QLabel("未连接")
        self.connection_text.setObjectName("connectionText")
        conn_row.addWidget(self.connection_dot, 0, Qt.AlignVCenter)
        conn_row.addWidget(self.connection_text, 1, Qt.AlignVCenter)
        layout.addLayout(conn_row)

        # 3. 各种纯文本提示状态
        self.label_chassis_status = QLabel("底盘: 未知")
        self.label_chassis_status.setObjectName("chassisStatus")
        layout.addWidget(self.label_chassis_status)

        self.status_label = QLabel("状态: 等待操作...")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # 增加分割区
        layout.addSpacing(10)

        # --- 第二部分：实时遥测坐标 (AMCL/Odom Pose) ---
        title_telemetry = QLabel("实时导航遥测")
        title_telemetry.setObjectName("cardTitle")
        layout.addWidget(title_telemetry)

        telemetry_form = QFormLayout()
        telemetry_form.setLabelAlignment(Qt.AlignLeft)
        telemetry_form.setFormAlignment(Qt.AlignTop)
        telemetry_form.setHorizontalSpacing(12)
        telemetry_form.setVerticalSpacing(8)

        self.label_rx = QLabel("0.00")
        self.label_ry = QLabel("0.00")
        self.label_rz = QLabel("0.00")
        self.label_rd = QLabel("0.00")
        for w in (self.label_rx, self.label_ry, self.label_rz, self.label_rd):
            w.setObjectName("telemetryValue")
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        telemetry_form.addRow(QLabel("X(m)"), self.label_rx)
        telemetry_form.addRow(QLabel("Y(m)"), self.label_ry)
        telemetry_form.addRow(QLabel("Z(m)"), self.label_rz)
        telemetry_form.addRow(QLabel("方向角(°)"), self.label_rd)
        layout.addLayout(telemetry_form)

    # ---------------- 外部更新接口 ---------------- 
    def set_connection_state(self, connected: bool, text: str = None):
        state_str = "connected" if connected else "disconnected"
        self.connection_dot.setProperty("state", state_str)
        self.connection_dot.style().unpolish(self.connection_dot)
        self.connection_dot.style().polish(self.connection_dot)
        self.connection_dot.update()
        if text:
            self.connection_text.setText(text)
        else:
            self.connection_text.setText("已连接" if connected else "未连接")

    def set_system_status(self, text: str):
        self.status_label.setText(text)

    def set_chassis_status(self, is_online: bool):
        if is_online:
            self.label_chassis_status.setText("底盘: 在线 (Ready)")
            self.label_chassis_status.setStyleSheet("color: #30D158; font-weight: bold;")
        else:
            self.label_chassis_status.setText("底盘: 离线 (Offline)")
            self.label_chassis_status.setStyleSheet("color: #FF453A; font-weight: bold;")

    def update_voltage(self, voltage_str: str, percent: float):
        self.label_voltage.setText(f"电压: {voltage_str} V")
        self.label_battery_percent.setText(f"{int(percent)}%")
        self.battery_progress_bar.setValue(int(percent))
        # 红色警告样式
        if percent < 20:
            self.label_voltage.setStyleSheet("color: #FF453A;")
            self.label_battery_percent.setStyleSheet("color: #FF453A;")
        else:
            self.label_voltage.setStyleSheet("")
            self.label_battery_percent.setStyleSheet("")

    def update_telemetry(self, x: float, y: float, angle: float, z: float = 0.0):
        self.label_rx.setText(f"{x:.2f}")
        self.label_ry.setText(f"{y:.2f}")
        self.label_rz.setText(f"{z:.2f}")
        self.label_rd.setText(f"{angle:.2f}")
