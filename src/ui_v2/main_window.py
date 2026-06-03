import os
import sys
import logging
import asyncio
import math
import socket
import time
from typing import Optional
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox
from PySide6.QtCore import Qt, Slot, QTimer

# 核心与网络
from src.core.constants import PATHS_CONFIG, PARAMS_CONFIG, CONFIG
from src.core.models import RobotPose
from src.core.utils import apply_pose_transform
from src.network.mqtt_agent import MqttAgent
from src.network.async_ssh_manager import AsyncSSHManager
from src.controllers.map_manager import MapManager
from src.controllers.workflow_controller import WorkflowController
from src.controllers.navigation_controller import NavigationController
from src.controllers.inspection_plan_manager import InspectionPlanManager
from src.controllers.patrol_controller import PatrolController
from src.controllers.teleop_controller import TeleopController
from src.controllers.pose_recorder import PoseRecorder
from src.ui.system_setting import SystemSetting

# V2 引入
from .theme import apply_theme
from .robot_state_hub import RobotStateHub
from .main_layout import MainLayoutWidget

class MyMainWindow(QMainWindow):
    """
    UI V2 主窗口
    采用单向数据流 (MVVM)：
      MqttAgent -> Store -> Panels/MapView
    PC 端只负责远程控制与显示。建图算法运行在机器人端，界面只渲染
    机器人端发布的 /map，并将当前帧 /scan 作为动态覆盖层显示。
    """
    def __init__(self, mqtt_agent=None):
        super().__init__()
        # 全局应用暗色主题
        from PySide6.QtWidgets import QApplication
        apply_theme(QApplication.instance(), PARAMS_CONFIG.get("theme", "auto"))
        
        self.setWindowTitle("ROS2 Control Panel V2")
        self.setMinimumSize(1024, 768)

        # 1. 核心状态池 (Single Source of Truth)
        self.store = RobotStateHub(self)
        
        # 2. 网络设施初始化
        self.async_ssh = AsyncSSHManager()
        self.mqtt_agent = mqtt_agent if mqtt_agent is not None else MqttAgent()
        
        # 3. 控制器初始化
        self.map_mgr = MapManager(map_bounds=PARAMS_CONFIG['map_bounds'])
        self.workflow_ctrl = WorkflowController(self.async_ssh, self.map_mgr, self)
        self.nav_ctrl = NavigationController(mqtt_agent=self.mqtt_agent)
        self.teleop_ctrl = TeleopController(mqtt_agent=self.mqtt_agent, parent=self)
        record_xlsx_path = PATHS_CONFIG.get('record_xlsx', 'pose_records.xlsx')
        self.pose_recorder = PoseRecorder(record_xlsx_path, parent=self)
        inspection_path = PATHS_CONFIG.get("inspection_plans_json", os.path.join("data", "inspection_plans.json"))
        self.inspection_manager = InspectionPlanManager(inspection_path, parent=self)
        self.patrol_ctrl = PatrolController(self.inspection_manager, self.store, parent=self)
        self._inspection_enabled = False
        self._active_nav_goal = None
        self._path_suppressed_until_new_goal = False
        self._nav_arrival_threshold_m = float(PARAMS_CONFIG.get("navigation_arrival_threshold", 0.35))
        self._map_to_odom = None
        self._frame_transforms = {}
        self._mapping_pose_log_counter = 0
        self._mapping_scan_default_visible = bool(PARAMS_CONFIG.get("show_mapping_scan_overlay", True))
        self._show_mapping_scan_overlay = self._mapping_scan_default_visible
        self._map_source = "local"
        self._live_map_received = False
        self._cleared_for_live_map = False
        self._last_live_map_received_at: Optional[float] = None
        self._last_scan_received_at: Optional[float] = None
        self._last_robot_message_at: Optional[float] = None
        self._mqtt_service_started_at: Optional[float] = None
        self._robot_link_timeout_s = 4.0
        self._robot_offline_notified = False
        self._mapping_map_log_counter = 0
        self._mapping_scan_log_counter = 0
        self._last_mapping_scan_status = ""
        self._scan_transform_log_counter = 0
        self._last_scan_transform_signature = ""
        
        # 4. 界面构建
        self.ui = MainLayoutWidget(self.store, self.inspection_manager, self.patrol_ctrl, self)
        self.setCentralWidget(self.ui)
        self._show_mapping_scan_overlay = self.ui.map_tools.btn_layers.isChecked()
        self.ui.map_view.set_scan_visible(self._show_mapping_scan_overlay)
        
        # 5. 信号绑定 (数据总线)
        self._bind_signals()
        self._setup_connection_watchdogs()
        
        # 6. 加载地初始数据
        self._load_initial_data()
        
        # 7. 启动 MQTT
        try:
            self.mqtt_agent.connect_broker()
            logging.info("[V2] MqttAgent started.")
        except Exception as e:
            logging.error(f"[V2] MqttAgent connect failed: {e}")



    def _bind_signals(self):
        """核心数据流组装"""
        # --- UI Top Bar Actions ---
        self.ui.btn_simulation.clicked.connect(self._toggle_simulation)
        self.ui.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        self.ui.btn_settings.clicked.connect(lambda: self.ui.toggle_dock_panel("settings"))
        self.ui.top_status.mqtt_toggle_requested.connect(self._do_start_mqtt_node)
        self.ui.top_status.chassis_toggle_requested.connect(self._do_start_chassis)
        if hasattr(self.ui, "settings_panel"):
            self.ui.settings_panel.settings_saved.connect(self._on_dock_settings_saved)
        self.ui.btn_locate_me.clicked.connect(self._center_map_on_robot)
        self.ui.map_tools.locate_requested.connect(self._center_map_on_robot)
        self.ui.map_tools.scan_visibility_changed.connect(self._on_scan_layer_toggled)
        if getattr(self.ui, "inspection_panel", None) is not None:
            self.ui.inspection_panel.add_map_point_requested.connect(self._start_add_inspection_point)
            self.ui.inspection_panel.add_current_pose_requested.connect(self._add_current_pose_to_inspection)
        
        # ================== MQTT Data -> Store ==================
        self.mqtt_agent.pose_updated.connect(self._on_pose_data)
        self.mqtt_agent.voltage_updated.connect(self.store.update_voltage)
        if hasattr(self.mqtt_agent, "status_updated"):
            self.mqtt_agent.status_updated.connect(self._on_robot_status_data)
        self.mqtt_agent.chassis_status_updated.connect(self.store.update_chassis_status)
        if hasattr(self.mqtt_agent, "latency_updated"):
            self.mqtt_agent.latency_updated.connect(self.store.update_latency)
        self.mqtt_agent.scan_updated.connect(self._on_scan_data)
        self.mqtt_agent.path_updated.connect(self._on_path_data)
        self.mqtt_agent.map_updated.connect(self._on_live_map_data)
        if hasattr(self.mqtt_agent, 'transform_updated'):
            self.mqtt_agent.transform_updated.connect(self._on_tf_data)
        
        # MQTT 连接状态 → Store + TelemetryPanel
        self.mqtt_agent.connection_status.connect(self._on_mqtt_connection_status)
        
        # Odom 数据 → 建图模式下更新位姿
        # 这里只更新显示用的机器人位姿，不在 PC 端做任何 map 级二次修正。
        if hasattr(self.mqtt_agent, 'odom_updated'):
            self.mqtt_agent.odom_updated.connect(self._on_odom_data)

        # ================== Store -> MapView ==================
        self.store.map_data_changed.connect(self.ui.map_view.update_map)
        self.store.global_path_changed.connect(self._on_store_path_changed)
        
        self.store.robot_pose_changed.connect(self._on_store_robot_pose_changed)
        if self._inspection_enabled:
            self.store.robot_pose_changed.connect(self.patrol_ctrl.on_robot_pose)
        
        def safely_update_scan(scan_dict):
            self._on_store_scan_changed(scan_dict)
        self.store.laser_scan_changed.connect(safely_update_scan)
        self.store.mapping_state_changed.connect(self._on_mapping_state_changed)

        # ================== Pose Recorder / Navigation ==================
        self.ui.pose_panel.sig_start_trace.connect(self.pose_recorder.start)
        self.ui.pose_panel.sig_start_trace.connect(lambda: self.ui.pose_panel.set_trace_active(True))
        
        def on_stop_trace():
            if self.pose_recorder.recording and not self.pose_recorder.has_records:
                pose = getattr(self.store, "current_pose", None)
                if pose is not None:
                    self.pose_recorder.append(pose.x, pose.y, 0.0, pose.angle)
            ok = self.pose_recorder.stop()
            self.ui.pose_panel.set_trace_active(False)
            if ok:
                self.ui.pose_panel.set_latest_file(self.pose_recorder.last_saved_path)
                self._show_toast("轨迹表已生成，可在记录面板打开", "success")
                self._record_console_event("轨迹表已生成")
        self.ui.pose_panel.sig_stop_trace.connect(on_stop_trace)
        
        def on_record_point():
            pose = getattr(self.store, "current_pose", None)
            if pose:
                self.ui.pose_panel.add_point(pose.x, pose.y, pose.angle)
                logging.info(f"[PoseRecord] 手动打卡位置: {pose.x}, {pose.y}, {pose.angle}")
        self.ui.pose_panel.sig_record_point.connect(on_record_point)
        
        import numpy as np
        self.ui.pose_panel.sig_go_to_selected.connect(
            lambda x, y, yaw: self._send_navigation_goal(x, y, yaw, source="trace")
        )
        self.pose_recorder.status_message.connect(lambda msg: logging.info(f"[PoseRecorder] {msg}"))
        self.ui.teleop_panel.emergency_stop_requested.connect(self.teleop_ctrl.emergency_stop)
        self.ui.teleop_panel.emergency_stop_requested.connect(lambda: self._show_toast("已发送急停零速", "info"))
        
        # ================== UI Intents -> Controllers ==================
        # 接收并显示系统级全局通知
        def show_popup(msg):
            tone = "error" if "失败" in msg or "异常" in msg else "info"
            self._set_workflow_feedback(msg, busy=self._message_is_busy(msg), tone=tone)
            self.statusBar().showMessage(msg, 3000)
                
        self.store.workflow_message.connect(show_popup)
        self.store.workflow_message.connect(self._record_console_event)
        
        # 建图开关
        self.ui.control_panel.sig_start_mapping.connect(self._do_start_mapping)
        self.ui.control_panel.sig_stop_mapping.connect(self._do_stop_mapping)
        self.ui.control_panel.sig_save_map.connect(self._do_save_map)
        
        # 导航开关
        self.ui.control_panel.sig_start_navigation.connect(self._do_start_nav)
        self.ui.control_panel.sig_stop_navigation.connect(self._do_stop_nav)
        
        # 交互设定
        self.ui.control_panel.sig_set_initial_pose.connect(lambda: self.ui.map_view.set_interaction_mode("initial_pose"))
        self.ui.control_panel.sig_set_goal_pose.connect(lambda: self.ui.map_view.set_interaction_mode("goal"))
        
        # 处理手动坐标输入
        import numpy as np
        identity_inv = np.eye(3)
        self.ui.control_panel.sig_manual_initial_pose.connect(
            lambda x, y, yaw: self.nav_ctrl.set_initial_pose(x, y, yaw, identity_inv)
        )
        self.ui.control_panel.sig_manual_goal.connect(
            lambda x, y, yaw: self._send_navigation_goal(x, y, yaw, source="manual")
        )
        # 地图回传意图处理器
        self.ui.map_view.interaction_triggered.connect(self._on_map_interaction)
        if self._inspection_enabled:
            self.inspection_manager.current_plan_changed.connect(lambda _plan: self._refresh_inspection_layer())
            self.inspection_manager.plans_changed.connect(lambda _plans: self._refresh_inspection_layer())
            self.patrol_ctrl.active_waypoint_changed.connect(self._on_patrol_active_waypoint)
            self.patrol_ctrl.command_velocity_requested.connect(self._publish_patrol_cmd_vel)
            self.patrol_ctrl.goal_requested.connect(self._send_patrol_goal)
            self.patrol_ctrl.ensure_navigation_requested.connect(self._ensure_patrol_navigation)
            self.patrol_ctrl.status_changed.connect(lambda msg, tone: self._show_toast(msg, tone if tone in {"success", "error", "warning", "info"} else "info"))

        # 工作流消息
        self.workflow_ctrl.status_message.connect(self._on_workflow_status_message)
        self.workflow_ctrl.map_synced.connect(self._load_initial_data)
        self.workflow_ctrl.workflow_finished.connect(self._on_workflow_finished)
        
        # SSH 系统操作
        self.ui.control_panel.sig_start_chassis.connect(self._do_start_chassis)
        self.ui.control_panel.sig_start_mqtt_node.connect(self._do_start_mqtt_node)
        
        # 地图下载/上传
        self.ui.control_panel.sig_download_map.connect(self._do_download_map)
        self.ui.control_panel.sig_upload_map.connect(self._do_upload_map)
        
        # 初始位姿保存/恢复
        self.ui.control_panel.sig_save_initial_pose.connect(self._do_save_initial_pose)
        self.ui.control_panel.sig_recall_initial_pose.connect(self._do_recall_initial_pose)
        self._refresh_inspection_layer()

    def _load_initial_data(self):
        """首次加载静态地图"""
        if self.store.mapping_running:
            return
        ok = self.map_mgr.load(PATHS_CONFIG['map_yaml'])
        if ok and self.map_mgr.map_data:
            from src.core.models import MapMetadata
            
            map_data = self.map_mgr.map_data
            map_raster = map_data.get('data', map_data['image'])
            
            meta = MapMetadata(
                resolution=map_data.get('resolution', 0.05),
                origin_x=map_data.get('origin', [0, 0, 0])[0],
                origin_y=map_data.get('origin', [0, 0, 0])[1],
                origin_yaw=map_data.get('origin', [0, 0, 0])[2],
                width=map_raster.shape[1],
                height=map_raster.shape[0],
                data=map_raster,
                encoding=map_data.get('encoding', 'image')
            )
            self._apply_local_map(meta)

    def _record_console_event(self, message: str):
        panel = getattr(getattr(self, "ui", None), "control_panel", None)
        if panel and hasattr(panel, "add_event"):
            panel.add_event(message)

    def _show_toast(self, message: str, tone: str = "info", timeout_ms: int = 2800):
        if hasattr(self.ui, "show_toast"):
            self.ui.show_toast(message, tone=tone, timeout_ms=timeout_ms)
        self.statusBar().showMessage(message, timeout_ms)

    def _setup_connection_watchdogs(self):
        self._robot_link_timer = QTimer(self)
        self._robot_link_timer.setInterval(1000)
        self._robot_link_timer.timeout.connect(self._check_robot_link_watchdog)
        self._robot_link_timer.start()

        self._broker_timer = QTimer(self)
        self._broker_timer.setInterval(2000)
        self._broker_timer.timeout.connect(self._check_broker_watchdog)
        self._broker_timer.start()

    def _note_robot_link(self, source: str = ""):
        self._last_robot_message_at = time.monotonic()
        if not self.store.mqtt_broker_connected:
            self.store.set_mqtt_broker_connected(True, "收到机器人端 MQTT 数据")
        if not self.store.mqtt_running:
            self.store.set_mqtt_running(True)
        if not getattr(self.store, "robot_link_alive", False):
            self.store.set_robot_link_alive(True, "机器人端 MQTT 桥接在线")
            if self._robot_offline_notified:
                self._show_toast("小车已重新在线", "success", 2600)
        self._robot_offline_notified = False

    def _is_broker_reachable(self) -> bool:
        host = str(getattr(self.mqtt_agent, "host", "") or "")
        port = int(getattr(self.mqtt_agent, "port", 1883) or 1883)
        if not host:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.35):
                return True
        except OSError:
            return False

    def _check_broker_watchdog(self):
        reachable = self._is_broker_reachable()
        agent_connected = bool(getattr(self.mqtt_agent, "is_connected", False))
        connected = reachable and agent_connected
        if connected:
            if not self.store.mqtt_broker_connected:
                self.store.set_mqtt_broker_connected(True, "MQTT Broker 已连接")
            return

        if self.store.mqtt_broker_connected:
            self.store.set_mqtt_broker_connected(False, "MQTT Broker 离线")
            self._show_toast("MQTT Broker 已离线", "error", 3600)
        if not reachable:
            self._mark_robot_offline("Broker 无法连接")

    def _check_robot_link_watchdog(self):
        if not self.store.mqtt_running and not getattr(self.store, "robot_link_alive", False):
            return
        reference_time = self._last_robot_message_at or self._mqtt_service_started_at
        if reference_time is None:
            return
        if time.monotonic() - reference_time <= self._robot_link_timeout_s:
            return
        self._mark_robot_offline("机器人端 MQTT 桥接心跳超时")

    def _mark_robot_offline(self, reason: str):
        self.store.set_robot_link_alive(False, reason)
        self.store.update_chassis_status(False)
        self.store.set_mqtt_broker_connected(False, "小车离线")
        if self.store.mapping_running:
            self.store.set_mapping_running(False)
        if self.store.navigation_running:
            self.store.set_navigation_running(False)
        if not self._robot_offline_notified:
            self._robot_offline_notified = True
            self._show_toast(f"小车离线：{reason}", "error", 4800)
            self._set_workflow_feedback(f"小车离线：{reason}", busy=False, tone="error")

    @staticmethod
    def _message_is_busy(message: str) -> bool:
        text = str(message or "")
        busy_words = ("正在", "开始", "下发", "上传", "下载", "保存", "启动", "停止", "生成")
        final_words = ("完成", "成功", "失败", "异常", "已关闭", "已启动", "准备就绪")
        return any(word in text for word in busy_words) and not any(word in text for word in final_words)

    def _set_workflow_feedback(self, message: str, busy: bool = False, tone: str = "info"):
        panel = getattr(getattr(self, "ui", None), "control_panel", None)
        if panel and hasattr(panel, "set_workflow_feedback"):
            panel.set_workflow_feedback(message, busy=busy, tone=tone)
        else:
            self._record_console_event(message)

    def _on_workflow_status_message(self, msg: str):
        self.statusBar().showMessage(msg, 5000)
        self._set_workflow_feedback(msg, busy=self._message_is_busy(msg), tone="info")

    @staticmethod
    def _format_map_stats(map_meta) -> str:
        try:
            import numpy as np

            data = np.asarray(getattr(map_meta, "data", []), dtype=np.uint8)
            free = int(((data >= 0) & (data <= 25)).sum())
            occupied = int(((data >= 65) & (data <= 100)).sum())
            unknown = int((data == 255).sum())
        except Exception:
            free = occupied = unknown = -1
        return (
            f"{getattr(map_meta, 'width', 0)}x{getattr(map_meta, 'height', 0)} "
            f"res={float(getattr(map_meta, 'resolution', 0.0)):.3f} "
            f"origin=({float(getattr(map_meta, 'origin_x', 0.0)):.2f},"
            f"{float(getattr(map_meta, 'origin_y', 0.0)):.2f},"
            f"{float(getattr(map_meta, 'origin_yaw', 0.0)):.2f}) "
            f"free={free} occupied={occupied} unknown={unknown}"
        )

    # ---------------- 业务编排 ----------------
    
    def _apply_local_map(self, map_meta):
        self._map_source = "local"
        self._live_map_received = False
        self._cleared_for_live_map = False
        self._last_live_map_received_at = None
        self.store.update_map(map_meta)
        logging.info("[V2][MappingMap] source=LOCAL cleared_for_live_map=%s", self._cleared_for_live_map)

    def _on_live_map_data(self, map_meta):
        self._note_robot_link("map")
        self._last_live_map_received_at = time.monotonic()
        if not (self.store.mapping_running or self._map_source == "live_mqtt" or self._cleared_for_live_map):
            return

        first_live_frame = not self._live_map_received or self._map_source != "live_mqtt"
        self._map_source = "live_mqtt"
        self._live_map_received = True
        self.store.update_map(map_meta)

        should_log = first_live_frame
        if self.store.mapping_running:
            self._mapping_map_log_counter += 1
        if should_log:
            logging.info(
                "[V2][MappingMap] source=LIVE cleared_for_live_map=%s %s",
                self._cleared_for_live_map,
                self._format_map_stats(map_meta),
            )
        self._cleared_for_live_map = False

    def _on_scan_data(self, scan_dict):
        self._note_robot_link("scan")
        self._last_scan_received_at = time.monotonic()
        self.store.update_scan(scan_dict or {})

    def _on_path_data(self, path_points):
        self._note_robot_link("path")
        if getattr(self, "_path_suppressed_until_new_goal", False):
            self.store.update_path([])
            return
        self.store.update_path(path_points or [])

    @Slot()
    def _do_start_mapping(self):
        if not self.store.chassis_running:
            QMessageBox.warning(self, "依赖提示", "请先开启「启动底盘」，否则无法获取雷达和里程计数据！")
            return
        if not self.store.mqtt_running:
            QMessageBox.warning(self, "依赖提示", "请先启动「MQTT 节点」，否则建图画面无法实时回传。")
            return
        asyncio.create_task(self.workflow_ctrl.execute_mapping_workflow())
        
    @Slot()
    def _do_stop_mapping(self):
        asyncio.create_task(self.workflow_ctrl.execute_stop_mapping_workflow())

    @Slot()
    def _do_save_map(self):
        import asyncio
        map_name = self.ui.control_panel.get_map_name().strip() or "my_map"
        asyncio.create_task(self.workflow_ctrl.execute_save_and_stop_mapping_workflow(map_name))
        self._set_workflow_feedback("正在保存地图，成功后自动停止建图...", busy=True, tone="info")

    @Slot()
    def _do_start_nav(self):
        import asyncio
        if not self.store.chassis_running:
            QMessageBox.warning(self, "依赖提示", "请先开启「启动底盘」，否则无法进行导航定位！")
            return
        self.store.set_navigation_busy(True, "starting")
        map_name = self.ui.control_panel.get_map_name().strip()
        asyncio.create_task(self.workflow_ctrl.execute_navigation_workflow(map_name))

    @Slot()
    def _do_stop_nav(self):
        import asyncio
        self.store.set_navigation_busy(True, "stopping")
        asyncio.create_task(self.workflow_ctrl.execute_stop_navigation_workflow())



    @Slot(float, float, float, str)
    def _on_map_interaction(self, x: float, y: float, yaw: float, mode: str):
        import numpy as np
        # V2 地图直接工作在物理世界坐标系，所以逆变换矩阵为单位阵
        identity_inv = np.eye(3)
        if mode == 'initial_pose':
            self.nav_ctrl.set_initial_pose(x, y, yaw, identity_inv)
            logging.info(f"[_on_map_interaction] Sent initial pose: {x}, {y}, {yaw}")
        elif mode == 'goal':
            self._send_navigation_goal(x, y, yaw, source="map")
            logging.info(f"[_on_map_interaction] Sent Nav goal: {x}, {y}, {yaw}")
        elif mode == 'inspection_point' and self._inspection_enabled:
            point = self.inspection_manager.add_waypoint(x, y, yaw)
            self._refresh_inspection_layer()
            self._show_toast(f"已添加巡检点：{point.get('name', '巡检点')}", "success")

    def _send_navigation_goal(self, x: float, y: float, yaw: float, source: str = "map") -> bool:
        import numpy as np

        sent = self.nav_ctrl.set_goal_pose(x, y, yaw, np.eye(3))
        if sent:
            self._active_nav_goal = {"x": float(x), "y": float(y), "yaw": float(yaw), "source": source}
            self._path_suppressed_until_new_goal = False
        return sent

    def _start_add_inspection_point(self):
        self.ui.map_view.set_interaction_mode("inspection_point")
        self._show_toast("在地图上点选巡检点位置", "info")

    def _add_current_pose_to_inspection(self):
        pose = self.store.current_pose
        if not pose:
            QMessageBox.warning(self, "无当前位置", "当前还没有机器人位姿，无法加入巡检点。")
            return
        point = self.inspection_manager.add_waypoint(pose.x, pose.y, pose.yaw)
        self._refresh_inspection_layer()
        self._show_toast(f"当前位置已加入：{point.get('name', '巡检点')}", "success")

    def _refresh_inspection_layer(self, active_id=None):
        if not self._inspection_enabled:
            self.ui.map_view.clear_inspection_points()
            return
        if active_id is None:
            active_id = getattr(self, "_inspection_active_waypoint_id", None)
        plan = self.inspection_manager.current_plan()
        points = []
        if plan:
            points = plan.get("waypoints", []) or []
            if plan.get("mode") == "recorded" and plan.get("route_points"):
                points = plan.get("route_points", [])
        self.ui.map_view.update_inspection_points(points, active_id)

    def _on_patrol_active_waypoint(self, point):
        self._inspection_active_waypoint_id = point.get("id") if point else None
        self._refresh_inspection_layer(self._inspection_active_waypoint_id)

    def _send_patrol_goal(self, x: float, y: float, yaw: float):
        self._send_navigation_goal(x, y, yaw, source="patrol")

    def _publish_patrol_cmd_vel(self, linear: float, angular: float):
        if not hasattr(self, "mqtt_agent"):
            return
        self.mqtt_agent.publish(
            "cmd_vel",
            {
                "linear": {"x": float(linear), "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": float(angular)},
            },
        )

    def _ensure_patrol_navigation(self):
        task = getattr(self, "_patrol_dependency_task", None)
        if task and not task.done():
            return
        self._patrol_dependency_task = asyncio.create_task(self._ensure_patrol_navigation_async())

    async def _ensure_patrol_navigation_async(self):
        try:
            if not self.store.mqtt_running:
                self.store.set_service_busy("mqtt", True, "starting")
                success, message = await self.workflow_ctrl.start_service_async("mqtt")
                if not success:
                    self.patrol_ctrl.stop(f"MQTT 节点启动失败：{message}")
                    return
            if not self.store.chassis_running:
                self.store.set_service_busy("chassis", True, "starting")
                success, message = await self.workflow_ctrl.start_service_async("chassis")
                if not success:
                    self.patrol_ctrl.stop(f"底盘启动失败：{message}")
                    return
            if self.store.navigation_running:
                self.patrol_ctrl.resume_after_navigation_ready()
                return
            self.store.set_navigation_busy(True, "starting")
            map_name = self.ui.control_panel.get_map_name().strip()
            await self.workflow_ctrl.execute_navigation_workflow(map_name)
        except Exception as exc:
            logging.exception("[Patrol] 自动准备巡检依赖失败")
            self.store.set_service_busy("mqtt", False)
            self.store.set_service_busy("chassis", False)
            self.store.set_navigation_busy(False)
            self.patrol_ctrl.stop(f"巡检依赖准备失败：{exc}")
            
    @Slot(float, float, float)
    def _on_manual_initial_pose(self, x: float, y: float, yaw: float):
        import numpy as np
        identity_inv = np.eye(3)
        self.nav_ctrl.set_initial_pose(x, y, yaw, identity_inv)
        logging.info(f"[Manual] Sent initial pose: x={x}, y={y}, yaw={yaw}")

    @Slot(float, float, float)
    def _on_manual_goal(self, x: float, y: float, yaw: float):
        self._send_navigation_goal(x, y, yaw, source="manual")
        logging.info(f"[Manual] Sent nav goal: x={x}, y={y}, yaw={yaw}")

    def _center_map_on_robot(self):
        """将视角中心平滑移动到当前小车所在位置"""
        pose = self.store.current_pose
        if pose is not None and self.ui.map_view:
            self.ui.map_view.centerOn(pose.x, pose.y)

    # ---------------- 杂项设置与仿真 ----------------
    
    @Slot()
    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
            
    @Slot()
    def _show_system_settings(self):
        dialog = SystemSetting(current_config=CONFIG, parent=self)
        if dialog.exec():
            self._apply_settings(dialog.get_settings())

    def _on_dock_settings_saved(self, settings: dict):
        if settings.get("error"):
            QMessageBox.critical(self, "保存失败", f"写入配置文件失败:\n{settings['error']}")
            return
        self._apply_settings(settings, "设置已保存并应用")

    def _apply_settings(self, settings: dict, message: str = "显示设置已应用，连接设置可能需要重启后完全生效"):
        from PySide6.QtWidgets import QApplication

        apply_theme(QApplication.instance(), settings.get("theme", "auto"))
        self._show_toast(message, "info", 3600)
        new_host = settings.get("ip", self.mqtt_agent.host)
        new_port = self.mqtt_agent.port
        try:
            new_port = int(settings.get("port", self.mqtt_agent.port))
        except Exception:
            pass

        if new_host != self.mqtt_agent.host or new_port != self.mqtt_agent.port:
            self.mqtt_agent.update_connection(new_host, new_port)

    # 仿真子进程列表
    _sim_processes = []
    
    @Slot(bool)
    def _toggle_simulation(self, checked: bool):
        self.async_ssh.mock_mode = checked
        if checked:
            self.ui.btn_simulation.setText("停止仿真")
            import subprocess
            scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts')
            for name in ['mock_robot.py', 'mock_lidar.py']:
                p = os.path.join(scripts_dir, name)
                if os.path.isfile(p):
                    proc = subprocess.Popen([sys.executable, p], stdout=None, stderr=None)
                    self._sim_processes.append(proc)
        else:
            self.ui.btn_simulation.setText("仿真")
            for p in self._sim_processes:
                p.terminate()
            self._sim_processes.clear()

    # ---------------- SSH 系统操作 ----------------
    @Slot()
    def _do_start_chassis(self):
        if self.store.service_busy("chassis"):
            return
        if self.store.chassis_running:
            self.store.set_service_busy("chassis", True, "stopping")
            asyncio.create_task(self.workflow_ctrl.execute_stop_chassis_workflow())
            logging.info("[V2] Chassis stop requested.")
        else:
            self.store.set_service_busy("chassis", True, "starting")
            asyncio.create_task(self.workflow_ctrl.execute_chassis_workflow())
            logging.info("[V2] Chassis bringup requested.")

    @Slot()
    def _do_start_mqtt_node(self):
        if self.store.service_busy("mqtt"):
            return
        if self.store.mqtt_running and getattr(self.store, "robot_link_alive", False):
            self.store.set_service_busy("mqtt", True, "stopping")
            asyncio.create_task(self.workflow_ctrl.execute_stop_mqtt_workflow())
            logging.info("[V2] MQTT node stop requested.")
        else:
            self.store.set_service_busy("mqtt", True, "starting")
            asyncio.create_task(self.workflow_ctrl.execute_mqtt_workflow())
            logging.info("[V2] MQTT node start requested.")

    # ---------------- 地图下载/上传 ----------------
    @Slot()
    def _do_download_map(self):
        from PySide6.QtWidgets import QFileDialog
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if save_dir:
            import asyncio
            map_name = self.ui.control_panel.get_map_name().strip() or "my_map"
            asyncio.create_task(self.workflow_ctrl.download_map(map_name, save_dir))
            self._set_workflow_feedback("正在下载地图...", busy=True, tone="info")

    @Slot()
    def _do_upload_map(self):
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(self, "选择地图文件", "", "地图 (*.yaml *.pgm);;All (*)")
        if file_path:
            import asyncio
            asyncio.create_task(self.workflow_ctrl.upload_map(file_path))

    # ---------------- 初始位姿保存/恢复 ----------------
    @Slot()
    def _do_save_initial_pose(self):
        import json
        pose = self.store.current_pose
        if pose:
            data = {"x": pose.x, "y": pose.y, "yaw": pose.yaw, "angle": pose.angle}
            path = PATHS_CONFIG.get('initial_pose_json', 'initial_pose.json')
            with open(path, 'w') as f:
                json.dump(data, f)
            logging.info(f"[V2] Saved initial pose to {path}: {data}")
            self._show_toast(f"初始位姿已保存至 {path}", "success")
        else:
            QMessageBox.warning(self, "无数据", "当前没有有效的机器人位姿")

    @Slot()
    def _do_recall_initial_pose(self):
        import json, numpy as np
        path = PATHS_CONFIG.get('initial_pose_json', 'initial_pose.json')
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            pose = RobotPose.from_dict(data)
            x, y, yaw = pose.x, pose.y, pose.angle
            self.nav_ctrl.set_initial_pose(pose.x, pose.y, pose.yaw, np.eye(3))
            logging.info(f"[V2] Recalled initial pose from {path}: {data}")
            self._show_toast(f"初始位姿已恢复: X={x:.2f} Y={y:.2f} Yaw={yaw:.2f}", "success")
        except FileNotFoundError:
            QMessageBox.warning(self, "文件不存在", f"未找到保存文件: {path}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"恢复失败: {e}")

    # ---------------- MQTT 连接状态 ----------------
    def _on_robot_status_data(self, status: dict):
        if isinstance(status, dict):
            self._note_robot_link("status")

    def _on_tf_data(self, transform: dict):
        self._note_robot_link("tf")
        parent = str(transform.get("parent", "")).lstrip("/")
        child = str(transform.get("child", "")).lstrip("/")
        if parent and child:
            self._frame_transforms[(parent, child)] = transform
            if hasattr(self.store, "update_tf_status"):
                self.store.update_tf_status(True)
        if parent == "map" and child == "odom":
            self._map_to_odom = transform
        self._refresh_mapping_pose()

    def _on_scan_layer_toggled(self, visible: bool):
        self._show_mapping_scan_overlay = bool(visible)
        if visible:
            self._show_toast("雷达点云图层已开启", "info", 1800)
            if not self._should_render_scan_overlay():
                self.ui.map_view.clear_scan()
                return
            scan_data = getattr(self.store, "_state", {}).get("laser_scan")
            if scan_data:
                self._on_store_scan_changed(scan_data)
        else:
            self.ui.map_view.clear_scan()
            self._show_toast("雷达点云图层已隐藏", "info", 1800)

    @staticmethod
    def _invert_transform(transform: dict) -> dict:
        yaw = float(transform.get("yaw", 0.0))
        tx = float(transform.get("x", 0.0))
        ty = float(transform.get("y", 0.0))
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        inv_x = -(cos_yaw * tx + sin_yaw * ty)
        inv_y = sin_yaw * tx - cos_yaw * ty
        return {"x": inv_x, "y": inv_y, "yaw": -yaw}

    @staticmethod
    def _compose_transforms(first: dict, second: dict) -> dict:
        x, y, yaw = apply_pose_transform(
            transform_x=float(first.get("x", 0.0)),
            transform_y=float(first.get("y", 0.0)),
            transform_yaw=float(first.get("yaw", 0.0)),
            pose_x=float(second.get("x", 0.0)),
            pose_y=float(second.get("y", 0.0)),
            pose_yaw=float(second.get("yaw", 0.0)),
        )
        return {"x": x, "y": y, "yaw": yaw}

    @staticmethod
    def _is_finite_values(*values) -> bool:
        try:
            return all(math.isfinite(float(value)) for value in values)
        except (TypeError, ValueError):
            return False

    def _lookup_transform(self, parent: str, child: str):
        parent_norm = str(parent or "").lstrip("/")
        child_norm = str(child or "").lstrip("/")
        if not parent_norm or not child_norm:
            return None
        direct = self._frame_transforms.get((parent_norm, child_norm))
        if direct:
            return direct
        reverse = self._frame_transforms.get((child_norm, parent_norm))
        if reverse:
            return self._invert_transform(reverse)
        return None

    def _resolve_transform_chain_with_path(self, parent: str, child: str, max_depth: int = 6):
        parent_norm = str(parent or "").lstrip("/")
        child_norm = str(child or "").lstrip("/")
        if not parent_norm or not child_norm:
            return None, []
        if parent_norm == child_norm:
            return {"x": 0.0, "y": 0.0, "yaw": 0.0}, [parent_norm]

        adjacency = {}
        for (edge_parent, edge_child), transform in self._frame_transforms.items():
            p = str(edge_parent or "").lstrip("/")
            c = str(edge_child or "").lstrip("/")
            if not p or not c:
                continue
            adjacency.setdefault(p, []).append((c, transform))
            adjacency.setdefault(c, []).append((p, self._invert_transform(transform)))

        queue = [(parent_norm, {"x": 0.0, "y": 0.0, "yaw": 0.0}, [parent_norm], 0)]
        seen = {parent_norm}
        while queue:
            frame, frame_transform, path, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for next_frame, edge_transform in adjacency.get(frame, []):
                if next_frame in seen:
                    continue
                combined = self._compose_transforms(frame_transform, edge_transform)
                next_path = path + [next_frame]
                if next_frame == child_norm:
                    return combined, next_path
                seen.add(next_frame)
                queue.append((next_frame, combined, next_path, depth + 1))
        return None, []

    def _resolve_transform_chain(self, parent: str, child: str, max_depth: int = 6):
        path_resolver = getattr(self, "_resolve_transform_chain_with_path", None)
        if path_resolver:
            transform, _path = path_resolver(parent, child, max_depth)
            return transform

        parent_norm = str(parent or "").lstrip("/")
        child_norm = str(child or "").lstrip("/")
        if not parent_norm or not child_norm:
            return None
        if parent_norm == child_norm:
            return {"x": 0.0, "y": 0.0, "yaw": 0.0}

        adjacency = {}
        for (edge_parent, edge_child), transform in self._frame_transforms.items():
            p = str(edge_parent or "").lstrip("/")
            c = str(edge_child or "").lstrip("/")
            if not p or not c:
                continue
            adjacency.setdefault(p, []).append((c, transform))
            adjacency.setdefault(c, []).append((p, self._invert_transform(transform)))

        queue = [(parent_norm, {"x": 0.0, "y": 0.0, "yaw": 0.0}, 0)]
        seen = {parent_norm}
        while queue:
            frame, frame_transform, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for next_frame, edge_transform in adjacency.get(frame, []):
                if next_frame in seen:
                    continue
                combined = self._compose_transforms(frame_transform, edge_transform)
                if next_frame == child_norm:
                    return combined
                seen.add(next_frame)
                queue.append((next_frame, combined, depth + 1))
        return None

    def _lookup_transform_chain_for_scan(self, parent: str, child: str):
        resolver = getattr(self, "_resolve_transform_chain_with_path", None)
        if resolver:
            return resolver(parent, child)
        transform = self._resolve_transform_chain(parent, child)
        path = [str(parent or "").lstrip("/"), str(child or "").lstrip("/")] if transform else []
        return transform, path

    def _resolve_scan_pose_in_map_detail(self, frame_id: str):
        frame = str(frame_id or "").lstrip("/")
        base_frames = ("base_footprint", "base_link")

        def pose_from_tf_source(source_frame: str):
            pose = getattr(self.store, "current_pose", None)
            if pose and str(pose.source or "").startswith("tf_"):
                return {"x": pose.x, "y": pose.y, "yaw": pose.yaw}, f"pose:{pose.source} scan_frame={source_frame}"
            for base_frame in base_frames:
                transform, path = self._lookup_transform_chain_for_scan("map", base_frame)
                if transform:
                    return transform, f"tf:{'->'.join(path)} scan_frame={source_frame} sensor_tf_missing"
            return None, ""

        if not frame:
            for base_frame in base_frames:
                transform, path = self._lookup_transform_chain_for_scan("map", base_frame)
                if transform:
                    return transform, f"tf:{'->'.join(path)} scan_frame=empty"
            fallback, source = pose_from_tf_source("empty")
            if fallback:
                return fallback, source
            return None, "no_tf:scan_frame=empty"

        transform, path = self._lookup_transform_chain_for_scan("map", frame)
        if transform:
            return transform, f"tf:{'->'.join(path)}"
        fallback, source = pose_from_tf_source(frame)
        if fallback:
            return fallback, source
        known_edges = ",".join(f"{p}->{c}" for p, c in list(getattr(self, "_frame_transforms", {}).keys())[:10])
        return None, f"no_tf:map->{frame} known={known_edges or 'none'}"

    def _resolve_scan_pose_in_map(self, frame_id: str):
        detail_resolver = getattr(self, "_resolve_scan_pose_in_map_detail", None)
        if detail_resolver:
            transform, _source = detail_resolver(frame_id)
            return transform

        frame = str(frame_id or "").lstrip("/")
        base_frames = ("base_footprint", "base_link")
        if not frame:
            for base_frame in base_frames:
                transform = self._resolve_transform_chain("map", base_frame)
                if transform:
                    return transform
            pose = getattr(self.store, "current_pose", None)
            if pose and str(pose.source or "").startswith("tf_"):
                return {"x": pose.x, "y": pose.y, "yaw": pose.yaw}
            return None

        transform = self._resolve_transform_chain("map", frame)
        if transform:
            return transform
        pose = getattr(self.store, "current_pose", None)
        if pose and str(pose.source or "").startswith("tf_"):
            return {"x": pose.x, "y": pose.y, "yaw": pose.yaw}
        for base_frame in base_frames:
            transform = self._resolve_transform_chain("map", base_frame)
            if transform:
                return transform
        return None

    def _log_scan_transform_diagnostic(self, scan_dict: dict, transform: Optional[dict], source: str):
        self._scan_transform_log_counter = getattr(self, "_scan_transform_log_counter", 0) + 1
        frame_id = str((scan_dict or {}).get("frame_id", "")).lstrip("/") or "<empty>"
        ranges = (scan_dict or {}).get("ranges", [])
        range_count = len(ranges) if isinstance(ranges, list) else 0
        age_s = None if self._last_scan_received_at is None else time.monotonic() - self._last_scan_received_at
        if transform:
            x = float(transform.get("x", 0.0))
            y = float(transform.get("y", 0.0))
            yaw = float(transform.get("yaw", 0.0))
            signature = f"{frame_id}|{source}|{round(math.degrees(yaw), 1)}"
            detail = f"x={x:.3f} y={y:.3f} yaw={math.degrees(yaw):.1f}deg"
        else:
            signature = f"{frame_id}|{source}|none"
            detail = "transform=none"
        logging.debug(
            "[V2][ScanTF] frame=%s source=%s %s ranges=%s age=%s",
            frame_id,
            source,
            detail,
            range_count,
            "--" if age_s is None else f"{age_s:.2f}s",
        )
        self._last_scan_transform_signature = signature

    def _resolve_mapping_pose_from_tf(self) -> Optional[RobotPose]:
        for base_frame in ("base_footprint", "base_link"):
            direct = self._lookup_transform("map", base_frame)
            if direct:
                x = float(direct.get("x", 0.0))
                y = float(direct.get("y", 0.0))
                yaw = float(direct.get("yaw", 0.0))
                if not self._is_finite_values(x, y, yaw):
                    continue
                return RobotPose(
                    x=x,
                    y=y,
                    z=0.0,
                    yaw=yaw,
                    angle=math.degrees(yaw),
                    source="tf_map_base",
                )

        map_to_odom = self._lookup_transform("map", "odom")
        if not map_to_odom:
            return None

        for base_frame in ("base_footprint", "base_link"):
            odom_to_base = self._lookup_transform("odom", base_frame)
            if not odom_to_base:
                continue
            map_x = float(map_to_odom.get("x", 0.0))
            map_y = float(map_to_odom.get("y", 0.0))
            map_yaw = float(map_to_odom.get("yaw", 0.0))
            base_x = float(odom_to_base.get("x", 0.0))
            base_y = float(odom_to_base.get("y", 0.0))
            base_yaw = float(odom_to_base.get("yaw", 0.0))
            if not self._is_finite_values(map_x, map_y, map_yaw, base_x, base_y, base_yaw):
                continue
            x, y, yaw = apply_pose_transform(
                transform_x=map_x,
                transform_y=map_y,
                transform_yaw=map_yaw,
                pose_x=base_x,
                pose_y=base_y,
                pose_yaw=base_yaw,
            )
            if not self._is_finite_values(x, y, yaw):
                continue
            return RobotPose(
                x=x,
                y=y,
                z=0.0,
                yaw=yaw,
                angle=math.degrees(yaw),
                source="tf_map_odom_base",
            )
        return None

    def _refresh_mapping_pose(self):
        if not self.store.mapping_running:
            return

        pose = self._resolve_mapping_pose_from_tf()
        source = "TF"
        if pose is None:
            return
        if not self._is_finite_values(pose.x, pose.y, pose.z, pose.yaw, pose.angle):
            return

        self.store.update_robot_pose(pose)
        self._mapping_pose_log_counter += 1
        logging.debug(
            "[V2][MappingPose] source=%s x=%.3f y=%.3f yaw=%.1f°",
            source,
            pose.x,
            pose.y,
            math.degrees(pose.yaw),
        )

    def _on_store_robot_pose_changed(self, pose):
        if not pose:
            return
        if not self._is_finite_values(pose.x, pose.y, pose.z, pose.yaw, pose.angle):
            return
        self.ui.map_view.update_robot_pose(pose.x, pose.y, pose.yaw)
        if self.pose_recorder.recording:
            self.pose_recorder.append(pose.x, pose.y, 0.0, pose.angle)
        self._check_navigation_arrival(pose)

    def _on_store_path_changed(self, path_points):
        if getattr(self, "_path_suppressed_until_new_goal", False):
            self.ui.map_view.clear_path()
            return
        self.ui.map_view.update_path(path_points or [])

    def _check_navigation_arrival(self, pose):
        goal = self._active_nav_goal
        if not goal or not self.store.navigation_running:
            return
        distance = math.hypot(float(pose.x) - float(goal["x"]), float(pose.y) - float(goal["y"]))
        if distance > self._nav_arrival_threshold_m:
            return
        self._active_nav_goal = None
        self._path_suppressed_until_new_goal = True
        self.ui.map_view.clear_path()
        self.store.update_path([])
        self._show_toast("已到达目标位置", "success", 3600)
        self._set_workflow_feedback("已到达目标位置", busy=False, tone="success")

    def _log_mapping_scan(self, status: str):
        self._mapping_scan_log_counter += 1
        if status != self._last_mapping_scan_status:
            logging.info("[V2][MappingScan] %s", status)
            messages = {
                "skipped:disabled": ("雷达点云图层已关闭", "warning"),
                "skipped:no_map_tf": ("等待 map 坐标系下的雷达 TF", "warning"),
                "rendered": ("雷达点云已显示", "success"),
            }
            if status in messages:
                message, tone = messages[status]
                self._set_workflow_feedback(message, busy=False, tone=tone)
        self._last_mapping_scan_status = status

    def _should_render_scan_overlay(self) -> bool:
        return bool(getattr(self.store, "mapping_running", False) or getattr(self.store, "navigation_running", False))

    def _on_store_scan_changed(self, scan_dict):
        if not scan_dict:
            self.ui.map_view.clear_scan()
            return

        should_render_scan = getattr(
            self,
            "_should_render_scan_overlay",
            lambda: bool(getattr(self.store, "mapping_running", False) or getattr(self.store, "navigation_running", False)),
        )
        if not should_render_scan():
            self.ui.map_view.clear_scan()
            return

        frame_id = str(scan_dict.get("frame_id", "")).lstrip("/")
        detail_resolver = getattr(self, "_resolve_scan_pose_in_map_detail", None)
        if detail_resolver:
            scan_transform, scan_source = detail_resolver(frame_id)
        else:
            scan_transform = self._resolve_scan_pose_in_map(frame_id)
            scan_source = "legacy"

        if self.store.mapping_running:
            if not self._show_mapping_scan_overlay:
                self._log_mapping_scan("skipped:disabled")
                self.ui.map_view.clear_scan()
                return
            if scan_transform is None:
                self._log_mapping_scan("skipped:no_map_tf")
                diagnoser = getattr(self, "_log_scan_transform_diagnostic", None)
                if diagnoser:
                    diagnoser(scan_dict, None, scan_source)
                self.ui.map_view.clear_scan()
                return

        if scan_transform is None:
            pose = getattr(self.store, "current_pose", None)
            if pose is None:
                self.ui.map_view.clear_scan()
                return
            scan_transform = {"x": pose.x, "y": pose.y, "yaw": pose.yaw}
            scan_source = f"pose_fallback:{getattr(pose, 'source', '') or 'unknown'}"

        diagnoser = getattr(self, "_log_scan_transform_diagnostic", None)
        if diagnoser:
            diagnoser(scan_dict, scan_transform, scan_source)

        self.ui.map_view.update_scan(
            scan_dict,
            float(scan_transform.get("x", 0.0)),
            float(scan_transform.get("y", 0.0)),
            float(scan_transform.get("yaw", 0.0)),
        )
        if self.store.mapping_running:
            self._log_mapping_scan("rendered")

    def _on_mapping_state_changed(self, running: bool):
        self.ui.map_view.clear_path()
        self.ui.map_view.clear_scan()
        self.store.update_path([])
        self.store.update_scan({})
        self._mapping_scan_log_counter = 0
        self._last_mapping_scan_status = ""
        self._scan_transform_log_counter = 0
        self._last_scan_transform_signature = ""

        if running:
            if getattr(self, "_mapping_scan_default_visible", True):
                self._show_mapping_scan_overlay = True
                map_tools = getattr(getattr(self, "ui", None), "map_tools", None)
                map_view = getattr(getattr(self, "ui", None), "map_view", None)
                if map_tools is not None and hasattr(map_tools, "btn_layers") and not map_tools.btn_layers.isChecked():
                    map_tools.btn_layers.setChecked(True)
                elif map_view is not None and hasattr(map_view, "set_scan_visible"):
                    map_view.set_scan_visible(True)
            self._live_map_received = False
            self._cleared_for_live_map = True
            self._mapping_map_log_counter = 0
            self.ui.map_view.clear_map()
            logging.info("[V2][MappingMap] source=%s cleared_for_live_map=%s", self._map_source.upper(), True)
            return

        logging.info("[V2][MappingMap] source=%s cleared_for_live_map=%s", self._map_source.upper(), self._cleared_for_live_map)

    def _on_mqtt_connection_status(self, connected: bool, message: str):
        logging.info(f"MQTT Status: {connected} - {message}")
        self.store.set_mqtt_broker_connected(connected, message)
        # 更新遥测面板的连接指示器
        if connected:
            self.ui.telemetry_panel.indicator_circle.setStyleSheet("color: #3fb950; font-size: 16px;")
            self.ui.telemetry_panel.status_label.setText("MQTT 已连接")
        else:
            self.ui.telemetry_panel.indicator_circle.setStyleSheet("color: #f14c4c; font-size: 16px;")
            self.ui.telemetry_panel.status_label.setText("MQTT 连接断开")
            self.store.set_robot_link_alive(False, "MQTT Broker 连接断开")
            self.store.update_chassis_status(False)
            if hasattr(self, "patrol_ctrl"):
                self.patrol_ctrl.emergency_stop()

    # ---------------- 建图位姿 ----------------
    def _on_odom_data(self, pose):
        self._note_robot_link("odom")
        # 建图时不使用里程计推算位置，只在 TF 已给出 map 坐标系位姿时刷新。
        self._refresh_mapping_pose()

    def _on_pose_data(self, pose):
        if not pose:
            return
        if not self._is_finite_values(pose.x, pose.y, pose.z, pose.yaw, pose.angle):
            return
        self._note_robot_link("pose")
        # Mapping mode pose should come from TF-resolved map coordinates.
        # Ignore AMCL pose here to avoid overriding mapping pose with stale nav data.
        if self.store.mapping_running:
            return
        self.store.update_robot_pose(pose)

    # ---------------- 键盘遥控 (WASD) ----------------
    def keyPressEvent(self, event):
        if hasattr(self, 'teleop_ctrl'):
            self.teleop_ctrl.handle_key_press(event)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if hasattr(self, 'teleop_ctrl'):
            self.teleop_ctrl.handle_key_release(event)
        super().keyReleaseEvent(event)

    # ---------------- 窗口关闭 ----------------
    def _clear_runtime_layers(self):
        self._active_nav_goal = None
        self._path_suppressed_until_new_goal = False
        self.ui.map_view.clear_path()
        self.ui.map_view.clear_scan()
        self.store.update_path([])
        self.store.update_scan({})

    @Slot(str, bool, str)
    def _on_workflow_finished(self, workflow_name: str, success: bool, message: str):
        logging.info("[WorkflowFinished] %s success=%s msg=%s", workflow_name, success, message)
        service_name = {
            "chassis": "chassis",
            "stop_chassis": "chassis",
            "mqtt": "mqtt",
            "stop_mqtt": "mqtt",
        }.get(workflow_name)
        if service_name:
            self.store.set_service_busy(service_name, False)
        self._record_console_event(message)
        if workflow_name not in {"save_map", "download_map", "upload_map"}:
            self.statusBar().showMessage(message, 6000)

        # 重点优化：当核心启动型服务失败时，给用户一个明确的弹窗，而不是像以前直接吞掉
        if not success and not workflow_name.startswith("stop_"):
            titles = {
                "mqtt": "连接 MQTT 桥接失败",
                "chassis": "启动底盘失败",
                "gmapping": "启动建图失败",
                "navigation": "启动导航失败"
            }
            if workflow_name in titles:
                QMessageBox.warning(self, titles[workflow_name], message)
                self._set_workflow_feedback(message, busy=False, tone="error")

        if workflow_name == "chassis":
            if success:
                self.store.set_chassis_running(True)
                self._show_toast("底盘已启动", "success")
                self._set_workflow_feedback("底盘已启动", busy=False, tone="success")
            return

        if workflow_name == "stop_chassis":
            if success:
                if hasattr(self, "patrol_ctrl"):
                    self.patrol_ctrl.stop("底盘已关闭，巡检停止")
                self.store.set_chassis_running(False)
                self.store.set_mapping_running(False)
                self.store.set_navigation_running(False)
                self._clear_runtime_layers()
                self._show_toast("底盘已关闭", "success")
                self._set_workflow_feedback("底盘已关闭", busy=False, tone="success")
            return

        if workflow_name == "mqtt":
            if success:
                self.store.set_mqtt_running(True)
                self._mqtt_service_started_at = time.monotonic()
                self.store.set_robot_link_alive(False, "等待机器人端 MQTT 桥接心跳")
                self._show_toast("MQTT 桥接已启动", "success")
                self._set_workflow_feedback("MQTT 桥接已启动", busy=False, tone="success")
            return

        if workflow_name == "stop_mqtt":
            if success:
                if hasattr(self, "patrol_ctrl"):
                    self.patrol_ctrl.emergency_stop()
                self.store.set_mqtt_running(False)
                self.store.set_robot_link_alive(False, "MQTT 桥接已关闭")
                self._mqtt_service_started_at = None
                self._last_robot_message_at = None
                self._show_toast("MQTT 桥接已关闭", "success")
                self._set_workflow_feedback("MQTT 桥接已关闭", busy=False, tone="success")
            return

        if workflow_name == "gmapping":
            if success:
                self.store.set_mapping_running(True)
                self._show_toast("建图已启动", "success")
                self._set_workflow_feedback("建图已启动，等待实时地图与雷达点云", busy=False, tone="success")
            else:
                self.store.set_mapping_running(False)
            return

        if workflow_name == "stop_mapping":
            if success:
                self.store.set_mapping_running(False)
                self._clear_runtime_layers()
                self._show_toast("建图已停止", "success")
                self._set_workflow_feedback("建图已停止，可保存或下载地图", busy=False, tone="success")
            return

        if workflow_name == "navigation":
            if success:
                self.store.set_navigation_running(True)
                self._show_toast("导航已启动", "success")
                self._set_workflow_feedback("导航已启动，可设置初始位姿和目标点", busy=False, tone="success")
                if hasattr(self, "patrol_ctrl"):
                    self.patrol_ctrl.resume_after_navigation_ready()
            else:
                self.store.set_navigation_running(False)
                self._set_workflow_feedback(message, busy=False, tone="error")
                if hasattr(self, "patrol_ctrl"):
                    self.patrol_ctrl.stop(f"导航启动失败：{message}")
            self.store.set_navigation_busy(False)
            return

        if workflow_name == "stop_navigation":
            if success:
                if hasattr(self, "patrol_ctrl"):
                    self.patrol_ctrl.stop("导航已关闭，巡检停止")
                self.store.set_navigation_running(False)
                self._clear_runtime_layers()
                self._show_toast("导航已停止", "success")
                self._set_workflow_feedback("导航已停止", busy=False, tone="success")
            self.store.set_navigation_busy(False)
            return

        if workflow_name == "save_map":
            if success:
                self._show_toast("地图已保存并同步到本地", "success")
                self._set_workflow_feedback("地图已保存并同步到本地", busy=False, tone="success")
            else:
                QMessageBox.warning(self, "保存地图失败", message)
                self._set_workflow_feedback(message, busy=False, tone="error")
            return

        if workflow_name == "download_map":
            if success:
                self._show_toast("地图已下载", "success")
                self._set_workflow_feedback("地图已下载", busy=False, tone="success")
            else:
                QMessageBox.warning(self, "下载地图失败", message)
                self._set_workflow_feedback(message, busy=False, tone="error")
            return

        if workflow_name == "upload_map":
            if success:
                self._show_toast("地图已上传到机器人", "success")
                self._set_workflow_feedback("地图已上传到机器人", busy=False, tone="success")
            else:
                QMessageBox.warning(self, "上传地图失败", message)
                self._set_workflow_feedback(message, busy=False, tone="error")
            return

    def closeEvent(self, event):
        for p in self._sim_processes:
            p.terminate()
        try:
            loop = asyncio.get_event_loop()
            asyncio.ensure_future(self.async_ssh.close_async())
        except:
            pass
        event.accept()
