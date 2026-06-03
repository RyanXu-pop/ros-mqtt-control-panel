# service_controller.py
# -*- coding: utf-8 -*-
"""
ServiceController — SSH 服务启停与地图操作控制器

从 MyMainWindow 中抽离的异步服务操作逻辑。通过 Qt 信号与 UI 层解耦：
  - status_message: 状态栏文字更新
  - show_info / show_error / show_warning: 弹窗通知
  - button_enable: 按钮使能控制 (button_name, enabled)

依赖:
  - AppSystemState: 全局状态机
  - AsyncSSHManager: SSH 操作执行层
  - WorkflowController: 复杂流水线编排
"""

import os
import re
import shutil
import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal
from qasync import asyncSlot

from src.network.async_ssh_manager import AsyncSSHManager
from src.controllers.workflow_controller import WorkflowController
from src.core.models import AppSystemState


class ServiceController(QObject):
    """
    SSH 服务启停与地图操作控制器。

    信号:
        status_message(str): 状态栏文字
        show_info(str, str): (title, msg) 弹出信息提示
        show_error(str, str): (title, msg) 弹出错误提示
        show_warning(str, str): (title, msg) 弹出警告提示
        ask_question(str, str): (title, msg) 弹出是/否提问 → 需要 UI 层连接处理
        button_enable(str, bool): (按钮名称, enabled)
        map_saved(str): 地图名称，保存成功后发出
        request_start_mqtt(): 请求 UI 层启动 MQTT 节点（在建图/导航前检查时使用）
    """

    # UI 反馈信号
    status_message = Signal(str)
    show_info = Signal(str, str)
    show_error = Signal(str, str)
    show_warning = Signal(str, str)
    button_enable = Signal(str, bool)

    # 业务事件信号
    map_saved = Signal(str)  # map_name

    def __init__(
        self,
        app_state: AppSystemState,
        async_ssh: AsyncSSHManager,
        workflow_ctrl: WorkflowController,
        parent=None,
    ):
        super().__init__(parent)
        self.app_state = app_state
        self.async_ssh = async_ssh
        self.workflow_ctrl = workflow_ctrl

    # ================================================================== #
    #  MQTT 节点启停
    # ================================================================== #

    @asyncSlot()
    async def toggle_mqtt_async(self):
        """切换 MQTT Bridge 节点启停"""
        if not self.app_state.mqtt_running:
            self.button_enable.emit("start_mqtt_button", False)
            success, msg = await self.async_ssh.start_mqtt_bridge_async()
            if success:
                self.app_state.mqtt_running = True
                self.show_info.emit("MQTT节点", "小车MQTT节点已启动")
            else:
                self.show_error.emit("MQTT节点", f"启动失败: {msg}")
                self.status_message.emit(f"状态: 启动失败: {msg}")
            self.button_enable.emit("start_mqtt_button", True)
        else:
            try:
                await self.async_ssh.stop_mqtt_bridge_async()
                self.app_state.mqtt_running = False
                self.show_info.emit("MQTT节点", "小车MQTT节点已关闭")
                self.button_enable.emit("start_mqtt_button", True)
            except Exception as e:
                self.show_error.emit("MQTT节点", f"关闭失败: {e}")
                self.status_message.emit(f"状态: 关闭失败: {e}")

    # ================================================================== #
    #  底盘启停
    # ================================================================== #

    @asyncSlot()
    async def toggle_chassis_async(self):
        """切换底盘 Bringup 启停"""
        if not self.app_state.chassis_running:
            self.button_enable.emit("start_chassis_button", False)
            success, msg = await self.async_ssh.start_chassis_async()
            if success:
                self.app_state.chassis_running = True
                self.show_info.emit("底盘", "底盘 Bringup 已启动")
            else:
                self.show_error.emit("底盘", f"启动失败: {msg}")
                self.status_message.emit(f"状态: 启动失败: {msg}")
            self.button_enable.emit("start_chassis_button", True)
        else:
            try:
                success, msg = await self.async_ssh.stop_chassis_async()
                if success:
                    self.app_state.chassis_running = False
                else:
                    self.show_error.emit("底盘", f"关闭失败: {msg}")
                    self.button_enable.emit("start_chassis_button", True)
                    return
                self.show_info.emit("底盘", "底盘 Bringup 已关闭")
                self.button_enable.emit("start_chassis_button", True)
            except Exception as e:
                self.show_error.emit("底盘", f"关闭失败: {e}")
                self.status_message.emit(f"状态: 关闭失败: {e}")

    # ================================================================== #
    #  建图启停
    # ================================================================== #

    def can_start_mapping(self) -> tuple[bool, str]:
        """
        检查是否允许启动建图。返回 (可以, 拒绝原因)。
        调用方应在 UI 层处理拒绝。
        """
        if self.app_state.navigation_running:
            return False, "导航正在运行中，无法同时启动建图！\n请先关闭导航。"
        if not self.app_state.chassis_running:
            return False, "请先启动底盘 (Bringup)，建图需要底盘数据"
        if not self.app_state.mqtt_running:
            return False, "MQTT_NOT_RUNNING"  # 特殊标记，UI 层弹出确认对话框
        return True, ""

    @asyncSlot()
    async def toggle_mapping_async(self):
        """切换 Gmapping 建图启停"""
        if not self.app_state.mapping_running:
            can, reason = self.can_start_mapping()
            if not can:
                if reason == "MQTT_NOT_RUNNING":
                    # 信号通知 UI 层处理弹窗确认（需要用户交互）
                    self.show_warning.emit(
                        "建图",
                        "检测到 MQTT 节点未启动！\n\n"
                        "建图画面需要 MQTT 节点将地图数据从机器人转发到本地。\n"
                        "请先启动 MQTT 节点再启动建图。"
                    )
                else:
                    self.show_warning.emit("状态冲突", reason)
                return

            self.button_enable.emit("start_mapping_button", False)
            success, msg = await self.async_ssh.start_gmapping_async()

            if success:
                self.app_state.mapping_running = True
                self.show_info.emit(
                    "建图",
                    "Gmapping 建图已启动！\n\n"
                    "🗺️ 实时地图会在左侧自动更新\n"
                    "🎮 请用键盘或遥控控制机器人移动\n"
                    "💾 完成后点击「保存地图」",
                )
            else:
                self.show_error.emit("建图", f"启动失败: {msg}")
                self.status_message.emit(f"建图启动失败: {msg}")

            self.button_enable.emit("start_mapping_button", True)
        else:
            # 停止建图
            try:
                success, msg = await self.async_ssh.stop_gmapping_async()
                if success:
                    self.app_state.mapping_running = False
                else:
                    self.show_error.emit("建图", f"停止失败: {msg}")
                    return
                self.show_info.emit("建图", "Gmapping 建图已停止")
            except Exception as e:
                self.show_error.emit("建图", f"停止失败: {e}")
                self.status_message.emit(f"状态: 停止建图失败: {e}")

    # ================================================================== #
    #  导航启停
    # ================================================================== #

    def can_start_navigation(self) -> tuple[bool, str]:
        """检查是否允许启动导航。"""
        if self.app_state.mapping_running:
            return False, "建图正在运行中，无法同时启动导航！\n请先停止建图并保存地图。"
        if not self.app_state.chassis_running:
            return False, "请先启动底盘！\n\n导航需要底盘提供 /odom、/tf 等数据"
        return True, ""

    @asyncSlot()
    async def toggle_navigation_async(self):
        """切换 Navigation2 导航启停"""
        if not self.app_state.navigation_running:
            can, reason = self.can_start_navigation()
            if not can:
                self.show_warning.emit("状态冲突" if "建图" in reason else "导航", reason)
                return

            if not self.app_state.mqtt_running:
                self.show_warning.emit(
                    "导航",
                    "MQTT 节点未启动。\n\n"
                    "建议先启动 MQTT 节点，以便在 UI 上显示机器人位姿。\n"
                    "请先启动 MQTT 节点。"
                )
                return

            self.button_enable.emit("start_navigation_button", False)
            self.status_message.emit("状态: 正在启动 Navigation2...")

            success, msg = await self.async_ssh.start_navigation_async()

            if success:
                self.app_state.navigation_running = True
                self.show_info.emit(
                    "导航",
                    "Navigation2 导航已启动！\n\n"
                    "初始位置已自动设置为原点 (0, 0)\n\n"
                    "现在可以：\n"
                    "• 点击地图设置导航目标点\n"
                    "• 或在「导航控制」区域输入目标坐标",
                )
            else:
                self.status_message.emit("状态: 导航启动失败")
                self.show_error.emit("导航", f"启动失败:\n{msg}")

            self.button_enable.emit("start_navigation_button", True)
        else:
            # 关闭导航
            self.status_message.emit("状态: 正在关闭导航...")
            try:
                success, msg = await self.async_ssh.stop_navigation_mode_async()
                if success:
                    self.app_state.navigation_running = False
                    self.app_state.chassis_running = False
                    self.status_message.emit("状态: 导航已关闭")
                    self.show_info.emit("导航", msg or "导航已关闭")
                else:
                    self.status_message.emit("状态: 关闭导航失败")
                    self.show_error.emit("导航", f"关闭导航失败: {msg}")
                self.button_enable.emit("start_navigation_button", True)
            except Exception as e:
                self.status_message.emit("状态: 关闭导航失败")
                self.show_error.emit("导航", f"关闭导航失败: {e}")
                self.button_enable.emit("start_navigation_button", True)

    # ================================================================== #
    #  地图保存
    # ================================================================== #

    @asyncSlot()
    async def save_map_async(self, map_name: str, maps_dir: str, data_map_path: str):
        """
        保存当前地图并同步下载。

        Args:
            map_name: 地图名称（字母数字下划线）
            maps_dir: 本地地图存放目录
            data_map_path: 兼容旧逻辑的 map.png 路径
        """
        if not re.match(r"^[a-zA-Z0-9_]+$", map_name):
            self.show_warning.emit("保存地图", "地图名称只能包含字母、数字和下划线")
            return

        self.button_enable.emit("save_map_button", False)
        self.status_message.emit("状态: 正在保存地图（可能需要10-30秒）...")

        try:
            os.makedirs(maps_dir, exist_ok=True)
            await self.workflow_ctrl.save_and_sync_map_async(map_name, maps_dir)

            # 复制生成的图片到默认 map.png
            local_png = os.path.join(maps_dir, f"{map_name}.png")
            if os.path.exists(local_png) and data_map_path:
                shutil.copy2(local_png, data_map_path)

            self.show_info.emit("地图同步", f"地图 '{map_name}' 已成功保存并同步！")
            self.map_saved.emit(map_name)
            self.button_enable.emit("download_map_button", True)

        except Exception as e:
            self.show_error.emit("保存地图", f"出现错误:\n{e}")
        finally:
            self.button_enable.emit("save_map_button", True)

    # ================================================================== #
    #  地图下载
    # ================================================================== #

    @asyncSlot()
    async def download_map_async(self, map_name: str, local_dir: str):
        """下载地图到指定本地目录"""
        self.button_enable.emit("download_map_button", False)
        self.status_message.emit("状态: 正在下载地图...")

        try:
            success, message = await self.async_ssh.download_map_async(map_name, local_dir)
            if success:
                self.show_info.emit("下载地图", f"地图已下载!\n\n{message}")
                self.status_message.emit("状态: 地图已下载")
            else:
                self.show_error.emit("下载地图", f"下载失败: {message}")
                self.status_message.emit("状态: 下载地图失败")
        except Exception as e:
            self.show_error.emit("下载地图", f"下载异常: {e}")
            self.status_message.emit(f"状态: 下载地图异常: {e}")
        finally:
            self.button_enable.emit("download_map_button", True)

    # ================================================================== #
    #  地图上传
    # ================================================================== #

    @asyncSlot()
    async def upload_map_async(self, pgm_path: str, yaml_path: str):
        """上传本地地图到机器人"""
        self.button_enable.emit("upload_map_button", False)
        self.status_message.emit("状态: 正在上传地图...")

        success, message = await self.async_ssh.upload_map_async(pgm_path, yaml_path)

        self.button_enable.emit("upload_map_button", True)
        if success:
            self.show_info.emit("上传地图", f"上传成功!\n\n{message}")
            self.status_message.emit("状态: 地图已上传到机器人")
        else:
            self.show_error.emit("上传地图", f"上传失败: {message}")
            self.status_message.emit("状态: 上传地图失败")
