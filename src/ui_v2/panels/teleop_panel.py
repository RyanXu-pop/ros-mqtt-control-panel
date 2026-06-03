from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Signal

class TeleopPanel(QWidget):
    """
    虚拟遥控面板 (Teleop Overlay)
    由于真实的操控是全局键盘监听，这里主要做一个优雅的按键提示可视化面板（类似游戏手柄提示）。
    新增了 Apple Maps 风格的丝滑抽屉展开/折叠功能。
    """
    
    # 当面板高度发生变化（动画过程中）向外发射信号，方便主窗体重定位 Y 坐标
    height_changed = Signal(int)
    emergency_stop_requested = Signal()
    
    def __init__(self, parent=None, dock_mode: bool = False):
        super().__init__(parent)
        self.setProperty("class", "PanelWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._dock_mode = dock_mode
        if dock_mode:
            self.setMinimumWidth(300)
        else:
            self.setFixedWidth(300)
        
        self._is_expanded = False # 默认折叠
        self.setup_ui()

    def setup_ui(self):
        # 主布局，去掉多余边距让顶部 Header 贴边
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. 点击栏 (Header)
        self.header_btn = QPushButton("遥控说明   ▲")
        self.header_btn.setCursor(Qt.PointingHandCursor)
        self.header_btn.setStyleSheet("""
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
        """)
        self.header_btn.clicked.connect(self.toggle_drawer)
        self.main_layout.addWidget(self.header_btn)
        
        # 2. 内容区包装 (用于动画裁剪高度)
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(15, 0, 15, 15)
        content_layout.setSpacing(8)
        
        desc = QLabel("键盘焦点在应用时可用:\n\n[W] 前进\n[S] 后退\n[A] 左转\n[D] 右转\n[Space] 急停\n\n提示: 在小车连接时生效。")
        desc.setStyleSheet("color: #d4d4d4; font-size: 13px; line-height: 1.5;")
        desc.setWordWrap(True)
        content_layout.addWidget(desc)

        self.btn_emergency_stop = QPushButton("立即急停")
        self.btn_emergency_stop.setCursor(Qt.PointingHandCursor)
        self.btn_emergency_stop.clicked.connect(self.emergency_stop_requested.emit)
        self.btn_emergency_stop.setStyleSheet(
            """
            QPushButton {
                background: #d92d20;
                color: #ffffff;
                border: 1px solid #ff453a;
                border-radius: 8px;
                padding: 10px 12px;
                font-size: 13px;
                font-weight: 800;
            }
            QPushButton:hover {
                background: #ff453a;
            }
            """
        )
        content_layout.addWidget(self.btn_emergency_stop)
        
        self.main_layout.addWidget(self.content_widget)
        
        # 动画对象
        self.animation = QPropertyAnimation(self.content_widget, b"maximumHeight")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.InOutQuart)
        
        # 绑定动画运行时不断发射高度信号，通知 parent 更新 Y 坐标使其"向上"展开
        self.animation.valueChanged.connect(self._on_animation_step)
        
        # 初始化为折叠状态
        self.content_widget.setMaximumHeight(0)
        if self._dock_mode:
            self.header_btn.hide()
            self.content_widget.setMaximumHeight(16777215)
            self.content_widget.setVisible(True)

    def toggle_drawer(self):
        if self._dock_mode:
            return
        self._is_expanded = not self._is_expanded
        
        # 强制测量完整展开所需的高度
        target_height = self.content_widget.sizeHint().height() if self._is_expanded else 0
        current_height = self.content_widget.maximumHeight()
        
        self.animation.setStartValue(current_height)
        self.animation.setEndValue(target_height)
        self.animation.start()
        
        # 箭头提示变化
        self.header_btn.setText("遥控说明   ▼" if self._is_expanded else "遥控说明   ▲")
        
    def _on_animation_step(self, value):
        # 随着 maximumHeight 的改变，整个 Panel 的物理尺寸也会跟着变
        # Qt 布局系统会自动 shrink
        self.adjustSize()
        self.height_changed.emit(self.height())
