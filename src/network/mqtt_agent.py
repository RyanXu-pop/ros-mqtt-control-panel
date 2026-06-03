import base64
import json
import logging
import time
from typing import Optional
import zlib

import numpy as np
import paho.mqtt.client as mqtt
from PySide6.QtCore import QObject, Signal

from src.core.constants import MQTT_CONFIG, MQTT_TOPICS_CONFIG, TOPICS_CONFIG
from src.core.models import ErrorAggregator, MapMetadata, RobotPose


class RosMsgAdapter:
    _TOPIC_TYPE_MAP = {
        "pose": "amcl_pose_msg_type",
        "voltage": "power_voltage_msg_type",
        "goal": "pose_stamped_msg_type",
        "initial_pose": "amcl_pose_msg_type",
    }

    @staticmethod
    def get_ros_type_by_topic(topic: str) -> Optional[str]:
        for key, value in MQTT_TOPICS_CONFIG.items():
            if value != topic:
                continue
            if key == "status":
                return None
            ros_key = RosMsgAdapter._TOPIC_TYPE_MAP.get(key)
            if ros_key and ros_key in TOPICS_CONFIG:
                return TOPICS_CONFIG[ros_key]
        return None

    @staticmethod
    def parse(topic: str, payload: str):
        ros_type = RosMsgAdapter.get_ros_type_by_topic(topic)
        try:
            if ros_type in {"geometry_msgs/PoseWithCovarianceStamped", "geometry_msgs/PoseStamped"}:
                return json.loads(payload)
            if ros_type in {"std_msgs/Float32", "std_msgs/UInt16"}:
                return float(payload)
            return json.loads(payload)
        except Exception:
            return payload

    @staticmethod
    def serialize(topic: str, data):
        ros_type = RosMsgAdapter.get_ros_type_by_topic(topic)
        if ros_type == "std_msgs/Float32":
            return str(float(data))
        return json.dumps(data)


