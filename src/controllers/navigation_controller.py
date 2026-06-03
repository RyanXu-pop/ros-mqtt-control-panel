# navigation_controller.py

import json
import logging
import math
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal

from src.core.constants import PATHS_CONFIG
from src.core.utils import apply_affine_transform


class NavigationController(QObject):
    status_message = Signal(str)

    def __init__(self, mqtt_agent, parent=None):
        super().__init__(parent)
        self._mqtt = mqtt_agent

    def send_goal(
        self,
        x: float,
        y: float,
        affine_M_inv,
        robot_x: float,
        robot_y: float,
    ) -> Tuple[float, float, float]:
        dx = x - robot_x
        dy = y - robot_y
        yaw_rad = math.atan2(dy, dx)
        yaw_deg = math.degrees(yaw_rad)

        x_ros, y_ros = apply_affine_transform(affine_M_inv, [(x, y)])[0]

        self._mqtt.publish("goal", {"x": x_ros, "y": y_ros, "yaw": yaw_rad})
        self.status_message.emit("状态: 目标发送指令已发送")
        logging.debug(
            "[NavCtrl] send_goal -> x_ros=%.3f, y_ros=%.3f, yaw=%.1f deg",
            x_ros,
            y_ros,
            yaw_deg,
        )
        return x, y, yaw_deg

    def send_goal_angle(
        self,
        robot_x: float,
        robot_y: float,
        target_x: float,
        target_y: float,
        affine_M_inv,
    ) -> Tuple[float, float, float]:
        dx = target_x - robot_x
        dy = target_y - robot_y
        yaw_rad = math.atan2(dy, dx)
        yaw_deg = math.degrees(yaw_rad)

        x_ros, y_ros = apply_affine_transform(affine_M_inv, [(robot_x, robot_y)])[0]

        self._mqtt.publish("goal", {"x": x_ros, "y": y_ros, "yaw": yaw_rad})
        self.status_message.emit("状态: 目标角度指令已发送")
        logging.debug(
            "[NavCtrl] send_goal_angle -> x_ros=%.3f, y_ros=%.3f, yaw=%.1f deg",
            x_ros,
            y_ros,
            yaw_deg,
        )
        return robot_x, robot_y, yaw_deg

    def set_goal_pose(self, x: float, y: float, yaw: float, affine_M_inv) -> bool:
        x_ros, y_ros = apply_affine_transform(affine_M_inv, [(x, y)])[0]
        try:
            self._mqtt.publish("goal", {"x": float(x_ros), "y": float(y_ros), "yaw": float(yaw)})
            self.status_message.emit(f"状态: 导航目标 ({x:.2f}, {y:.2f}) 已发送")
            logging.debug("[NavCtrl] set_goal_pose -> x=%.3f, y=%.3f, yaw=%.3f rad", x_ros, y_ros, yaw)
            return True
        except Exception as e:
            logging.error("[NavCtrl] 导航目标发布失败: %s", e)
            return False

    def publish_initial_pose(self, x: float, y: float, yaw: float) -> bool:
        try:
            self._mqtt.publish(
                "initial_pose",
                {
                    "x": float(x),
                    "y": float(y),
                    "yaw": float(yaw),
                    "angle": math.degrees(float(yaw)),
                },
            )
            logging.debug("[NavCtrl] publish_initial_pose -> x=%s, y=%s, yaw=%s", x, y, yaw)
            return True
        except Exception as e:
            logging.error("[NavCtrl] 初始位姿发布失败: %s", e)
            return False

    def set_initial_pose(self, x: float, y: float, yaw: float, affine_M_inv) -> bool:
        x_ros, y_ros = apply_affine_transform(affine_M_inv, [(x, y)])[0]
        result = self.publish_initial_pose(x_ros, y_ros, yaw)
        if result:
            self.status_message.emit(f"状态: 初始位置 ({x:.2f}, {y:.2f}) 同步指令已发送至ROS")
        return result

    def save_initial_pose(self, x_str: str, y_str: str, yaw_str: str) -> bool:
        try:
            pose_data = {"x": x_str, "y": y_str, "yaw": yaw_str}
            with open(PATHS_CONFIG["initial_pose_json"], "w") as f:
                json.dump(pose_data, f)
            self.status_message.emit("状态: 初始位置已保存")
            return True
        except Exception as e:
            self.status_message.emit(f"状态: 保存失败 - {e}")
            logging.error("[NavCtrl] 保存初始位置失败: %s", e)
            return False

    def recall_initial_pose(self) -> Optional[dict]:
        try:
            with open(PATHS_CONFIG["initial_pose_json"], "r") as f:
                pose_data = json.load(f)
            self.status_message.emit("状态: 已恢复保存的初始位置")
            return pose_data
        except FileNotFoundError:
            self.status_message.emit("状态: 未找到已保存的初始位置文件")
            return None
        except Exception as e:
            logging.error("[NavCtrl] 读取初始位置失败: %s", e)
            return None
