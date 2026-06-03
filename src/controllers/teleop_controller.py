# src/controllers/teleop_controller.py
# -*- coding: utf-8 -*-
"""
TeleopController — 键盘遥控控制器

将 WASD / 方向键映射为 ROS Twist 消息并通过 MQTT 以 10 Hz 下发。

安全机制:
  - 所有按键松开后，连续发送 ZERO_GRACE_COUNT 帧零速指令确保机器人停车
  - 之后自动停止发送，减少无用网络流量
"""

import json
from PySide6.QtCore import QObject, QTimer, Qt, Slot
import logging
from src.core.constants import MQTT_TOPICS_CONFIG

# 所有受控键集合（提取为模块常量，避免每次事件都创建 tuple）
_TELEOP_KEYS = frozenset({
    Qt.Key_W, Qt.Key_S, Qt.Key_A, Qt.Key_D,
    Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
    Qt.Key_Space,
})

# 零速保护帧数：松开所有按键后额外发送多少帧 (0,0) 确保停车
ZERO_GRACE_COUNT = 5


class TeleopController(QObject):
    """
    键盘遥控控制器 (WASD -> Twist)
    拦截主界面的按键事件，转换为线速度和角速度，通过 MQTT (robot/cmd_vel) 高频下发。
    """
    def __init__(self, mqtt_agent, parent=None):
        super().__init__(parent)
        self.mqtt_agent = mqtt_agent

        # 运动参数
        self.max_linear_speed = 0.5   # m/s
        self.max_angular_speed = 1.0  # rad/s

        # 当前预期速度
        self.target_linear = 0.0
        self.target_angular = 0.0

        # 按下的键集合
        self.pressed_keys: set[int] = set()

        # 零速保护计数器：> 0 时仍需发送零速
        self._zero_grace_remaining = 0

        # 发送定时器 (10 Hz)
        self.publish_timer = QTimer(self)
        self.publish_timer.timeout.connect(self._publish_cmd_vel)
        self.publish_timer.start(100)  # 100 ms

        # MQTT topic
        self.cmd_vel_topic = MQTT_TOPICS_CONFIG.get('cmd_vel', "robot/cmd_vel")

    # ------------------------------------------------------------------ #
    # 键盘事件
    # ------------------------------------------------------------------ #

    def handle_key_press(self, event) -> bool:
        """处理按下事件。返回 True 表示已拦截。"""
        key = event.key()
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self.pressed_keys.clear()
            self.target_linear = 0.0
            self.target_angular = 0.0
            self._zero_grace_remaining = ZERO_GRACE_COUNT
            self._publish_cmd_vel()
            return True
        if key in _TELEOP_KEYS and not event.isAutoRepeat():
            self.pressed_keys.add(key)
            self._update_target_speeds()
            return True
        return False

    def handle_key_release(self, event) -> bool:
        """处理弹起事件。返回 True 表示已拦截。"""
        key = event.key()
        if key == Qt.Key_Space and not event.isAutoRepeat():
            return True
        if key in _TELEOP_KEYS and not event.isAutoRepeat():
            self.pressed_keys.discard(key)
            self._update_target_speeds()
            return True
        return False

    def emergency_stop(self):
        """立即发送零速，等同于按下 Space 急停。"""
        self.pressed_keys.clear()
        self.target_linear = 0.0
        self.target_angular = 0.0
        self._zero_grace_remaining = ZERO_GRACE_COUNT
        self._publish_cmd_vel()

    # ------------------------------------------------------------------ #
    # 速度计算
    # ------------------------------------------------------------------ #

    def _update_target_speeds(self):
        """根据当前按下的组合键计算目标速度"""
        linear = 0.0
        angular = 0.0

        if Qt.Key_W in self.pressed_keys or Qt.Key_Up in self.pressed_keys:
            linear += self.max_linear_speed
        if Qt.Key_S in self.pressed_keys or Qt.Key_Down in self.pressed_keys:
            linear -= self.max_linear_speed

        if Qt.Key_A in self.pressed_keys or Qt.Key_Left in self.pressed_keys:
            angular += self.max_angular_speed
        if Qt.Key_D in self.pressed_keys or Qt.Key_Right in self.pressed_keys:
            angular -= self.max_angular_speed

        self.target_linear = linear
        self.target_angular = angular

        # 如果从有速度变成零速，启动保护帧计数
        if linear == 0.0 and angular == 0.0:
            self._zero_grace_remaining = ZERO_GRACE_COUNT
        else:
            # 有速度就不需要计数
            self._zero_grace_remaining = 0

    # ------------------------------------------------------------------ #
    # 发布
    # ------------------------------------------------------------------ #

    @Slot()
    def _publish_cmd_vel(self):
        """定时发布 cmd_vel Twist 消息（10 Hz）"""
        if not self.mqtt_agent.is_connected:
            return

        is_moving = self.target_linear != 0.0 or self.target_angular != 0.0

        # 空闲静默：没有速度且保护帧已耗尽，不再发送
        if not is_moving and self._zero_grace_remaining <= 0:
            return

        # 消耗一帧保护计数
        if not is_moving:
            self._zero_grace_remaining -= 1

        twist_msg = {
            "linear": {
                "x": float(self.target_linear),
                "y": 0.0,
                "z": 0.0,
            },
            "angular": {
                "x": 0.0,
                "y": 0.0,
                "z": float(self.target_angular),
            },
        }

        self.mqtt_agent.client.publish(self.cmd_vel_topic, json.dumps(twist_msg))
