import math
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton
from PySide6.QtCore import Qt

class ManualPoseDialog(QDialog):
    """
    手动输入位姿的对话框。
    用于手动精确设定目标点或初始点坐标。
    """
    def __init__(self, mode="goal", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("输入导航目标" if mode == "goal" else "手动设定初始位姿")
        self.setFixedSize(300, 200)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QLabel { color: #d4d4d4; font-size: 13px; }
            QDoubleSpinBox {
                background-color: #2d2d30;
                color: #ffffff;
                border: 1px solid #3e3e42;
                padding: 5px;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0098ff; }
            QPushButton#cancelBtn {
                background-color: transparent;
                border: 1px solid #3e3e42;
                color: #d4d4d4;
            }
            QPushButton#cancelBtn:hover { background-color: #2d2d30; }
        """)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # X, Y, Yaw inputs
        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)

        # X
        row_x = QHBoxLayout()
        row_x.addWidget(QLabel("X (米):"))
        self.spin_x = QDoubleSpinBox()
        self.spin_x.setRange(-1000, 1000)
        self.spin_x.setSingleStep(0.1)
        self.spin_x.setDecimals(3)
        row_x.addWidget(self.spin_x)
        form_layout.addLayout(row_x)

        # Y
        row_y = QHBoxLayout()
        row_y.addWidget(QLabel("Y (米):"))
        self.spin_y = QDoubleSpinBox()
        self.spin_y.setRange(-1000, 1000)
        self.spin_y.setSingleStep(0.1)
        self.spin_y.setDecimals(3)
        row_y.addWidget(self.spin_y)
        form_layout.addLayout(row_y)

        # Yaw
        row_yaw = QHBoxLayout()
        row_yaw.addWidget(QLabel("Yaw (度):"))
        self.spin_yaw = QDoubleSpinBox()
        self.spin_yaw.setRange(-180, 180)
        self.spin_yaw.setSingleStep(5)
        self.spin_yaw.setDecimals(1)
        row_yaw.addWidget(self.spin_yaw)
        form_layout.addLayout(row_yaw)

        layout.addLayout(form_layout)
        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("cancelBtn")
        btn_cancel.clicked.connect(self.reject)
        
        btn_confirm = QPushButton("确定发送")
        btn_confirm.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_confirm)
        layout.addLayout(btn_layout)

    def get_values(self):
        """返回 (x, y, yaw_radians)"""
        x = self.spin_x.value()
        y = self.spin_y.value()
        # 将 UI 上的度数转换为程序逻辑需要的弧度
        yaw_rad = math.radians(self.spin_yaw.value())
        return x, y, yaw_rad
