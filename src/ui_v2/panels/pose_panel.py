import math
import os
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PoseRecordPanel(QWidget):
    """Pose recording panel."""

    height_changed = Signal(int)

    sig_start_trace = Signal()
    sig_stop_trace = Signal()
    sig_record_point = Signal()
    sig_go_to_selected = Signal(float, float, float)

    def __init__(self, parent=None, dock_mode: bool = False):
        super().__init__(parent)
        self.setProperty("class", "PanelWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._dock_mode = dock_mode
        if dock_mode:
            self.setMinimumWidth(300)
        else:
            self.setFixedWidth(300)
        self._latest_xlsx_path = ""

        self._is_expanded = False
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.header_btn = QPushButton("位姿记录   ▲")
        self.header_btn.setCursor(Qt.PointingHandCursor)
        self.header_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                color: #8f98a6;
                font-weight: bold;
                letter-spacing: 1px;
                text-align: left;
                padding: 15px;
            }
            QPushButton:hover {
                color: #ffffff;
                background: rgba(255, 255, 255, 0.05);
            }
            """
        )
        self.header_btn.clicked.connect(self.toggle_drawer)
        self.main_layout.addWidget(self.header_btn)

        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(15, 0, 15, 15)
        content_layout.setSpacing(10)

        trace_label = QLabel("轨迹连续记录")
        trace_label.setStyleSheet("color: #d4d4d4; font-size: 13px; margin-top: 5px;")
        content_layout.addWidget(trace_label)

        trace_action_layout = QHBoxLayout()
        self.btn_start_trace = QPushButton("开始记录")
        self.btn_start_trace.setProperty("class", "PrimaryAction")
        self.btn_start_trace.clicked.connect(self.sig_start_trace.emit)

        self.btn_stop_trace = QPushButton("停止并保存")
        self.btn_stop_trace.setProperty("class", "DangerAction")
        self.btn_stop_trace.setEnabled(False)
        self.btn_stop_trace.clicked.connect(self.sig_stop_trace.emit)

        trace_action_layout.addWidget(self.btn_start_trace)
        trace_action_layout.addWidget(self.btn_stop_trace)
        content_layout.addLayout(trace_action_layout)

        self.latest_file_label = QLabel("最近轨迹表：暂无")
        self.latest_file_label.setWordWrap(True)
        self.latest_file_label.setStyleSheet("color: #c5ccd8; font-size: 12px;")
        content_layout.addWidget(self.latest_file_label)

        file_action_layout = QHBoxLayout()
        self.btn_open_trace_file = QPushButton("打开表格")
        self.btn_open_trace_file.clicked.connect(self._open_latest_file)
        self.btn_open_trace_folder = QPushButton("打开文件夹")
        self.btn_open_trace_folder.clicked.connect(self._open_latest_folder)
        for button in (self.btn_open_trace_file, self.btn_open_trace_folder):
            button.setEnabled(False)
            file_action_layout.addWidget(button)
        content_layout.addLayout(file_action_layout)

        point_label = QLabel("单点位姿记录")
        point_label.setStyleSheet("color: #d4d4d4; font-size: 13px; margin-top: 10px;")
        content_layout.addWidget(point_label)

        self.btn_record_point = QPushButton("记录当前位姿")
        self.btn_record_point.clicked.connect(self.sig_record_point.emit)
        content_layout.addWidget(self.btn_record_point)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            """
            QListWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                padding: 2px;
            }
            QListWidget::item:selected {
                background-color: #007acc;
                color: white;
            }
            """
        )
        self.list_widget.setFixedHeight(120)
        content_layout.addWidget(self.list_widget)

        list_action_layout = QHBoxLayout()
        self.btn_go_to = QPushButton("前往选中点")
        self.btn_go_to.clicked.connect(self._on_go_to)

        self.btn_delete = QPushButton("删除选中")
        self.btn_delete.clicked.connect(self._on_delete)

        list_action_layout.addWidget(self.btn_go_to)
        list_action_layout.addWidget(self.btn_delete)
        content_layout.addLayout(list_action_layout)

        self.main_layout.addWidget(self.content_widget)

        self.animation = QPropertyAnimation(self.content_widget, b"maximumHeight")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.InOutQuart)
        self.animation.valueChanged.connect(self._on_animation_step)

        self.content_widget.setMaximumHeight(0)
        if self._dock_mode:
            self.header_btn.hide()
            self.content_widget.setMaximumHeight(16777215)
            self.content_widget.setVisible(True)

    def toggle_drawer(self):
        if self._dock_mode:
            return
        self._is_expanded = not self._is_expanded
        target_height = self.content_widget.sizeHint().height() if self._is_expanded else 0
        current_height = self.content_widget.maximumHeight()

        self.animation.setStartValue(current_height)
        self.animation.setEndValue(target_height)
        self.animation.start()

        self.header_btn.setText("位姿记录   ▼" if self._is_expanded else "位姿记录   ▲")

    def _on_animation_step(self, value):
        self.adjustSize()
        self.height_changed.emit(self.height())

    def _on_delete(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        for item in items:
            self.list_widget.takeItem(self.list_widget.row(item))

    def _on_go_to(self):
        items = self.list_widget.selectedItems()
        if not items:
            return

        text = items[0].text()
        try:
            parts = text.split(" ")
            x = float(parts[1].split(":")[1])
            y = float(parts[2].split(":")[1])
            yaw_deg = float(parts[3].split(":")[1].rstrip("°"))
            self.sig_go_to_selected.emit(x, y, math.radians(yaw_deg))
        except Exception:
            QMessageBox.warning(self, "解析失败", f"无法解析记录点: {text}")

    def set_trace_active(self, active: bool):
        self.btn_start_trace.setEnabled(not active)
        self.btn_stop_trace.setEnabled(active)

    def set_latest_file(self, xlsx_path: str):
        path = os.path.abspath(xlsx_path)
        self._latest_xlsx_path = path
        self.latest_file_label.setText(f"最近轨迹表：{os.path.basename(path)}")
        self.latest_file_label.setToolTip(path)
        exists = os.path.exists(path)
        self.btn_open_trace_file.setEnabled(exists)
        self.btn_open_trace_folder.setEnabled(bool(os.path.dirname(path)))

    def _open_latest_file(self):
        if self._latest_xlsx_path and os.path.exists(self._latest_xlsx_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._latest_xlsx_path))

    def _open_latest_folder(self):
        if self._latest_xlsx_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._latest_xlsx_path)))

    def add_point(self, x: float, y: float, yaw: float):
        t_str = time.strftime("%H:%M:%S")
        record_str = f"[{t_str}] X:{x:.2f} Y:{y:.2f} Yaw:{yaw:.2f}°"
        self.list_widget.addItem(record_str)
        self.list_widget.scrollToBottom()
