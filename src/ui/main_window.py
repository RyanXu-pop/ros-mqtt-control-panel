# main.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
import math
import json
import numpy as np
import os
import logging
from typing import Dict, Any, Tuple, List, Optional
import asyncio
import subprocess

from PySide6.QtWidgets import QApplication, QMainWindow, QDialog, QLineEdit, QDialogButtonBox, QMessageBox, QGridLayout, QLabel
from PySide6.QtCore import Signal, Slot, Qt, QTimer
from PySide6.QtCore import QPoint

from src.core.constants import PATHS_CONFIG, PARAMS_CONFIG, MQTT_CONFIG, MQTT_TOPICS_CONFIG, validate_config_for_main_app
from src.network.mqtt_agent import MqttAgent
from src.network.async_ssh_manager import AsyncSSHManager
from src.controllers.workflow_controller import WorkflowController
from src.ui.views import UIManager
from src.controllers.map_manager import MapManager

from src.controllers.pose_recorder import PoseRecorder
from src.controllers.navigation_controller import NavigationController
from src.controllers.service_controller import ServiceController
from src.core.models import RobotPose, MapMetadata, AppSystemState
from src.core.utils import apply_affine_transform, convert_to_float, BoundedCache
from src.ui.system_setting import SystemSetting
from qasync import asyncSlot




