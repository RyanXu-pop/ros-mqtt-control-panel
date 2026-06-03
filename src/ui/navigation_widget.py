# src/ui/navigation_widget.py
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QLineEdit, QPushButton, QGridLayout
)
from PySide6.QtCore import Qt, Signal

class NavigationWidget(QFrame):
    """
    导航控制面板 (Navigation Widget)
    负责处理用户手动输入目标 X, Y, 角度，以及发送导航指令的界面交互。
    """
    
    # 抛出信号给上层主窗口
    signal_target_changed = Signal()  # 当输入框内容改变时
    signal_send_target = Signal()     # 当点击“发送目标”时
    signal_send_angle = Signal()      # 当点击“发送角度”时
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        title_nav = QLabel("导航控制")
        title_nav.setObjectName("cardTitle")
        layout.addWidget(title_nav)

        nav_grid = QGridLayout()
        nav_grid.setHorizontalSpacing(10)
        nav_grid.setVerticalSpacing(10)

        self.target_x_label = QLabel("目标 X")
        self.target_y_label = QLabel("目标 Y")
        angle_label = QLabel("朝向(度)")

        self.x_edit = QLineEdit("0")
        self.x_edit.setPlaceholderText("例如 1.25")
        self.y_edit = QLineEdit("0")
        self.y_edit.setPlaceholderText("例如 -0.40")
        self.angle_edit = QLineEdit("0")
        self.angle_edit.setPlaceholderText("例如 90")

        # 实时更新地图上的目标点：内部输入框变化时，自动抛出信号
        self.x_edit.textChanged.connect(self.signal_target_changed)
        self.y_edit.textChanged.connect(self.signal_target_changed)

        nav_grid.addWidget(self.target_x_label, 0, 0)
        nav_grid.addWidget(self.x_edit, 0, 1)
        nav_grid.addWidget(self.target_y_label, 1, 0)
        nav_grid.addWidget(self.y_edit, 1, 1)
        nav_grid.addWidget(angle_label, 2, 0)
        nav_grid.addWidget(self.angle_edit, 2, 1)

        layout.addLayout(nav_grid)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.buttonST = QPushButton("发送目标")
        self.buttonST.setObjectName("accentButton")
        self.buttonST.clicked.connect(self.signal_send_target)
        
        self.buttonSA = QPushButton("发送角度")
        self.buttonSA.clicked.connect(self.signal_send_angle)
        
        btn_row.addWidget(self.buttonST, 1)
        btn_row.addWidget(self.buttonSA, 1)
        layout.addLayout(btn_row)

    # ---------------- 外部访问接口 ----------------
    def get_x(self) -> str:
        return self.x_edit.text()

    def get_y(self) -> str:
        return self.y_edit.text()

    def get_angle(self) -> str:
        return self.angle_edit.text()

    def set_coords(self, x: float, y: float):
        self.x_edit.setText(f"{x:.2f}")
        self.y_edit.setText(f"{y:.2f}")

    def set_angle(self, angle: float):
        self.angle_edit.setText(f"{angle:.2f}")
