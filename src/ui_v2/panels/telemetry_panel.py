from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget


class TelemetryPanel(QWidget):
    """Floating telemetry dashboard."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store

        self.setProperty("class", "PanelWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.setup_ui()
        self.bind_store()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(9)

        title_label = QLabel("实时遥测")
        title_font = QFont("Segoe UI", 10, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #f2f4f8; letter-spacing: 1px;")
        layout.addWidget(title_label)

        status_layout = QHBoxLayout()
        self.indicator_circle = QLabel("●")
        self.indicator_circle.setStyleSheet("color: #f14c4c; font-size: 16px;")
        self.status_label = QLabel("MQTT 未连接")
        self.status_label.setStyleSheet("color: #d8dde6; font-size: 13px; font-weight: bold;")

        status_layout.addWidget(self.indicator_circle)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        volt_layout = QHBoxLayout()
        volt_icon = QLabel("电压")
        volt_icon.setStyleSheet("color: #8f98a6; font-size: 11px; font-weight: 700;")
        self.volt_label = QLabel("N/A")
        self.volt_label.setStyleSheet("color: #d8dde6; font-size: 13px;")

        volt_layout.addWidget(volt_icon)
        volt_layout.addWidget(self.volt_label)
        volt_layout.addStretch()
        layout.addLayout(volt_layout)

        self.battery_bar = QProgressBar()
        self.battery_bar.setRange(0, 100)
        self.battery_bar.setValue(0)
        self.battery_bar.setTextVisible(False)
        self.battery_bar.setFixedHeight(6)
        self.battery_bar.setStyleSheet(
            """
            QProgressBar { background: #1a1d22; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #3fb950; border-radius: 3px; }
            """
        )
        layout.addWidget(self.battery_bar)

        coord_layout = QHBoxLayout()
        coord_icon = QLabel("位姿")
        coord_icon.setStyleSheet("color: #8f98a6; font-size: 11px; font-weight: 700;")
        self.coord_label = QLabel("X: 0.00  Y: 0.00  θ: 0°")
        self.coord_label.setStyleSheet("color: #d8dde6; font-size: 12px; font-family: monospace;")

        coord_layout.addWidget(coord_icon)
        coord_layout.addWidget(self.coord_label)
        coord_layout.addStretch()
        layout.addLayout(coord_layout)

        self.setFixedWidth(300)

    def bind_store(self):
        self.store.chassis_alive_changed.connect(self._on_chassis_status)
        self.store.voltage_changed.connect(self._on_voltage_changed)
        self.store.robot_pose_changed.connect(self._on_pose_changed)

    def _on_chassis_status(self, is_alive: bool):
        if is_alive:
            self.indicator_circle.setStyleSheet("color: #3fb950; font-size: 16px;")
            self.status_label.setText("底盘在线")
        else:
            self.indicator_circle.setStyleSheet("color: #f14c4c; font-size: 16px;")
            self.status_label.setText("底盘离线")

    def _on_voltage_changed(self, voltage: float, percent: float):
        color = "#3fb950" if voltage >= 24.0 else ("#f14c4c" if voltage <= 20.0 else "#d29922")
        self.volt_label.setText(f"{voltage:.2f} V ({int(percent)}%)")
        self.volt_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.battery_bar.setValue(int(percent))
        self.battery_bar.setStyleSheet(
            f"""
            QProgressBar {{ background: #1a1d22; border: none; border-radius: 3px; }}
            QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}
            """
        )

    def _on_pose_changed(self, pose):
        z = getattr(pose, "z", 0.0)
        self.coord_label.setText(f"X:{pose.x:5.2f} Y:{pose.y:5.2f} Z:{z:5.2f} θ:{pose.angle:4.0f}°")