class MyMainWindow(QMainWindow):
    def __init__(self, mqtt_agent=None):
        super().__init__()

        self.map_rotation: float = 0.0
        self.cached_map: Optional[np.ndarray] = None
        self.map_data: Optional[Dict[str, Any]] = None
        self.last_data: Optional[Dict[str, float]] = None
        self.transform_cache: BoundedCache = BoundedCache(maxsize=500)
        # 机器人位置
        self.robot_x: float = 0.0
        self.robot_y: float = 0.0
        self.robot_angle: float = 0.0
        
        # 目标位置
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_angle = 0.0
        
        # 从配置加载参数
        self.map_bounds = PARAMS_CONFIG['map_bounds']

        # 添加config属性，用于UI访问配置
        self.config = PARAMS_CONFIG

        
        # 位置记录相关属性
        self.record_pos_flag = PARAMS_CONFIG.get('record_pos_flag', False)
        self.record_pos_xlsx_path = PATHS_CONFIG.get('record_xlsx', "location_record.xlsx")
        
        self.async_ssh = AsyncSSHManager()
        
        self.affine_M = np.eye(3)
        self.affine_M_inv = np.eye(3)

        # ---- 子模块实例化 ----
        self.map_mgr = MapManager(
            map_bounds=self.map_bounds,
            map_rotation=self.map_rotation,
            transform_cache=self.transform_cache,  # 共享同一渐变缓存
        )
        self.workflow_ctrl = WorkflowController(self.async_ssh, self.map_mgr, self)
        
        # 监听工作流信号
        self.workflow_ctrl.status_message.connect(self._on_workflow_status)
        self.workflow_ctrl.map_synced.connect(self._reload_map_display)

        # 支持依赖注入，方便单元测试
        self.mqtt_agent = mqtt_agent if mqtt_agent is not None else MqttAgent()
        
        # 连接信号
        self.mqtt_agent.pose_updated.connect(self.store_data)
        self.mqtt_agent.odom_updated.connect(self.update_odom_position)  # 建图模式下的机器人位置
        self.mqtt_agent.connection_status.connect(self.on_mqtt_connection_status)
        self.mqtt_agent.voltage_updated.connect(self.update_voltage)
        self.mqtt_agent.chassis_status_updated.connect(self.update_chassis_status)
        self.mqtt_agent.map_updated.connect(self.update_live_map)
        self.mqtt_agent.mqtt_error_aggregated.connect(self.on_mqtt_error)
        self.mqtt_agent.scan_updated.connect(self.update_live_scan)
        self.mqtt_agent.path_updated.connect(self.update_global_path)

        # 实例化统一状态机
        self.app_state = AppSystemState(self)
        self.app_state.mqtt_changed.connect(self._on_mqtt_state_changed)
        self.app_state.chassis_changed.connect(self._on_chassis_state_changed)
        self.app_state.mapping_changed.connect(self._on_mapping_state_changed)
        self.app_state.navigation_changed.connect(self._on_navigation_state_changed)

        # 实例化位置记录器、导航控制器、遥控控制器
        self.pose_recorder = PoseRecorder(xlsx_path=self.record_pos_xlsx_path)
        self.nav_ctrl = NavigationController(mqtt_agent=self.mqtt_agent)
        from src.controllers.teleop_controller import TeleopController
        self.teleop_ctrl = TeleopController(mqtt_agent=self.mqtt_agent, parent=self)

        # 实例化服务控制器（SSH 启停逻辑从此类抽离）
        self.service_ctrl = ServiceController(
            app_state=self.app_state,
            async_ssh=self.async_ssh,
            workflow_ctrl=self.workflow_ctrl,
            parent=self,
        )
        self.service_ctrl.status_message.connect(self.ui_set_status)
        self.service_ctrl.show_info.connect(self._show_info_dialog)
        self.service_ctrl.show_error.connect(self._show_error_dialog)
        self.service_ctrl.show_warning.connect(self._show_warning_dialog)
        self.service_ctrl.button_enable.connect(self._set_button_enabled)

        # --- 窗口在不同平台上的基础优化 ---
        self.setWindowTitle("机器人导航与控制")
        self.setMinimumSize(800, 600)

        # 在 macOS 上：保持原生标题栏（确保三色按钮/标题栏自动显隐行为正常），并自适应窗口大小
        app_instance = QApplication.instance()
        if sys.platform == "darwin":
            # 明确确保是“标准窗口”，避免标题栏按钮被隐藏/异常
            try:
                flags = self.windowFlags()
                flags |= Qt.Window
                flags &= ~Qt.FramelessWindowHint
                self.setWindowFlags(flags)
            except Exception:
                pass

            if app_instance is not None:
                screen = app_instance.primaryScreen()
                if screen is not None:
                    geom = screen.availableGeometry()
                    # 使用可用区域的 80% 大小，更符合 macOS 上的默认应用窗口比例
                    self.resize(int(geom.width() * 0.8), int(geom.height() * 0.8))
        else:
            # 非 macOS：如果可获取屏幕信息，也做一个简单的自适应，避免在高分屏上显得过小
            if app_instance is not None:
                screen = app_instance.primaryScreen()
                if screen is not None:
                    geom = screen.availableGeometry()
                    self.resize(max(geom.width() // 2, 1024), max(geom.height() // 2, 720))
        
        self.ui = UIManager(self)
        self.load_map_data()
        self.ui.setup_ui()
        self.ui.apply_styles()
        
        # 全局信号连接 (事件驱动)
        self.pose_recorder.status_message.connect(self.ui.status_label.setText)
        self.nav_ctrl.status_message.connect(self.ui.status_label.setText)

        
        # UI 就绪后再去连接 MQTT，避免连接回调触发时 UI 尚未创建
        try:
            self.mqtt_agent.connect_broker()
            logging.info("[MainWindow] MqttAgent started and signal connected.")
        except Exception as e:
            logging.error(f"[MainWindow] MqttAgent connect failed at startup: {e}")
        
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_plot)
        self.update_timer.start(100)
        
        # 数据看门狗定时器 (2秒没收到数据就认为断开)
        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.timeout.connect(self._on_watchdog_timeout)
        self.watchdog_timer.start(2000)

    def _reset_watchdog(self):
        """收到任何遥测数据时重置看门狗定时器"""
        if hasattr(self, 'watchdog_timer'):
            self.watchdog_timer.start(2000)

    def _on_watchdog_timeout(self):
        """长时间未收到数据，重置 UI 显示"""
        if hasattr(self.ui, 'telemetry_widget'):
            self.ui.telemetry_widget.set_chassis_status(False)
            self.ui.telemetry_widget.update_voltage("N/A", 0)
        
        if hasattr(self.ui, 'label_chassis_status'):
            self.ui.label_chassis_status.setText("底盘: 离线 (Timeout)")
            self.ui.label_chassis_status.setStyleSheet("color: #FF9500; font-weight: 700;")
        if hasattr(self.ui, 'label_voltage'):
            self.ui.label_voltage.setText("电压: N/A")
        if hasattr(self.ui, 'label_battery_percent'):
            self.ui.label_battery_percent.setText('<span style="color:gray">0%</span>')
        if hasattr(self.ui, 'label_battery_icon'):
            self.ui.label_battery_icon.setText('<span style="font-size:32px;color:gray">🔋</span>')

    def _on_workflow_status(self, msg: str):
        if hasattr(self, 'ui'):
            if hasattr(self.ui, 'telemetry_widget'):
                self.ui.telemetry_widget.set_system_status(msg)
            elif getattr(self.ui, 'status_label', None):
                self.ui.status_label.setText(f"状态: {msg}")

    def load_map_data(self):
        """加载地图数据，委托给 MapManager。"""
        ok = self.map_mgr.load(PATHS_CONFIG['map_yaml'])
        # 同步属性（供旧代码引用）
        self.map_data = self.map_mgr.map_data
        self.cached_map = self.map_mgr.cached_map
        if not ok:
            QMessageBox.critical(self, "错误",
                "地图数据加载失败\n请检查 config.yaml 中的 `map_yaml` 路径")
            return
        if hasattr(self, 'ui') and self.ui:
            self.ui.update_map_display(
                self.map_data, self.robot_x, self.robot_y,
                self.robot_angle, self.target_x, self.target_y
            )


    @Slot(RobotPose)
    def store_data(self, data: RobotPose):
        """
        存储并显示 AMCL 位姿数据（来自 /amcl_pose）
        """
        self._reset_watchdog()
        logging.info(f"[MainWindow] store_data called with: {data}")
        self.last_data = data

        
        # 更新机器人位置（无论是否在导航模式，只要有坐标数据就更新以便观察仿真状态）
        try:
            self.robot_x = data.x
            self.robot_y = data.y
            self.robot_angle = data.angle
            
            # 更新 UI 显示
            if self.map_data:
                self.ui.update_map_display(
                    self.map_data, self.robot_x, self.robot_y, self.robot_angle,
                    self.target_x, self.target_y
                )
                logging.debug(f"[位置] 机器人位置更新: ({data.x:.2f}, {data.y:.2f}, {self.robot_angle:.1f}°)")
        except Exception as e:
            logging.warning(f"更新 AMCL 位姿失败: {e}")


    def on_mqtt_error(self, aggregated_error_msg: str):
        """处理聚合后的高频 MQTT 错误，仅在后台记录，避免弹窗风暴"""
        logging.warning(f"[系统自适应拦截] MQTT 解析异常汇总:\n{aggregated_error_msg}")
        self.ui.status_bar.showMessage("部分 MQTT 数据解析异常，请查看日志", 3000)





    def update_plot(self):
        """更新机器人位置和目标位置显示"""
        if not self.last_data:
            return

        x = self.last_data.x
        y = self.last_data.y
        z = self.last_data.z
        angle = self.last_data.angle

        logging.debug(f"[MainWindow] update_plot: x={x}, y={y}, z={z}, angle={angle}")

        point_key = (x, y)
        if point_key in self.transform_cache:
            transformed_x, transformed_y = self.transform_cache[point_key]
        else:
            transformed_x, transformed_y = apply_affine_transform(self.affine_M, [(x, y)])[0]
            self.transform_cache[point_key] = (transformed_x, transformed_y)
        logging.debug(f"[MainWindow] update_plot: transformed_x={transformed_x}, transformed_y={transformed_y}")

        # 更新机器人位置
        origin_x, origin_y = self.map_data["origin"][0], self.map_data["origin"][1]
        rot_x, rot_y = MapManager.rotate_coords(transformed_x, transformed_y, self.map_rotation, origin_x, origin_y)
        rot_x = max(self.map_bounds[0], min(self.map_bounds[1], rot_x))
        rot_y = max(self.map_bounds[2], min(self.map_bounds[3], rot_y))
        
        # 保存机器人位置用于绘制
        self.robot_x = rot_x
        self.robot_y = rot_y
        self.robot_angle = angle

        if self.record_pos_flag:
            self.pose_recorder.append(transformed_x, transformed_y, z, angle)


        # 更新标签 (通过统一的 TelemetryWidget 接口)
        if hasattr(self.ui, 'telemetry_widget'):
            self.ui.telemetry_widget.update_telemetry(transformed_x, transformed_y, angle, z)
        else:
            self.ui.label_rx.setText(f"X: {transformed_x:.2f}")
            self.ui.label_ry.setText(f"Y: {transformed_y:.2f}")
            self.ui.label_rz.setText(f"Z: {z:.2f}")
            self.ui.label_rd.setText(f"角度: {angle:.2f}")
        logging.debug(f"[MainWindow] update_plot: UI updated X={transformed_x:.2f}, Y={transformed_y:.2f}, Z={z:.2f}, 角度={angle:.2f}")

        # 更新地图显示
        self.ui.update_map_display(
            self.map_data, self.robot_x, self.robot_y, self.robot_angle, self.target_x, self.target_y
        )

    def on_mqtt_connection_status(self, connected, message):
        # 若 UI 尚未初始化，先缓存或直接返回
        if not hasattr(self, "ui") or self.ui is None or not hasattr(self.ui, "status_label"):
            return
            
        status_text = f"已连接到MQTT Broker（{self.mqtt_agent.host}）" if connected else f"MQTT Broker未连接（{self.mqtt_agent.host}）"
        if hasattr(self.ui, 'telemetry_widget'):
            self.ui.telemetry_widget.set_system_status(f"状态: {status_text}")
            self.ui.telemetry_widget.set_connection_state(connected, "已连接" if connected else "未连接")
        else:
            # Fallback
            self.ui.status_label.setText(status_text)
            try:
                self.ui.set_connection_state(connected, "已连接" if connected else "未连接")
            except Exception:
                pass

    def _pixel_to_world_coords(self, event) -> Optional[Tuple[float, float]]:
        """将鼠标点击事件转换为世界坐标。返回 (x, y) 或 None。"""
        pos = event.pos()
        map_label = self.ui.map_label
        map_pixel = map_label.get_map_pixel_from_mouse_pos(pos)
        if map_pixel is None:
            self.ui.status_label.setText("状态: 点击位置超出地图区域")
            return None

        # 获取地图参数（建图模式优先使用实时数据）
        if self.app_state.mapping_running and map_label.live_map_info:
            info = map_label.live_map_info
            height_px = info.get('height', 0)
            resolution = info.get('resolution', 0.05)
            origin = [info.get('origin_x', 0.0), info.get('origin_y', 0.0)]
            if height_px == 0:
                self.ui.status_label.setText("状态: 建图数据尚未就绪")
                return None
        elif self.map_data and "image" in self.map_data:
            height_px = self.map_data["image"].shape[0]
            resolution = self.map_data["resolution"]
            origin = self.map_data["origin"]
        else:
            self.ui.status_label.setText("状态: 无可用的地图数据")
            return None

        # 像素 → 世界（图像Y向下、地图Y向上）
        x = origin[0] + map_pixel.x() * resolution
        y = origin[1] + (height_px - map_pixel.y()) * resolution
        return x, y

    def on_canvas_click(self, event):
        """处理地图点击设置导航目标"""
        if event.button() != Qt.LeftButton:
            return

        if self.app_state.mapping_running:
            self.ui.status_label.setText("状态: 建图模式下不能设置导航目标")
            return

        if self.ui.shared_origin_mode:
            self.handle_shared_origin_click(event)
            return

        try:
            coords = self._pixel_to_world_coords(event)
            if coords is None:
                return
            x, y = coords

            # 应用逆旋转
            origin_x, origin_y = self.map_data["origin"][0], self.map_data["origin"][1]
            x, y = MapManager.inverse_rotate_coords(x, y, self.map_rotation, origin_x, origin_y)

            if not (self.map_bounds[0] <= x <= self.map_bounds[1] and self.map_bounds[2] <= y <= self.map_bounds[3]):
                self.ui.status_label.setText(f"状态: 点击坐标 ({x:.2f}, {y:.2f}) 超出地图范围")
                return

            self.target_x, self.target_y = x, y
            self.ui.x_edit.setText(f"{x:.2f}")
            self.ui.y_edit.setText(f"{y:.2f}")

            if self.last_data:
                start_x = getattr(self.last_data, 'x', 0.0)
                start_y = getattr(self.last_data, 'y', 0.0)
                start_x, start_y = apply_affine_transform(self.affine_M, [(start_x, start_y)])[0]
                self.target_angle = MapManager.calc_direction_angle(start_x, start_y, x, y)
                self.ui.angle_edit.setText(f"{self.target_angle:.2f}")

            self.ui.update_map_display(
                self.map_data, self.robot_x, self.robot_y, self.robot_angle, self.target_x, self.target_y
            )
        except Exception as e:
            self.ui.status_label.setText(f"状态: 处理点击失败 - {e}")
            logging.error(f"处理画布点击失败: {e}")
        
    def handle_shared_origin_click(self, event):
        """处理共同原点设置模式下的地图点击"""
        try:
            coords = self._pixel_to_world_coords(event)
            if coords is None:
                return
            clicked_world_x, clicked_world_y = coords

            # 计算新的原点（让所点像素成为(0,0)）
            map_origin = self.map_data["origin"]
            new_origin_x = map_origin[0] - clicked_world_x
            new_origin_y = map_origin[1] - clicked_world_y
            
            reply = QMessageBox.question(self, "确认设置共同原点", 
                                       f"确认将您点击的位置设置为共同原点 (0,0) 吗？\n\n"
                                       f"(原点将更新以对齐您点击的像素位置)",
                                       QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                # 更新地图原点（内部会reload并刷新UI）
                self.update_map_origin(new_origin_x, new_origin_y)
                
                # 同时更新小车的初始位置为(0,0)
                self.update_robot_initial_position(0.0, 0.0)
                
                # 向ROS同步初始位姿(0,0,0)，保持与共同原点一致
                self.nav_ctrl.publish_initial_pose(0.0, 0.0, 0.0)

                
                # 退出共同原点设置模式
                self.ui.toggle_shared_origin_mode(False)
                
                self.ui.status_label.setText(f"状态: 共同原点已在您点击的位置设置成功，并已同步ROS")
                QMessageBox.information(self, "共同原点设置成功", 
                                      f"地图和小车的共同原点已在您点击的位置设置成功。")
                
                # 更新地图显示
                self.ui.update_map_display(
                    self.map_data, self.robot_x, self.robot_y, self.robot_angle, self.target_x, self.target_y
                )
            else:
                self.ui.status_label.setText("状态: 共同原点设置已取消")
                
        except Exception as e:
            self.ui.status_label.setText(f"状态: 设置共同原点失败 - {e}")
            QMessageBox.critical(self, "错误", f"设置共同原点失败: {e}")
    
    def update_map_origin(self, new_x: float, new_y: float):
        """更新地图原点（委托给 MapManager）。"""
        ok = self.map_mgr.update_origin(new_x, new_y)
        # 同步属性
        self.map_data = self.map_mgr.map_data
        self.cached_map = self.map_mgr.cached_map
        if ok:
            self.ui.status_label.setText(f"状态: 地图原点已更新为 ({new_x:.3f}, {new_y:.3f})")
        else:
            QMessageBox.critical(self, "原点更新失败", f"更新地图原点失败")

    
    def update_robot_initial_position(self, x: float, y: float):
        """更新小车的初始位置"""
        try:
            # 更新UI中的初始位置输入框
            if hasattr(self.ui, 'initial_x_edit') and hasattr(self.ui, 'initial_y_edit'):
                self.ui.initial_x_edit.setText(f"{x:.2f}")
                self.ui.initial_y_edit.setText(f"{y:.2f}")
            
            # 更新地图显示
            if hasattr(self, 'map_data') and self.map_data:
                self.ui.update_map_display(
                    self.map_data,
                    x,
                    y,
                    0.0,  # yaw
                    self.target_x,
                    self.target_y
                )
            
            # 保存到配置文件
            pose_data = {
                "x": f"{x:.3f}",
                "y": f"{y:.3f}",
                "yaw": "0"
            }
            with open(PATHS_CONFIG['initial_pose_json'], 'w') as f:
                json.dump(pose_data, f)
            
            # 重新加载地图显示
            if hasattr(self, 'map_data') and self.map_data:
                self.ui.update_map_display(
                    self.map_data,
                    self.robot_x,
                    self.robot_y,
                    self.robot_angle,
                    self.target_x,
                    self.target_y
                )
            
        except Exception as e:
            self.ui.status_label.setText(f"状态: 更新小车初始位置失败 - {e}")
            logging.error(f"更新小车初始位置失败: {e}")
    
    def _convert_to_float(self, val_str: str) -> Optional[float]:
        return convert_to_float(val_str)

    def set_initial_pose(self):
        """设置初始位置（委托给 NavigationController）。"""
        try:
            x = self._convert_to_float(self.ui.initial_x_edit.text())
            y = self._convert_to_float(self.ui.initial_y_edit.text())
            yaw = self._convert_to_float(self.ui.initial_yaw_edit.text())
            if x is None or y is None or yaw is None:
                raise ValueError("无效的初始位置输入")
            self.nav_ctrl.set_initial_pose(x, y, yaw, self.affine_M_inv)
            if self.map_data:
                self.ui.update_map_display(
                    self.map_data, x, y, yaw, self.target_x, self.target_y
                )
        except Exception as e:
            self.ui.status_label.setText(f"状态: 设置初始位置失败 - {e}")
            QMessageBox.warning(self, "错误", str(e))


    def save_initial_pose(self):
        """保存初始位置（委托给 NavigationController）。"""
        try:
            self.nav_ctrl.save_initial_pose(
                self.ui.initial_x_edit.text(),
                self.ui.initial_y_edit.text(),
                self.ui.initial_yaw_edit.text(),
            )
        except Exception as e:
            self.ui.status_label.setText(f"状态: 保存失败 - {e}")
            QMessageBox.warning(self, "错误", str(e))


    def recall_initial_pose(self):
        """恢复初始位置（委托给 NavigationController）。"""
        pose_data = self.nav_ctrl.recall_initial_pose()
        if pose_data:
            self.ui.initial_x_edit.setText(pose_data.get("x", "0"))
            self.ui.initial_y_edit.setText(pose_data.get("y", "0"))
            self.ui.initial_yaw_edit.setText(pose_data.get("yaw", "0"))


    def reset_initial_pose_to_origin(self, auto_send: bool = True):
        """重置初始位置到原点 (0, 0, 0°)。"""
        try:
            self.ui.initial_x_edit.setText("0")
            self.ui.initial_y_edit.setText("0")
            self.ui.initial_yaw_edit.setText("0")
            self.robot_x = 0.0
            self.robot_y = 0.0
            self.robot_angle = 0.0
            self.ui.label_rx.setText("X: 0.00")
            self.ui.label_ry.setText("Y: 0.00")
            self.ui.label_rz.setText("Z: 0.00")
            self.ui.label_rd.setText("角度: 0.00")
            if auto_send:
                self.nav_ctrl.publish_initial_pose(0.0, 0.0, 0.0)
                self.ui.status_label.setText("状态: 初始位置已设置为原点 (0, 0, 0°)")
                logging.info("初始位置已设置为原点 (0, 0, 0°)")
            else:
                self.ui.status_label.setText("状态: 初始位置已填充为原点，请点击「设置」确认")
            if self.map_data:
                self.ui.update_map_display(
                    self.map_data, 0.0, 0.0, 0.0, self.target_x, self.target_y
                )
        except Exception as e:
            logging.error(f"重置初始位置失败: {e}")
            self.ui.status_label.setText(f"状态: 设置初始位置失败 - {e}")


    def send_coordinates(self):
        """发送目标坐标（委托给 NavigationController）。"""
        try:
            x = self._convert_to_float(self.ui.x_edit.text())
            y = self._convert_to_float(self.ui.y_edit.text())
            if x is None or y is None:
                raise ValueError("无效的目标坐标输入")
            self.target_x, self.target_y, self.target_angle = self.nav_ctrl.send_goal(
                x, y, self.affine_M_inv, self.robot_x, self.robot_y
            )
            if self.map_data:
                self.ui.update_map_display(
                    self.map_data, self.robot_x, self.robot_y,
                    self.robot_angle, self.target_x, self.target_y
                )
        except Exception as e:
            self.ui.status_label.setText(f"状态: 发送失败 - {e}")
            QMessageBox.warning(self, "错误", str(e))


    def send_angle(self):
        """发送目标角度（委托给 NavigationController）。"""
        try:
            tx = self._convert_to_float(self.ui.x_edit.text())
            ty = self._convert_to_float(self.ui.y_edit.text())
            if tx is None or ty is None:
                raise ValueError("无效的目标坐标输入")
            self.target_x, self.target_y, self.target_angle = self.nav_ctrl.send_goal_angle(
                self.robot_x, self.robot_y, tx, ty, self.affine_M_inv
            )
        except Exception as e:
            self.ui.status_label.setText(f"状态: 发送失败 - {e}")
            QMessageBox.warning(self, "错误", str(e))


    def system_setting(self):
        """打开系统设置对话框"""
        from src.core.constants import CONFIG
        dialog = SystemSetting(current_config=CONFIG, parent=self)
        if dialog.exec():
            # 对话框已将配置写入 config.yaml
            # 检查 MQTT 连接信息是否改变，如果改变则重连
            settings = dialog.get_settings()
            new_host = settings.get("ip", self.mqtt_agent.host)
            try:
                new_port = int(settings.get("port", self.mqtt_agent.port))
            except (ValueError, TypeError):
                new_port = self.mqtt_agent.port
            if new_host != self.mqtt_agent.host or new_port != self.mqtt_agent.port:
                self.mqtt_agent.update_connection(new_host, new_port)
            logging.info("系统设置已更新（部分设置需重启生效）")

    # ------------------------------------------------------------------ #
    # 仿真模式
    # ------------------------------------------------------------------ #

    _sim_processes: List[subprocess.Popen] = []

    @Slot(bool)
    def toggle_simulation(self, checked: bool):
        """启动/停止仿真模式（运行 mock_robot + mock_lidar 子进程）"""
        # 同步切换 SSH 的指令拦截（模拟）模式
        self.async_ssh.mock_mode = checked
        
        if checked:
            self._start_simulation()
        else:
            self._stop_simulation()

    def _start_simulation(self):
        """Spawn 仿真子进程"""
        scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts')
        python_exe = sys.executable
        scripts = ['mock_robot.py', 'mock_lidar.py']

        for name in scripts:
            path = os.path.join(scripts_dir, name)
            if not os.path.isfile(path):
                logging.warning(f"[仿真] 脚本不存在: {path}")
                continue
            try:
                proc = subprocess.Popen(
                    [python_exe, path],
                    # 不再使用 PIPE 以防止在 Windows 上因缓存区满导致进程挂起
                    # 同时让输出直接打印在控制台，方便用户调试
                    stdout=None,
                    stderr=None,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                )
                self._sim_processes.append(proc)
                logging.info(f"[仿真] 已启动 {name} (PID={proc.pid})")
            except Exception as e:
                logging.error(f"[仿真] 启动 {name} 失败: {e}")

        if self._sim_processes:
            self.ui.button_simulation.setText("🔴 停止仿真")
            self.ui.status_label.setText("状态: 仿真模式已启动")
        else:
            self.ui.button_simulation.setChecked(False)
            QMessageBox.warning(self, "仿真模式", "没有找到仿真脚本，请确认 scripts/ 目录存在")

    def _stop_simulation(self):
        """停止所有仿真子进程"""
        for proc in self._sim_processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                logging.info(f"[仿真] 已停止进程 PID={proc.pid}")
        self._sim_processes.clear()
        self.ui.button_simulation.setText("🟢 启动仿真")
        self.ui.status_label.setText("状态: 仿真模式已停止")




    @Slot(bool)
    def _on_mqtt_state_changed(self, running: bool):
        if running:
            self.ui.start_mqtt_button.setText("关闭 MQTT 节点")
            self.ui.status_label.setText("状态: 小车MQTT节点已启动")
        else:
            self.ui.start_mqtt_button.setText("启动 MQTT 节点")
            self.ui.status_label.setText("状态: 小车MQTT节点已关闭")
            
    @Slot(bool)
    def _on_chassis_state_changed(self, running: bool):
        if running:
            self.ui.start_chassis_button.setText("关闭底盘")
            self.ui.status_label.setText("状态: 底盘 Bringup 已启动")
        else:
            self.ui.start_chassis_button.setText("启动底盘 (Bringup)")
            self.ui.status_label.setText("状态: 底盘 Bringup 已关闭")
            
    @Slot(bool)
    def _on_mapping_state_changed(self, running: bool):
        if running:
            self.ui.start_mapping_button.setText("停止建图")
            self.ui.label_mapping_status.setText("建图状态: 运行中")
            self.ui.label_mapping_status.setStyleSheet("color: #34C759; font-weight: bold;")
            self.ui.save_map_button.setEnabled(True)
            self.ui.map_label.set_mapping_mode(True)
            self.ui.status_label.setText("状态: Gmapping 建图运行中，请移动机器人探索环境")
        else:
            self.ui.start_mapping_button.setText("启动建图 (Gmapping)")
            self.ui.label_mapping_status.setText("建图状态: 已停止")
            self.ui.label_mapping_status.setStyleSheet("color: #FF9500;")
            self.ui.save_map_button.setEnabled(False)
            self.ui.map_label.set_mapping_mode(False)
            self.ui.status_label.setText("状态: 建图已停止")
            
    @Slot(bool)
    def _on_navigation_state_changed(self, running: bool):
        if running:
            self.ui.start_navigation_button.setText("关闭导航")
            self.ui.status_label.setText("状态: Navigation2 导航运行中，正在初始化...")
        else:
            self.ui.start_navigation_button.setText("启动导航")
            self.ui.status_label.setText("状态: 导航已关闭")


    # ================================================================== #
    # ServiceController 信号处理（通用 UI 反馈槽函数）
    # ================================================================== #

    def ui_set_status(self, msg: str):
        """状态栏更新（ServiceController.status_message 信号目标）"""
        self.ui.status_label.setText(msg)

    def _show_info_dialog(self, title: str, msg: str):
        QMessageBox.information(self, title, msg)

    def _show_error_dialog(self, title: str, msg: str):
        QMessageBox.critical(self, title, msg)

    def _show_warning_dialog(self, title: str, msg: str):
        QMessageBox.warning(self, title, msg)

    def _set_button_enabled(self, button_name: str, enabled: bool):
        """按名称查找 UI 按钮并设置使能状态"""
        btn = getattr(self.ui, button_name, None)
        if btn is not None:
            btn.setEnabled(enabled)
        elif hasattr(self.ui, 'control_panel_widget'):
            btn = getattr(self.ui.control_panel_widget, button_name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    # ================================================================== #
    # SSH 服务操作（委托给 ServiceController）
    # ================================================================== #

    @asyncSlot()
    async def start_mqtt_node_action(self):
        await self.service_ctrl.toggle_mqtt_async()

    @asyncSlot()
    async def start_chassis_action(self):
        """启动/停止底盘 Bringup"""
        await self.service_ctrl.toggle_chassis_async()

    @asyncSlot()
    async def start_mapping_action(self):
        """启动/停止 Gmapping 建图"""
        await self.service_ctrl.toggle_mapping_async()

    @asyncSlot()
    async def save_map_action(self):
        """保存当前地图并同步下载"""
        if hasattr(self.ui, 'control_panel_widget'):
            map_name = self.ui.control_panel_widget.get_map_name().strip() or "my_map"
        else:
            map_name = self.ui.input_map_name.text().strip() or "my_map"

        maps_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "maps")
        data_map_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "map.png")
        await self.service_ctrl.save_map_async(map_name, maps_dir, data_map_path)

    def _reload_map_display(self, map_png_path: str, map_yaml_path: str = None):
        """重新加载地图显示（委托给 MapManager）。"""
        ok = self.map_mgr.reload_display(map_png_path, map_yaml_path)
        if ok:
            self.map_bounds = self.map_mgr.map_bounds
            self.map_data = self.map_mgr.map_data
            self.cached_map = self.map_mgr.cached_map
            self.ui.update_map_display(
                self.map_data, self.robot_x, self.robot_y,
                self.robot_angle, self.target_x, self.target_y,
            )

    @asyncSlot()
    async def download_map_action(self):
        """下载地图到本地（QFileDialog 必须在 UI 层）"""
        from PySide6.QtWidgets import QFileDialog
        map_name = self.ui.input_map_name.text().strip() or "my_map"
        local_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", os.path.expanduser("~"))
        if not local_dir:
            return
        await self.service_ctrl.download_map_async(map_name, local_dir)

    @asyncSlot()
    async def upload_map_action(self):
        """上传本地地图到机器人（QFileDialog 必须在 UI 层）"""
        from PySide6.QtWidgets import QFileDialog
        default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "maps")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~")

        pgm_path, _ = QFileDialog.getOpenFileName(
            self, "选择地图 PGM 文件", default_dir, "PGM Files (*.pgm);;All Files (*)"
        )
        if not pgm_path:
            return

        yaml_path = pgm_path.replace('.pgm', '.yaml')
        if not os.path.exists(yaml_path):
            yaml_path, _ = QFileDialog.getOpenFileName(
                self, "选择地图 YAML 文件", os.path.dirname(pgm_path), "YAML Files (*.yaml);;All Files (*)"
            )
            if not yaml_path:
                QMessageBox.warning(self, "上传地图", "需要同时选择 PGM 和 YAML 文件")
                return

        map_name = os.path.splitext(os.path.basename(pgm_path))[0]
        reply = QMessageBox.question(
            self, "上传地图",
            f"将上传地图: {map_name}\n\n"
            f"PGM: {pgm_path}\nYAML: {yaml_path}\n\n"
            f"这将覆盖机器人容器内的 yahboom_map 文件。\n确定上传吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return
        await self.service_ctrl.upload_map_async(pgm_path, yaml_path)

    @Slot(RobotPose)
    def update_odom_position(self, data: RobotPose):
        """
        更新机器人位置（来自主 odom，用于建图模式）
        """
        self._reset_watchdog()
        if not self.app_state.mapping_running and not self.app_state.navigation_running:
            return
        
        try:
            # 更新机器人位置
            self.robot_x = data.x
            self.robot_y = data.y
            self.robot_angle = data.angle

            
            # 更新 UI 显示的动态元素（机器人位置）
            if hasattr(self.ui, 'map_label') and self.ui.map_label.mapping_mode:
                # 在建图模式下，使用实时地图的参数
                if self.ui.map_label.live_map_info:
                    info = self.ui.map_label.live_map_info
                    elements = {
                        "robot_pos": (data.x, data.y, self.robot_angle),
                        "target_pos": (self.target_x, self.target_y),
                        "map_info": {

                            "resolution": info.get('resolution', 0.05),
                            "origin": [info.get('origin_x', 0.0), info.get('origin_y', 0.0), 0.0],
                            "height": info.get('height', 0),
                            "width": info.get('width', 0)
                        },
                        "enable_shared_origin": False
                    }
                    self.ui.map_label.set_dynamic_elements(elements)
        except Exception as e:
            logging.debug(f"更新 odom 位置失败: {e}")

    @Slot(MapMetadata)
    def update_live_map(self, map_data: MapMetadata):
        """更新实时地图显示（建图模式 或 导航模式）"""
        if hasattr(self.ui, 'map_label'):
            # 记录收到地图数据的日志
            width = map_data.width
            height = map_data.height
            
            if self.app_state.mapping_running:
                # 建图模式：更新实时地图
                logging.info(f"[建图] 收到地图数据: {width}x{height}")
                self.ui.map_label.update_live_map(map_data)
                self.ui.status_label.setText(f"状态: 建图运行中 | 地图: {width}x{height}")
            elif self.app_state.navigation_running:
                # 导航模式：更新导航地图显示
                logging.info(f"[导航] 收到地图数据: {width}x{height}")
                # 将 MQTT 格式转换为 UI 需要的格式
                origin_x = map_data.origin_x
                origin_y = map_data.origin_y
                resolution = map_data.resolution
                data = map_data.data  # numpy array
                
                if data is not None:
                    # 转换为 RGB 图像用于显示
                    # OccupancyGrid: 0=空闲(白), 100=障碍(黑), -1/255=未知(灰)
                    img_data = np.zeros((height, width, 3), dtype=np.uint8)
                    img_data[data == 0] = [255, 255, 255]  # 空闲 = 白色

                    img_data[data == 100] = [0, 0, 0]       # 障碍 = 黑色
                    img_data[(data != 0) & (data != 100)] = [128, 128, 128]  # 未知 = 灰色
                    
                    # 更新 map_data 供 UI 使用
                    self.map_data = {
                        "resolution": resolution,
                        "origin": [origin_x, origin_y, 0.0],
                        "image": np.flipud(img_data),  # 翻转 Y 轴以匹配地图坐标系
                        "extent": self.map_bounds
                    }
                    
                    # 更新显示
                    self.ui.update_map_display(
                        self.map_data, self.robot_x, self.robot_y, self.robot_angle,
                        self.target_x, self.target_y
                    )
                    self.ui.status_label.setText(f"状态: 导航运行中 | 地图: {width}x{height}")
            else:
                logging.debug("[地图] 收到地图数据但无活动模式，忽略")

    @Slot(dict)
    def update_live_scan(self, scan_data: dict):
        """接收并转发最新的 LaserScan 数据给 MapLabel"""
        if hasattr(self.ui, 'map_label'):
            self.ui.map_label.set_scan_data(scan_data)

    @Slot(list)
    def update_global_path(self, path_points: list):
        """接收并转发 Nav2 全局路径到 MapLabel 绘制"""
        if hasattr(self.ui, 'map_label'):
            self.ui.map_label.set_path_data(path_points)

    @asyncSlot()
    async def start_navigation_action(self):
        """启动/停止 Navigation2 导航"""
        # 导航成功启动时需要自动设置初始位姿，所以部分逻辑保留在此
        if not self.app_state.navigation_running:
            can, reason = self.service_ctrl.can_start_navigation()
            if not can:
                QMessageBox.warning(self, "状态冲突" if "建图" in reason else "导航", reason)
                return
            if not self.app_state.mqtt_running:
                reply = QMessageBox.question(self, "导航",
                    "MQTT 节点未启动。\n\n"
                    "建议先启动 MQTT 节点，以便在 UI 上显示机器人位姿。\n\n"
                    "是否继续启动导航？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.No:
                    return
            await self.service_ctrl.toggle_navigation_async()
            # 导航启动成功后自动设置初始位姿
            if self.app_state.navigation_running:
                self.reset_initial_pose_to_origin(auto_send=True)
        else:
            await self.service_ctrl.toggle_navigation_async()

    def start_record_position(self):
        """开始记录位置（委托给 PoseRecorder）。"""
        self.pose_recorder.start()
        self.record_pos_flag = True  # 保留为外部检查兼容
        self.ui.button_record_position_xlsx_start.setEnabled(False)
        self.ui.button_record_position_xlsx_stop.setEnabled(True)


    def stop_record_position(self):
        """停止记录位置（委托给 PoseRecorder）。"""
        ok = self.pose_recorder.stop()
        self.record_pos_flag = False  # 保留为外部检查兼容
        if ok:
            QMessageBox.information(self, "成功",
                f"位置信息已保存到 {self.record_pos_xlsx_path}")
        self.ui.button_record_position_xlsx_start.setEnabled(True)
        self.ui.button_record_position_xlsx_stop.setEnabled(False)


    def record_current_position(self):
        """记录当前位置到列表（格式化委托给 PoseRecorder）。"""
        if not self.ui.recorded_positions_display:
            return
        record_str = self.pose_recorder.format_current(self.last_data, self.affine_M)
        if record_str is None:
            record_str = f"{__import__('time').strftime('%H:%M:%S')} - 位置未石"
            self.ui.status_label.setText("状态: 记录失败 (无位置数据)")
        else:
            self.ui.status_label.setText("状态: 当前位置已记录")
        self.ui.recorded_positions_display.addItem(record_str)
        self.ui.recorded_positions_display.scrollToBottom()


    def delete_selected_record(self):
        """删除选中的记录"""
        if not self.ui.recorded_positions_display:
            return
        selected_items = self.ui.recorded_positions_display.selectedItems()
        if not selected_items:
            self.ui.status_label.setText("状态: 请先选择一条记录以删除")
            QMessageBox.information(self, "无选中项", "请先在'记录的位置'列表中选择一条记录。")
            return
        item_to_delete = selected_items[0]
        row = self.ui.recorded_positions_display.row(item_to_delete)
        self.ui.recorded_positions_display.takeItem(row)
        self.ui.status_label.setText("状态: 选中的记录已删除")

    def closeEvent(self, event):
        """窗口关闭事件：确保清理所有后台进程和连接"""
        # 1. 停止仿真模式
        self._stop_simulation()
        
        # 2. 停止 MQTT 代理
        if hasattr(self, 'mqtt_agent'):
            try:
                self.mqtt_agent.stop()
            except Exception as e:
                logging.error(f"[Cleanup] 停止 MQTT 失败: {e}")
                
        # 3. 停止 SSH 任务
        # 注意：AsyncSSHManager 工作在 asyncio 循环中，这里只是同步触发
        
        logging.info("应用正在关闭...")
        event.accept()

    def keyPressEvent(self, event):
        """全局键盘按下事件侦听，用于键盘遥感"""
        if hasattr(self, 'teleop_ctrl') and self.teleop_ctrl:
            if self.teleop_ctrl.handle_key_press(event):
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """全局键盘弹起事件侦听"""
        if hasattr(self, 'teleop_ctrl') and self.teleop_ctrl:
            if self.teleop_ctrl.handle_key_release(event):
                event.accept()
                return
        super().keyReleaseEvent(event)

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.mqtt_agent.close()
        # 清理异步任务循环（如有未完成的等待）
        loop = asyncio.get_event_loop()
        future = asyncio.ensure_future(self.async_ssh.close_async())
        # 对于退出时的释放，通常也可以选择不等待，但如果必须清理远程：
        # loop.run_until_complete(future) （这里就不写了，避免卡界面）
        event.accept()

    def update_chassis_status(self, is_alive: bool):
        """更新底盘健康状态显示"""
        self._reset_watchdog()
        if hasattr(self.ui, 'telemetry_widget'):
            self.ui.telemetry_widget.set_chassis_status(is_alive)
        elif hasattr(self.ui, 'label_chassis_status'):
            if is_alive:
                self.ui.label_chassis_status.setText("底盘: 在线 (Ready)")
                self.ui.label_chassis_status.setStyleSheet("color: #34C759; font-weight: 700;")
            else:
                self.ui.label_chassis_status.setText("底盘: 离线 (No Odom)")
                self.ui.label_chassis_status.setStyleSheet("color: #FF9500; font-weight: 700;")

    def update_voltage(self, voltage: float):
        self._reset_watchdog()
        self.voltage = voltage
        percent = min(max((voltage - 20.0) / (24.0 - 20.0), 0), 1)  # 24~26V线性百分比
        percent_val = float(percent * 100)
        
        if hasattr(self.ui, 'telemetry_widget'):
            self.ui.telemetry_widget.update_voltage(f"{voltage:.2f}", percent_val)
        else:
            # Fallback for old ui
            if hasattr(self.ui, 'label_voltage'):
                self.ui.label_voltage.setText(f"电压: {voltage:.2f} V")
            if hasattr(self.ui, 'label_battery_icon'):
                color = 'green' if voltage >= 24.0 else ('red' if voltage <= 20.0 else 'yellow')
                self.ui.label_battery_icon.setText(f'<span style="font-size:32px;color:{color}">🔋</span>')
            if hasattr(self.ui, 'label_battery_percent'):
                percent_color = 'red' if voltage <= 20.0 else 'green'
                self.ui.label_battery_percent.setText(f'<span style="color:{percent_color}">{int(percent_val)}%</span>')


