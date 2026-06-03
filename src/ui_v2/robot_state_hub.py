import logging
import math
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from src.core.models import MapMetadata, RobotPose


class RobotStateHub(QObject):
    """
    Single source of truth for V2 UI state.
    """

    voltage_changed = Signal(float, float)
    chassis_alive_changed = Signal(bool)
    robot_pose_changed = Signal(RobotPose)
    laser_scan_changed = Signal(dict)
    global_path_changed = Signal(list)
    map_data_changed = Signal(MapMetadata)

    mapping_state_changed = Signal(bool)
    navigation_state_changed = Signal(bool)
    chassis_service_changed = Signal(bool)
    mqtt_service_changed = Signal(bool)
    mqtt_connection_changed = Signal(bool, str)
    robot_link_changed = Signal(bool, str)
    service_busy_changed = Signal(str, bool, str)
    tf_status_changed = Signal(bool)
    navigation_busy_changed = Signal(bool, str)
    workflow_message = Signal(str)
    latency_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = {
            "chassis_alive": False,
            "voltage": 0.0,
            "chassis_running": False,
            "mqtt_running": False,
            "service_busy": {
                "chassis": {"busy": False, "action": ""},
                "mqtt": {"busy": False, "action": ""},
            },
            "mqtt_broker_connected": False,
            "robot_link_alive": False,
            "mapping_running": False,
            "navigation_running": False,
            "navigation_busy": False,
            "navigation_busy_reason": "",
            "robot_pose": None,
            "target_pose": None,
            "initial_pose": None,
            "map_metadata": None,
            "laser_scan": None,
            "tf_ready": False,
            "global_path": [],
            "latency_ms": None,
        }

        # Watchdog 已被移除，依靠明确的状态事件
        pass

    def _ping_watchdog(self):
        pass

    def _on_watchdog_timeout(self):
        pass

    def update_voltage(self, voltage: float):
        self._ping_watchdog()
        self._state["voltage"] = voltage
        percent = min(max((voltage - 20.0) / (24.0 - 20.0), 0), 1) * 100.0
        self.voltage_changed.emit(voltage, percent)

    def update_chassis_status(self, is_alive: bool):
        self._ping_watchdog()
        if self._state["chassis_alive"] != is_alive:
            self._state["chassis_alive"] = is_alive
            self.chassis_alive_changed.emit(is_alive)

    def update_robot_pose(self, pose: RobotPose):
        numeric_values = (pose.x, pose.y, pose.z, pose.yaw, pose.angle)
        if not all(math.isfinite(value) for value in numeric_values):
            logging.warning("[Store] Ignored non-finite robot pose: %s", pose)
            return
        self._ping_watchdog()
        self._state["robot_pose"] = pose
        self.robot_pose_changed.emit(pose)

    def update_scan(self, scan_data: dict):
        self._ping_watchdog()
        self._state["laser_scan"] = scan_data
        self.laser_scan_changed.emit(scan_data)

    def update_tf_status(self, ready: bool):
        ready = bool(ready)
        if self._state["tf_ready"] == ready:
            return
        self._state["tf_ready"] = ready
        self.tf_status_changed.emit(ready)

    def update_path(self, path: list):
        self._ping_watchdog()
        self._state["global_path"] = path
        self.global_path_changed.emit(path)

    def update_map(self, map_meta: MapMetadata):
        self._ping_watchdog()
        self._state["map_metadata"] = map_meta
        self.map_data_changed.emit(map_meta)

    def update_latency(self, latency_ms: float):
        if not math.isfinite(float(latency_ms)):
            return
        self._state["latency_ms"] = max(0.0, float(latency_ms))
        self.latency_changed.emit(self._state["latency_ms"])

    def set_mqtt_broker_connected(self, connected: bool, message: str = ""):
        if self._state["mqtt_broker_connected"] == connected and not message:
            return
        self._state["mqtt_broker_connected"] = connected
        self.mqtt_connection_changed.emit(connected, message)

    def set_robot_link_alive(self, alive: bool, message: str = ""):
        alive = bool(alive)
        if self._state["robot_link_alive"] == alive and not message:
            return
        self._state["robot_link_alive"] = alive
        self.robot_link_changed.emit(alive, message)
        if not alive and self._state["chassis_alive"]:
            self._state["chassis_alive"] = False
            self.chassis_alive_changed.emit(False)

    def set_mapping_running(self, running: bool):
        self._state["mapping_running"] = running
        self.mapping_state_changed.emit(running)
        if running:
            self.set_navigation_running(False)

    def set_navigation_running(self, running: bool):
        self._state["navigation_running"] = running
        self.navigation_state_changed.emit(running)
        if running:
            self.set_mapping_running(False)

    def set_chassis_running(self, running: bool):
        if self._state["chassis_running"] == running:
            return
        self._state["chassis_running"] = running
        self.chassis_service_changed.emit(running)
        if not running and self._state["chassis_alive"]:
            self._state["chassis_alive"] = False
            self.chassis_alive_changed.emit(False)

    def set_mqtt_running(self, running: bool):
        if self._state["mqtt_running"] == running:
            return
        self._state["mqtt_running"] = running
        self.mqtt_service_changed.emit(running)

    def set_service_busy(self, service_name: str, busy: bool, action: str = ""):
        service_busy = self._state.setdefault("service_busy", {})
        current = service_busy.get(service_name, {"busy": False, "action": ""})
        normalized = {"busy": bool(busy), "action": action if busy else ""}
        if current == normalized:
            return
        service_busy[service_name] = normalized
        self.service_busy_changed.emit(service_name, normalized["busy"], normalized["action"])

    def service_busy(self, service_name: str) -> bool:
        service_busy = self._state.get("service_busy", {})
        return bool(service_busy.get(service_name, {}).get("busy", False))

    def service_busy_action(self, service_name: str) -> str:
        service_busy = self._state.get("service_busy", {})
        return str(service_busy.get(service_name, {}).get("action", ""))

    def set_navigation_busy(self, busy: bool, reason: str = ""):
        self._state["navigation_busy"] = busy
        self._state["navigation_busy_reason"] = reason if busy else ""
        self.navigation_busy_changed.emit(busy, self._state["navigation_busy_reason"])

    def broadcast_message(self, msg: str):
        self.workflow_message.emit(msg)

    @property
    def mapping_running(self) -> bool:
        return self._state["mapping_running"]

    @property
    def navigation_running(self) -> bool:
        return self._state["navigation_running"]

    @property
    def navigation_busy(self) -> bool:
        return self._state["navigation_busy"]

    @property
    def navigation_busy_reason(self) -> str:
        return self._state["navigation_busy_reason"]

    @property
    def current_pose(self) -> Optional[RobotPose]:
        return self._state["robot_pose"]

    @property
    def chassis_running(self) -> bool:
        return self._state["chassis_running"]

    @property
    def mqtt_running(self) -> bool:
        return self._state["mqtt_running"]

    @property
    def mqtt_broker_connected(self) -> bool:
        return self._state["mqtt_broker_connected"]

    @property
    def robot_link_alive(self) -> bool:
        return self._state["robot_link_alive"]

    @property
    def chassis_alive(self) -> bool:
        return self._state["chassis_alive"]

    @property
    def map_available(self) -> bool:
        return self._state["map_metadata"] is not None

    @property
    def scan_available(self) -> bool:
        return bool(self._state["laser_scan"])

    @property
    def tf_ready(self) -> bool:
        return bool(self._state["tf_ready"])

    @property
    def latency_ms(self) -> Optional[float]:
        return self._state.get("latency_ms")
