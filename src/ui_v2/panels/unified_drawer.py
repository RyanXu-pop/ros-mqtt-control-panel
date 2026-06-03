from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QScrollArea, QFrame
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Signal

class UnifiedDrawer(QWidget):
    """
    Apple Maps 风格的统一侧边抽屉。
    聚合了 Telemetry, Workflow, PoseRecorder 和 Teleop 所有的组件。
    支持整体的展开与折叠动画，避免过多零散组件遮挡地图。
    """
    height_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "PanelWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(340)
        
        self._is_expanded = True  # 默认展开，因为它是主控中心
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. 拖拽把手 Header
        self.header_btn = QPushButton("专业控制台   ▼")
        self.header_btn.setCursor(Qt.PointingHandCursor)
        self.header_btn.setStyleSheet("""
            QPushButton {
                background: #171a1f;
                border: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                color: #f2f4f8;
                font-weight: bold;
                letter-spacing: 1px;
                text-align: center;
                padding: 12px;
                border-bottom: 1px solid #2f343c;
            }
            QPushButton:hover {
                color: #ffffff;
                background: #20242b;
            }
        """)
        self.header_btn.clicked.connect(self.toggle_drawer)
        self.main_layout.addWidget(self.header_btn)
        
        # 2. 可滚动的核心内容区
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #15171b;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #4b5565;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(14, 12, 14, 16)
        self.content_layout.setSpacing(12)
        
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        # 动画对象 (控制整个 scroll_area 的高度)
        self.animation = QPropertyAnimation(self.scroll_area, b"maximumHeight")
        self.animation.setDuration(400)
        self.animation.setEasingCurve(QEasingCurve.InOutQuart)
        self.animation.valueChanged.connect(self._on_animation_step)

    def add_panel(self, panel_widget: QWidget):
        """将旧的 Panel 作为卡片加入到统一抽屉中"""
        # 移除原 Panel 的背景以融入抽屉
        panel_widget.setStyleSheet("background: transparent; border: none;")
        self.content_layout.addWidget(panel_widget)
        
        # 加一个细细的分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #2f343c; max-height: 1px;")
        self.content_layout.addWidget(line)

    def set_max_height(self, max_h: int):
        """主窗口调用，防止抽屉超出屏幕高度"""
        self._max_allowed_height = max_h
        if self._is_expanded:
            self.scroll_area.setMaximumHeight(max_h - self.header_btn.height())

    def toggle_drawer(self):
        self._is_expanded = not self._is_expanded
        
        target_height = self._max_allowed_height - self.header_btn.height() if self._is_expanded else 0
        current_height = self.scroll_area.maximumHeight()
        
        self.animation.setStartValue(current_height)
        self.animation.setEndValue(target_height)
        self.animation.start()
        
        # 箭头提示变化
        self.header_btn.setText("专业控制台   ▼" if self._is_expanded else "专业控制台   ▲")
        
    def _on_animation_step(self, value):
        self.adjustSize()
        self.height_changed.emit(self.height())