class MqttAgent(QObject):
    pose_updated = Signal(RobotPose)
    odom_updated = Signal(RobotPose)
    transform_updated = Signal(dict)

    voltage_updated = Signal(float)
    chassis_status_updated = Signal(bool)
    status_updated = Signal(dict)
    connection_status = Signal(bool, str)
    goal_updated = Signal(dict)
    initialpose_updated = Signal(dict)
    map_updated = Signal(MapMetadata)
    scan_updated = Signal(dict)
    path_updated = Signal(list)
    mqtt_error_aggregated = Signal(str)
    latency_updated = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.error_aggregator = ErrorAggregator(flush_interval=3.0)
        self.error_aggregator.error_flushed.connect(self.mqtt_error_aggregated.emit)

        self.host = MQTT_CONFIG.get("host", "localhost")
        self.port = MQTT_CONFIG.get("port", 1883)
        self.username = MQTT_CONFIG.get("username", None)
        self.password = MQTT_CONFIG.get("password", None)
        self.topics = MQTT_TOPICS_CONFIG
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.is_connected = False
        self._last_remote_latency_at = 0.0

    def connect_broker(self):
        try:
            self.client.connect(self.host, self.port, 60)
            self.client.loop_start()
        except Exception as e:
            logging.error("[MQTT] connect failed: %s", e)
            self.connection_status.emit(False, f"MQTT connect failed: {e}")

    def update_connection(self, host: str, port: int):
        if self.host == host and self.port == port:
            return

        logging.info("[MQTT] updating broker %s:%s -> %s:%s", self.host, self.port, host, port)
        self.host = host
        self.port = port
        self.client.loop_stop()
        if self.is_connected:
            self.client.disconnect()
        self.connect_broker()

    def publish(self, topic_key: str, payload: dict) -> bool:
        if not self.is_connected:
            logging.warning("[MQTT] not connected, cannot publish to %r", topic_key)
            return False

        topic = self.topics.get(topic_key, topic_key)
        try:
            self.client.publish(topic, json.dumps(payload))
            logging.debug("[MQTT] published to %s: %s", topic, payload)
            return True
        except Exception as e:
            logging.error("[MQTT] publish failed (%s): %s", topic, e)
            return False

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.is_connected = True
            self.connection_status.emit(True, "已连接到 MQTT 服务器")
            for topic in self.topics.values():
                client.subscribe(topic)
                logging.info("[MQTT] subscribed: %s", topic)
        else:
            self.connection_status.emit(False, f"MQTT 连接失败，返回码: {reason_code}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.is_connected = False
        self.connection_status.emit(False, f"MQTT 断开连接 (码: {reason_code})")
        logging.warning("[MQTT] disconnected: %s", reason_code)

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode(errors="ignore")

        try:
            parsed = RosMsgAdapter.parse(topic, payload)
        except Exception as e:
            self.error_aggregator.report_error(f"消息解析失败 [{topic}]", str(e))
            return
        received_at = time.time()
        if not self._emit_latency(parsed, received_at):
            # Older robot-side bridge versions do not attach timestamps. Keep the
            # top-bar latency alive from receive events until the bridge is restarted.
            if time.monotonic() - self._last_remote_latency_at > 2.0:
                self.latency_updated.emit(0.0)

        if topic == self.topics.get("pose"):
            if isinstance(parsed, dict):
                self.pose_updated.emit(RobotPose.from_dict(parsed, default_source="amcl"))
        elif topic == self.topics.get("status"):
            if isinstance(parsed, dict):
                self.status_updated.emit(parsed)
                if "chassis_alive" in parsed:
                    self.chassis_status_updated.emit(bool(parsed["chassis_alive"]))
                if "voltage" in parsed and parsed["voltage"] is not None:
                    try:
                        self.voltage_updated.emit(float(parsed["voltage"]))
                    except (ValueError, TypeError) as e:
                        self.error_aggregator.report_error("电压值格式错误", f"值: {parsed['voltage']}, {e}")
        elif topic == self.topics.get("voltage"):
            try:
                self.voltage_updated.emit(float(parsed))
            except (ValueError, TypeError) as e:
                self.error_aggregator.report_error("电压值格式错误", f"值: {parsed}, {e}")
        elif topic == self.topics.get("goal"):
            self.goal_updated.emit(parsed)
        elif topic == self.topics.get("initial_pose"):
            self.initialpose_updated.emit(parsed)
        elif topic == self.topics.get("map"):
            self._handle_map_message(parsed)
        elif topic == self.topics.get("scan"):
            if isinstance(parsed, dict):
                self.scan_updated.emit(parsed)
        elif topic == self.topics.get("odom"):
            if isinstance(parsed, dict):
                self.odom_updated.emit(RobotPose.from_dict(parsed, default_source="odom"))
        elif topic == self.topics.get("tf"):
            if isinstance(parsed, dict):
                self.transform_updated.emit(parsed)
        elif topic == self.topics.get("path"):
            if isinstance(parsed, list):
                self.path_updated.emit(parsed)

    def _emit_latency(self, parsed, received_at: Optional[float] = None) -> bool:
        if not isinstance(parsed, dict):
            return False
        timestamp = parsed.get("timestamp") or parsed.get("stamp") or parsed.get("sent_at")
        if timestamp is None:
            header = parsed.get("header")
            if isinstance(header, dict):
                timestamp = header.get("stamp") or header.get("timestamp")
        try:
            sent_at = float(timestamp)
        except (TypeError, ValueError):
            return False
        if sent_at > 1_000_000_000_000:
            sent_at /= 1000.0
        now = received_at if received_at is not None else time.time()
        latency_ms = max(0.0, (now - sent_at) * 1000.0)
        self._last_remote_latency_at = time.monotonic()
        self.latency_updated.emit(latency_ms)
        return True

    def _handle_map_message(self, data: dict):
        if not isinstance(data, dict):
            return

        try:
            width = data.get("width", 0)
            height = data.get("height", 0)
            resolution = data.get("resolution", 0.05)
            origin_x = data.get("origin_x", 0.0)
            origin_y = data.get("origin_y", 0.0)
            origin_yaw = data.get("origin_yaw", 0.0)
            compressed = data.get("compressed", False)
            data_b64 = data.get("data", "")

            if not data_b64 or width == 0 or height == 0:
                return

            compressed_data = base64.b64decode(data_b64)
            raw_data = zlib.decompress(compressed_data) if compressed else compressed_data
            map_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width))

            map_data = MapMetadata(
                width=width,
                height=height,
                resolution=resolution,
                origin_x=origin_x,
                origin_y=origin_y,
                origin_yaw=origin_yaw,
                data=map_array,
                encoding="occupancy_grid",
            )
            self.map_updated.emit(map_data)
        except Exception as e:
            self.error_aggregator.report_error("解析地图数据失败", str(e))

    def close(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as e:
            logging.error("[MQTT] close failed: %s", e)
