import asyncio
import glob
import logging
import os
import re
from typing import Tuple

import yaml
from PySide6.QtCore import QObject, Signal

from src.controllers.map_manager import MapManager
from src.core.constants import PATHS_CONFIG
from src.network.async_ssh_manager import AsyncSSHManager


class WorkflowController(QObject):
    """Coordinate longer async workflows across SSH and local map sync."""

    status_message = Signal(str)
    map_synced = Signal(str, str)
    workflow_finished = Signal(str, bool, str)

    def __init__(self, async_ssh: AsyncSSHManager, map_mgr: MapManager, parent=None):
        super().__init__(parent)
        self.async_ssh = async_ssh
        self.map_mgr = map_mgr

    @staticmethod
    def _project_root() -> str:
        return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def _local_maps_dir(self) -> str:
        map_yaml = PATHS_CONFIG.get("map_yaml", "maps/my_map.yaml")
        if os.path.isabs(map_yaml):
            return os.path.dirname(map_yaml)
        return os.path.dirname(os.path.join(self._project_root(), map_yaml))

    @staticmethod
    def _normalize_map_name(map_name: str, default: str = "my_map") -> str:
        name = (map_name or "").strip()
        return name or default

    @staticmethod
    def _validate_map_name(map_name: str) -> Tuple[bool, str]:
        if not re.match(r"^[a-zA-Z0-9_]+$", map_name):
            return False, "地图名称只能包含字母、数字和下划线"
        return True, ""

    @staticmethod
    def _resolve_map_pair_from_selection(file_path: str) -> Tuple[bool, str, str, str]:
        selected = os.path.abspath(file_path)
        base, ext = os.path.splitext(selected)
        ext = ext.lower()

        if ext == ".yaml":
            yaml_path = selected
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    map_cfg = yaml.safe_load(f) or {}
            except Exception as exc:
                return False, f"读取 YAML 失败: {exc}", "", ""

            image_name = map_cfg.get("image")
            if image_name:
                pgm_path = image_name if os.path.isabs(image_name) else os.path.join(os.path.dirname(yaml_path), image_name)
            else:
                pgm_path = f"{base}.pgm"

            if not os.path.exists(pgm_path):
                return False, f"未找到与 YAML 配套的栅格图像: {pgm_path}", "", ""
            return True, "", pgm_path, yaml_path

        if ext == ".pgm":
            pgm_path = selected
            yaml_path = f"{base}.yaml"
            if not os.path.exists(yaml_path):
                return False, f"未找到与 PGM 配套的 YAML: {yaml_path}", "", ""
            return True, "", pgm_path, yaml_path

        return False, "仅支持上传 .yaml 或 .pgm 地图文件", "", ""

    async def save_and_sync_map_async(self, map_name: str, local_maps_dir: str):
        try:
            self.status_message.emit("开始保存地图...")

            success_save, msg_save = await self.async_ssh.save_map_async(map_name)
            if not success_save:
                message = f"保存失败: {msg_save}"
                self.workflow_finished.emit("save_map", False, message)
                return False, message

            self.status_message.emit("地图保存成功，开始下载...")

            success_dl, msg_dl = await self.async_ssh.download_map_async(map_name, local_maps_dir)
            if not success_dl:
                message = f"下载失败: {msg_dl}"
                self.workflow_finished.emit("save_map", False, message)
                return False, message

            self.status_message.emit("下载成功，正在生成前端预览图...")

            local_pgm = os.path.join(local_maps_dir, f"{map_name}.pgm")
            local_yaml = os.path.join(local_maps_dir, f"{map_name}.yaml")
            local_png = os.path.join(local_maps_dir, f"{map_name}.png")

            def convert_map():
                from PIL import Image

                with Image.open(local_pgm) as img:
                    img.convert("L").save(local_png, "PNG")

            os.makedirs(local_maps_dir, exist_ok=True)
            await asyncio.to_thread(convert_map)

            self.status_message.emit("地图已同步并准备就绪")
            self.map_synced.emit(local_png, local_yaml)
            message = f"{msg_save}\n本地地图: {local_yaml}"
            self.workflow_finished.emit("save_map", True, message)
            return True, message
        except Exception as exc:
            err_str = f"地图同步流水线异常: {exc}"
            logging.error(err_str)
            self.workflow_finished.emit("save_map", False, err_str)
            return False, err_str

    async def start_service_async(self, service_name: str) -> Tuple[bool, str]:
        try:
            self.status_message.emit(f"正在启动 {service_name}...")

            if service_name == "chassis":
                success, msg = await self.async_ssh.start_chassis_async()
            elif service_name == "navigation":
                success, msg = await self.async_ssh.start_navigation_async()
            elif service_name == "gmapping":
                success, msg = await self.async_ssh.start_gmapping_async()
            elif service_name == "mqtt":
                success, msg = await self.async_ssh.start_mqtt_bridge_async()
            else:
                success, msg = False, f"unknown service: {service_name}"

            self.status_message.emit(f"{service_name} 启动成功" if success else f"{service_name} 启动失败")
            self.workflow_finished.emit(service_name, success, msg)
            return success, msg
        except Exception as exc:
            err_str = f"启动服务 {service_name} 异常: {exc}"
            logging.error(err_str)
            self.workflow_finished.emit(service_name, False, err_str)
            return False, err_str

    async def stop_service_async(self, service_name: str) -> Tuple[bool, str]:
        try:
            self.status_message.emit(f"正在停止 {service_name}...")

            if service_name == "chassis":
                success, msg = await self.async_ssh.stop_chassis_async()
            elif service_name == "navigation":
                success, msg = await self.async_ssh.stop_navigation_mode_async()
            elif service_name == "gmapping":
                success, msg = await self.async_ssh.stop_gmapping_async()
            elif service_name == "mqtt":
                await self.async_ssh.stop_mqtt_bridge_async()
                success, msg = True, "MQTT 节点已关闭"
            else:
                logging.warning("未知服务无法停止: %s", service_name)
                return False, f"unknown service: {service_name}"

            self.status_message.emit(msg if success else f"{service_name} stop failed: {msg}")
            return success, msg
        except Exception as exc:
            err_str = f"停止服务 {service_name} 异常: {exc}"
            logging.error(err_str)
            self.status_message.emit(err_str)
            return False, err_str

    async def execute_mapping_workflow(self):
        await self.start_service_async("gmapping")

    async def execute_stop_mapping_workflow(self):
        success, msg = await self.stop_service_async("gmapping")
        self.workflow_finished.emit("stop_mapping", success, msg)

    async def execute_stop_chassis_workflow(self):
        success, msg = await self.stop_service_async("chassis")
        self.workflow_finished.emit("stop_chassis", success, msg)

    async def _upload_local_map(self, preferred_map_name: str = "") -> Tuple[bool, str]:
        maps_dir = self._local_maps_dir()
        preferred = self._normalize_map_name(preferred_map_name, default="")

        if preferred:
            yaml_files = [os.path.join(maps_dir, f"{preferred}.yaml")]
        else:
            yaml_files = sorted(glob.glob(os.path.join(maps_dir, "*.yaml")))

        yaml_files = [path for path in yaml_files if os.path.exists(path)]
        if not yaml_files:
            if preferred:
                return False, f"未找到指定地图: {os.path.join(maps_dir, preferred + '.yaml')}"
            return False, f"maps/ 目录下未找到 .yaml 地图文件: {maps_dir}"

        yaml_path = None
        pgm_path = None
        for candidate_yaml in yaml_files:
            try:
                with open(candidate_yaml, "r", encoding="utf-8") as f:
                    map_cfg = yaml.safe_load(f) or {}
            except Exception:
                continue

            pgm_name = map_cfg.get("image", "")
            if not pgm_name:
                continue

            candidate_pgm = pgm_name if os.path.isabs(pgm_name) else os.path.join(os.path.dirname(candidate_yaml), pgm_name)
            if os.path.exists(candidate_pgm):
                yaml_path = candidate_yaml
                pgm_path = candidate_pgm
                break

        if not yaml_path or not pgm_path:
            tried = [os.path.basename(path) for path in yaml_files]
            return False, f"maps/ 下未找到有效的 yaml+pgm 地图对（已检查: {tried}）"

        logging.info(
            "[Workflow] 选定地图: %s + %s",
            os.path.basename(yaml_path),
            os.path.basename(pgm_path),
        )
        self.status_message.emit("正在上传本地地图到小车（覆盖 yahboom_map）...")
        success, msg = await self.async_ssh.upload_map_async(pgm_path, yaml_path)
        if success:
            self.status_message.emit("地图上传成功，继续启动导航...")
            logging.info("[Workflow] 地图已上传: %s → yahboom_map", pgm_path)
        else:
            logging.error("[Workflow] 地图上传失败: %s", msg)
        return success, msg

    async def execute_navigation_workflow(self, map_name: str = ""):
        upload_ok, upload_msg = await self._upload_local_map(map_name)
        if not upload_ok:
            self.status_message.emit(f"地图上传失败，导航中止: {upload_msg}")
            self.workflow_finished.emit("navigation", False, f"地图上传失败: {upload_msg}")
            return
        await self.start_service_async("navigation")

    async def execute_stop_navigation_workflow(self):
        success, msg = await self.stop_service_async("navigation")
        self.workflow_finished.emit("stop_navigation", success, msg)

    async def execute_chassis_workflow(self):
        await self.start_service_async("chassis")

    async def execute_mqtt_workflow(self):
        await self.start_service_async("mqtt")

    async def execute_stop_mqtt_workflow(self):
        success, msg = await self.stop_service_async("mqtt")
        self.workflow_finished.emit("stop_mqtt", success, msg)

    async def execute_save_map_workflow(self, map_name: str = "my_map"):
        map_name = self._normalize_map_name(map_name)
        ok, err = self._validate_map_name(map_name)
        if not ok:
            self.workflow_finished.emit("save_map", False, err)
            return
        await self.save_and_sync_map_async(map_name, self._local_maps_dir())

    async def execute_save_and_stop_mapping_workflow(self, map_name: str = "my_map"):
        map_name = self._normalize_map_name(map_name)
        ok, err = self._validate_map_name(map_name)
        if not ok:
            self.workflow_finished.emit("save_map", False, err)
            return

        saved, _message = await self.save_and_sync_map_async(map_name, self._local_maps_dir())
        if not saved:
            return

        self.status_message.emit("地图已保存，正在停止建图...")
        success, msg = await self.stop_service_async("gmapping")
        self.workflow_finished.emit("stop_mapping", success, msg)

    async def download_map(self, map_name: str, local_dir: str):
        map_name = self._normalize_map_name(map_name)
        ok, err = self._validate_map_name(map_name)
        if not ok:
            self.workflow_finished.emit("download_map", False, err)
            return

        try:
            self.status_message.emit(f"正在下载地图 {map_name}...")
            success, message = await self.async_ssh.download_map_async(map_name, local_dir)
            self.workflow_finished.emit("download_map", success, message)
        except Exception as exc:
            err_str = f"下载地图异常: {exc}"
            logging.error(err_str)
            self.workflow_finished.emit("download_map", False, err_str)

    async def upload_map(self, file_path: str):
        try:
            ok, err, pgm_path, yaml_path = self._resolve_map_pair_from_selection(file_path)
            if not ok:
                self.workflow_finished.emit("upload_map", False, err)
                return

            self.status_message.emit(f"正在上传地图: {os.path.basename(yaml_path)}")
            success, message = await self.async_ssh.upload_map_async(pgm_path, yaml_path)
            self.workflow_finished.emit("upload_map", success, message)
        except Exception as exc:
            err_str = f"上传地图异常: {exc}"
            logging.error(err_str)
            self.workflow_finished.emit("upload_map", False, err_str)
