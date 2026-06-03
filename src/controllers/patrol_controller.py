# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal


class PatrolController(QObject):
    """
    Local inspection runner.

    It does not change navigation, mapping, or MQTT protocols. It only chooses
    the next local plan point and asks existing controllers to publish either a
    Nav2 goal or a conservative cmd_vel command.
    """

    status_changed = Signal(str, str)
    running_changed = Signal(bool, str)
    active_waypoint_changed = Signal(object)
    command_velocity_requested = Signal(float, float)
    goal_requested = Signal(float, float, float)
    ensure_navigation_requested = Signal()
    route_recording_changed = Signal(bool)

    POSE_STALE_TIMEOUT_S = 1.5
    DIRECT_TICK_MS = 120

    def __init__(self, plan_manager, store, parent=None):
        super().__init__(parent)
        self.plan_manager = plan_manager
        self.store = store
        self._running = False
        self._paused = False
        self._awaiting_navigation = False
        self._mode = "nav2"
        self._target_index = 0
        self._goal_sent = False
        self._arrived_at: Optional[float] = None
        self._latest_pose = None
        self._latest_pose_at = 0.0
        self._route_recording = False
        self._recorded_route_points = []

        self._timer = QTimer(self)
        self._timer.setInterval(self.DIRECT_TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def route_recording(self) -> bool:
        return self._route_recording

    def on_robot_pose(self, pose):
        self._latest_pose = pose
        self._latest_pose_at = time.monotonic()
        if self._route_recording and pose is not None:
            self._append_recorded_pose(pose)

    def start(self):
        plan = self.plan_manager.current_plan()
        if not plan:
            self._emit_status("没有可用巡检方案", "error")
            return False

        self._mode = str(plan.get("mode") or "nav2")
        targets = self._targets(plan)
        if not targets:
            self._emit_status("当前方案没有可执行点位", "warning")
            return False

        if self._mode == "nav2" and not self.store.navigation_running:
            self._awaiting_navigation = True
            self._emit_status("正在准备 Nav2 巡检依赖", "info")
            self.ensure_navigation_requested.emit()
            return True

        return self._begin_running()

    def resume_after_navigation_ready(self):
        if self._awaiting_navigation and self.store.navigation_running:
            self._awaiting_navigation = False
            self._begin_running()

    def pause(self, reason: str = "巡检已暂停"):
        if not self._running:
            return
        self._paused = True
        self._send_zero()
        self.running_changed.emit(True, self._mode)
        self._emit_status(reason, "warning")

    def resume(self):
        if not self._running:
            self.start()
            return
        self._paused = False
        self._arrived_at = None
        self._goal_sent = False
        self.running_changed.emit(True, self._mode)
        self._emit_status("巡检继续", "info")

    def stop(self, reason: str = "巡检已停止"):
        if not self._running and not self._awaiting_navigation:
            self._send_zero()
            return
        self._running = False
        self._paused = False
        self._awaiting_navigation = False
        self._goal_sent = False
        self._arrived_at = None
        self._timer.stop()
        self._send_zero()
        self.active_waypoint_changed.emit(None)
        self.running_changed.emit(False, self._mode)
        self._emit_status(reason, "info")

    def emergency_stop(self):
        self.pause("巡检已急停")
        self._send_zero()

    def next_point(self):
        if not self._running:
            return
        self._advance_target(manual=True)

    def mark_arrived(self):
        if not self._running:
            return
        self._emit_status("已确认到达，切换下一点", "success")
        self._advance_target(manual=True)

    def start_route_recording(self):
        if self._route_recording:
            return
        self._recorded_route_points = []
        self._route_recording = True
        self.route_recording_changed.emit(True)
        self._emit_status("开始录制巡检路线", "info")
        if self._latest_pose is not None:
            self._append_recorded_pose(self._latest_pose, force=True)

    def stop_route_recording(self):
        if not self._route_recording:
            return
        self._route_recording = False
        self.route_recording_changed.emit(False)
        if len(self._recorded_route_points) < 2:
            self._emit_status("录制点太少，未保存路线", "warning")
            return
        self.plan_manager.set_route_points(self._recorded_route_points)
        self._emit_status(f"已保存 {len(self._recorded_route_points)} 个路线点", "success")

    def _begin_running(self):
        plan = self.plan_manager.current_plan()
        targets = self._targets(plan)
        if not targets:
            self._emit_status("当前方案没有可执行点位", "warning")
            return False

        if self._mode in {"direct", "recorded"} and self._latest_pose is None:
            self._emit_status("等待机器人当前位置后才能直控巡检", "warning")
            return False

        self._running = True
        self._paused = False
        self._awaiting_navigation = False
        self._target_index = 0
        self._goal_sent = False
        self._arrived_at = None
        self._timer.start()
        self.running_changed.emit(True, self._mode)
        self._emit_status("巡检已开始", "success")
        self._emit_active()
        self._tick()
        return True

    def _targets(self, plan: Optional[dict] = None) -> list:
        if plan is None:
            plan = self.plan_manager.current_plan()
        if not plan:
            return []
        mode = str(plan.get("mode") or "nav2")
        if mode == "recorded":
            route_points = self.plan_manager.route_points()
            if route_points:
                return route_points
        return self.plan_manager.enabled_waypoints()

    def _tick(self):
        if not self._running or self._paused:
            return
        plan = self.plan_manager.current_plan()
        targets = self._targets(plan)
        if not targets:
            self.stop("当前方案没有可执行点位")
            return
        if self._target_index >= len(targets):
            self._target_index = 0

        if not self._safety_ok():
            return

        target = targets[self._target_index]
        if self._mode == "nav2":
            if not self._goal_sent:
                self.goal_requested.emit(
                    float(target.get("x", 0.0)),
                    float(target.get("y", 0.0)),
                    float(target.get("yaw", 0.0)),
                )
                self._goal_sent = True
                self._emit_status(f"已发送目标点：{target.get('name', '未命名')}", "info")
            pose = self._latest_pose
            if pose is not None:
                dx = float(target.get("x", 0.0)) - float(pose.x)
                dy = float(target.get("y", 0.0)) - float(pose.y)
                threshold = max(0.05, float(plan.get("arrival_threshold", 0.35)))
                dwell = max(0.0, float(plan.get("dwell_seconds", 1.0)))
                if math.hypot(dx, dy) <= threshold:
                    if self._arrived_at is None:
                        self._arrived_at = time.monotonic()
                        self._emit_status(f"到达点位：{target.get('name', '未命名')}", "success")
                    if time.monotonic() - self._arrived_at >= dwell:
                        self._advance_target()
                else:
                    self._arrived_at = None
            return

        if self._mode == "manual":
            return

        self._tick_direct(plan, target)

    def _tick_direct(self, plan: dict, target: dict):
        pose = self._latest_pose
        if pose is None:
            self.pause("等待机器人当前位置")
            return

        dx = float(target.get("x", 0.0)) - float(pose.x)
        dy = float(target.get("y", 0.0)) - float(pose.y)
        distance = math.hypot(dx, dy)
        threshold = max(0.05, float(plan.get("arrival_threshold", 0.35)))
        dwell = max(0.0, float(plan.get("dwell_seconds", 1.0)))

        if distance <= threshold:
            self._send_zero()
            if self._arrived_at is None:
                self._arrived_at = time.monotonic()
                self._emit_status(f"到达点位：{target.get('name', '未命名')}", "success")
            if time.monotonic() - self._arrived_at >= dwell:
                self._advance_target()
            return

        self._arrived_at = None
        target_angle = math.atan2(dy, dx)
        heading_error = self._normalize_angle(target_angle - float(pose.yaw))
        max_linear = max(0.03, min(0.25, float(plan.get("direct_max_linear", 0.15))))
        max_angular = max(0.08, min(0.8, float(plan.get("direct_max_angular", 0.45))))

        angular = max(-max_angular, min(max_angular, heading_error * 1.35))
        if abs(heading_error) > 0.85:
            linear = 0.0
        else:
            linear = max_linear * max(0.20, 1.0 - abs(heading_error) / 0.85)
            linear = min(linear, distance * 0.65)

        self.command_velocity_requested.emit(float(linear), float(angular))

    def _advance_target(self, manual: bool = False):
        plan = self.plan_manager.current_plan()
        targets = self._targets(plan)
        if not targets:
            self.stop("巡检完成")
            return

        loop = bool(plan.get("loop", True)) if plan else True
        next_index = self._target_index + 1
        if next_index >= len(targets):
            if not loop:
                self.stop("巡检完成")
                return
            next_index = 0
        self._target_index = next_index
        self._goal_sent = False
        self._arrived_at = None
        self._send_zero()
        self._emit_active()
        if manual or self._mode != "nav2":
            self._emit_status(f"切换到点位：{targets[self._target_index].get('name', '未命名')}", "info")
        self._tick()

    def _safety_ok(self) -> bool:
        if not self.store.chassis_running:
            self.pause("底盘已关闭，巡检暂停")
            return False
        if not self.store.mqtt_broker_connected:
            self.pause("Broker 断开，巡检暂停")
            return False
        if self._mode in {"nav2", "direct", "recorded"}:
            if self._latest_pose_at <= 0 or time.monotonic() - self._latest_pose_at > self.POSE_STALE_TIMEOUT_S:
                self.pause("位姿超时，巡检暂停")
                return False
        if self._mode == "nav2" and not self.store.navigation_running:
            self.pause("导航已关闭，巡检暂停")
            return False
        return True

    def _emit_active(self):
        targets = self._targets()
        if not targets:
            self.active_waypoint_changed.emit(None)
            return
        self.active_waypoint_changed.emit(targets[self._target_index])

    def _send_zero(self):
        self.command_velocity_requested.emit(0.0, 0.0)

    def _append_recorded_pose(self, pose, force: bool = False):
        point = {
            "id": f"route_{int(time.time() * 1000)}_{len(self._recorded_route_points) + 1}",
            "name": f"R{len(self._recorded_route_points) + 1}",
            "x": float(pose.x),
            "y": float(pose.y),
            "yaw": float(pose.yaw),
            "enabled": True,
            "order": len(self._recorded_route_points) + 1,
        }
        if self._recorded_route_points and not force:
            last = self._recorded_route_points[-1]
            if math.hypot(point["x"] - last["x"], point["y"] - last["y"]) < 0.18:
                return
        self._recorded_route_points.append(point)

    def _emit_status(self, message: str, tone: str = "info"):
        self.status_changed.emit(message, tone)

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle
