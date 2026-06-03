"""
Core data models used across the app.
"""

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
import math
import time
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class RobotPose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    angle: float = 0.0
    source: str = ""

    @classmethod
    def from_dict(cls, data: dict, default_source: str = "") -> "RobotPose":
        def _safe_float(value: Any, default: float = 0.0) -> float:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return default
            return numeric if math.isfinite(numeric) else default

        if not isinstance(data, dict):
            return cls(source=default_source)

        x = _safe_float(data.get("x", 0.0))
        y = _safe_float(data.get("y", 0.0))
        z = _safe_float(data.get("z", 0.0))

        if "yaw" in data and "angle" not in data:
            yaw = _safe_float(data["yaw"])
            if abs(yaw) > math.pi * 2:
                angle_deg = yaw
                yaw = math.radians(yaw)
            else:
                angle_deg = math.degrees(yaw)
        elif "angle" in data and "yaw" not in data:
            angle_deg = _safe_float(data["angle"])
            yaw = math.radians(angle_deg)
        else:
            yaw = _safe_float(data.get("yaw", 0.0))
            angle_raw = data.get("angle", None)
            if angle_raw is None:
                angle_deg = math.degrees(yaw)
            else:
                angle_val = _safe_float(angle_raw)
                # Some local mock publishers duplicate yaw into angle using radians.
                if math.isclose(angle_val, yaw, rel_tol=1e-6, abs_tol=1e-6):
                    angle_deg = math.degrees(angle_val)
                else:
                    angle_deg = angle_val

        return cls(
            x=x,
            y=y,
            z=z,
            yaw=yaw,
            angle=angle_deg,
            source=data.get("source", default_source),
        )


@dataclass
class MapMetadata:
    resolution: float = 0.05
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_yaw: float = 0.0
    width: int = 0
    height: int = 0
    data: Optional[Any] = None
    encoding: str = "image"

    @classmethod
    def from_dict(cls, data: dict) -> "MapMetadata":
        if not isinstance(data, dict):
            return cls()
        return cls(
            resolution=float(data.get("resolution", 0.05)),
            origin_x=float(data.get("origin_x", 0.0)),
            origin_y=float(data.get("origin_y", 0.0)),
            origin_yaw=float(data.get("origin_yaw", 0.0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            data=data.get("data"),
            encoding=str(data.get("encoding", "image")),
        )


class SystemState(Enum):
    OFFLINE = auto()
    IDLE = auto()
    MAPPING = auto()
    NAVIGATING = auto()


class AppSystemState(QObject):
    state_changed = Signal(SystemState)
    mqtt_changed = Signal(bool)
    chassis_changed = Signal(bool)
    mapping_changed = Signal(bool)
    navigation_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_state = SystemState.OFFLINE
        self._mqtt_running = False
        self._chassis_running = False

    @property
    def current_state(self) -> SystemState:
        return self._current_state

    def set_state(self, new_state: SystemState):
        if self._current_state != new_state:
            old_state = self._current_state
            self._current_state = new_state
            self.state_changed.emit(new_state)

            if old_state == SystemState.MAPPING and new_state != SystemState.MAPPING:
                self.mapping_changed.emit(False)
            if new_state == SystemState.MAPPING:
                self.mapping_changed.emit(True)

            if old_state == SystemState.NAVIGATING and new_state != SystemState.NAVIGATING:
                self.navigation_changed.emit(False)
            if new_state == SystemState.NAVIGATING:
                self.navigation_changed.emit(True)

    @property
    def mapping_running(self) -> bool:
        return self._current_state == SystemState.MAPPING

    @mapping_running.setter
    def mapping_running(self, val: bool):
        if val:
            self.set_state(SystemState.MAPPING)
        elif self._current_state == SystemState.MAPPING:
            self.set_state(SystemState.IDLE if self.chassis_running else SystemState.OFFLINE)

    @property
    def navigation_running(self) -> bool:
        return self._current_state == SystemState.NAVIGATING

    @navigation_running.setter
    def navigation_running(self, val: bool):
        if val:
            self.set_state(SystemState.NAVIGATING)
        elif self._current_state == SystemState.NAVIGATING:
            self.set_state(SystemState.IDLE if self.chassis_running else SystemState.OFFLINE)

    @property
    def mqtt_running(self) -> bool:
        return self._mqtt_running

    @mqtt_running.setter
    def mqtt_running(self, val: bool):
        if self._mqtt_running != val:
            self._mqtt_running = val
            self.mqtt_changed.emit(val)

    @property
    def chassis_running(self) -> bool:
        return self._chassis_running

    @chassis_running.setter
    def chassis_running(self, val: bool):
        if self._chassis_running != val:
            self._chassis_running = val
            self.chassis_changed.emit(val)
            if val and self._current_state == SystemState.OFFLINE:
                self.set_state(SystemState.IDLE)
            elif not val:
                self.set_state(SystemState.OFFLINE)


class ErrorAggregator(QObject):
    error_flushed = Signal(str)

    def __init__(self, flush_interval: float = 2.0, parent=None):
        super().__init__(parent)
        self.flush_interval = flush_interval
        self._error_counts = defaultdict(int)
        self._last_flush_time = time.time()

    def report_error(self, error_key: str, error_detail: str = ""):
        full_msg = f"{error_key}: {error_detail}" if error_detail else error_key
        self._error_counts[full_msg] += 1
        if time.time() - self._last_flush_time > self.flush_interval:
            self.flush()

    def flush(self):
        if not self._error_counts:
            return

        messages = []
        for msg, count in self._error_counts.items():
            if count > 1:
                messages.append(f"[{count} times] {msg}")
            else:
                messages.append(msg)

        self._error_counts.clear()
        self._last_flush_time = time.time()
        self.error_flushed.emit(" \n".join(messages))
