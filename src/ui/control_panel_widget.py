# src/ui/control_panel_widget.py
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit, QGridLayout
)
from PySide6.QtCore import Qt, Signal

class ControlPanelWidget(QFrame):
    """
    系统控制中心面板 (Control Panel Widget)
    接管了原来散落在 views 里的所有大系统操纵按键：启动底盘、启动建图、记录轨迹等
    """
    
    # 定义大量的按钮被按下的信号，供外层 MainWindow 直接接管
    signal_start_chassis = Signal()
    signal_start_navigation = Signal()
    signal_start_mqtt = Signal()
    
    signal_start_mapping = Signal()
    signal_save_map = Signal()
    signal_download_map = Signal()
    signal_upload_map = Signal()
    
    signal_set_shared_origin = Signal(bool)
    signal_pan_zoom = Signal(bool)
    
    signal_start_record = Signal()
    signal_stop_record = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # ==================== Card: System Actions ====================
        title_sys = QLabel("系统操作")
        title_sys.setObjectName("cardTitle")
        layout.addWidget(title_sys)

        self.start_chassis_button = QPushButton("启动底盘 (Bringup)")
        self.start_chassis_button.setObjectName("togglePrimary")
        self.start_chassis_button.clicked.connect(self.signal_start_chassis)

        self.start_navigation_button = QPushButton("启动导航 (SSH)")
        self.start_navigation_button.setObjectName("togglePrimary")
        self.start_navigation_button.clicked.connect(self.signal_start_navigation)

        self.start_mqtt_button = QPushButton("启动 MQTT 节点")
        self.start_mqtt_button.setObjectName("togglePrimary")
        self.start_mqtt_button.clicked.connect(self.signal_start_mqtt)

        layout.addWidget(self.start_chassis_button)
        layout.addWidget(self.start_navigation_button)
        layout.addWidget(self.start_mqtt_button)
        
        layout.addSpacing(10)

        # ==================== Card: Gmapping 建图 ====================
        title_map = QLabel("🗺️ 远程建图")
        title_map.setObjectName("cardTitle")
        layout.addWidget(title_map)
        
        # 建图状态标签
        self.label_mapping_status = QLabel("建图状态: 未启动")
        self.label_mapping_status.setObjectName("mappingStatus")
        layout.addWidget(self.label_mapping_status)
        
        self.start_mapping_button = QPushButton("启动建图 (Gmapping)")
        self.start_mapping_button.setObjectName("togglePrimary")
        self.start_mapping_button.clicked.connect(self.signal_start_mapping)
        layout.addWidget(self.start_mapping_button)
        
        # 地图名称输入
        map_name_layout = QHBoxLayout()
        map_name_label = QLabel("地图名称:")
        self.input_map_name = QLineEdit()
        self.input_map_name.setPlaceholderText("my_map")
        self.input_map_name.setText("my_map")
        map_name_layout.addWidget(map_name_label)
        map_name_layout.addWidget(self.input_map_name, 1)
        layout.addLayout(map_name_layout)
        
        # 保存/下载/上传按钮
        map_btn_layout = QHBoxLayout()
        self.save_map_button = QPushButton("保存地图")
        self.save_map_button.clicked.connect(self.signal_save_map)
        self.save_map_button.setEnabled(False)  # 建图启动后才能保存
        
        self.download_map_button = QPushButton("下载到本地")
        self.download_map_button.clicked.connect(self.signal_download_map)
        self.download_map_button.setEnabled(False)
        
        map_btn_layout.addWidget(self.save_map_button)
        map_btn_layout.addWidget(self.download_map_button)
        layout.addLayout(map_btn_layout)
        
        self.upload_map_button = QPushButton("上传地图到机器人")
        self.upload_map_button.setToolTip("将本地保存的地图上传到机器人")
        self.upload_map_button.clicked.connect(self.signal_upload_map)
        layout.addWidget(self.upload_map_button)

        layout.addSpacing(10)

        # ==================== Card: Tools & Recording ====================
        title_tools = QLabel("工具与记录")
        title_tools.setObjectName("cardTitle")
        layout.addWidget(title_tools)

        try:
            from src.core.constants import PARAMS_CONFIG
            
            tool_row = QHBoxLayout()
            tool_row.setSpacing(10)
            
            if PARAMS_CONFIG.get("show_set_origin_button", True):
                self.button_set_shared_origin = QPushButton("设置共同原点")
                self.button_set_shared_origin.setCheckable(True)
                self.button_set_shared_origin.toggled.connect(self.signal_set_shared_origin)
                tool_row.addWidget(self.button_set_shared_origin, 1)
            else:
                self.button_set_shared_origin = None
                
            if PARAMS_CONFIG.get("show_pan_zoom_button", True):
                self.button_pan_zoom = QPushButton("平移缩放地图")
                self.button_pan_zoom.setCheckable(True)
                self.button_pan_zoom.toggled.connect(self.signal_pan_zoom)
                tool_row.addWidget(self.button_pan_zoom, 1)
            else:
                self.button_pan_zoom = None
                
            if self.button_set_shared_origin or self.button_pan_zoom:
                layout.addLayout(tool_row)
        except Exception:
            self.button_set_shared_origin = None
            self.button_pan_zoom = None

        record_btn_grid = QGridLayout()
        record_btn_grid.setHorizontalSpacing(10)
        record_btn_grid.setVerticalSpacing(10)
        self.button_record_position_xlsx_start = QPushButton("开始记录轨迹")
        self.button_record_position_xlsx_start.clicked.connect(self.signal_start_record)
        self.button_record_position_xlsx_stop = QPushButton("停止记录轨迹")
        self.button_record_position_xlsx_stop.clicked.connect(self.signal_stop_record)
        
        record_btn_grid.addWidget(self.button_record_position_xlsx_start, 0, 0)
        record_btn_grid.addWidget(self.button_record_position_xlsx_stop, 0, 1)
        layout.addLayout(record_btn_grid)
        
    # ---------------- 外部访问接口 ----------------
    def get_map_name(self) -> str:
        return self.input_map_name.text()
        
    def set_mapping_status(self, text: str):
        self.label_mapping_status.setText(text)
        
    def set_mapping_buttons_enabled(self, enabled: bool):
        self.save_map_button.setEnabled(enabled)
        self.download_map_button.setEnabled(enabled)
        
    def update_record_buttons(self, is_recording: bool):
        if is_recording:
            self.button_record_position_xlsx_start.setText("记录中...")
            self.button_record_position_xlsx_start.setEnabled(False)
            self.button_record_position_xlsx_start.setStyleSheet("background-color: #FF3B30; color: white;")
        else:
            self.button_record_position_xlsx_start.setText("开始记录位置")
            self.button_record_position_xlsx_start.setEnabled(True)
            self.button_record_position_xlsx_start.setStyleSheet("")
