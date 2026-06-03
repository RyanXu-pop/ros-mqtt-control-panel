import importlib.util
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


BRIDGE_PATH = Path(__file__).resolve().parents[1] / "ros" / "mqtt_bridge_ros2.py"


def _load_bridge_module(tag: str):
    spec = importlib.util.spec_from_file_location(f"mqtt_bridge_ros2_test_{tag}", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_odometry_message(x=1.0, y=2.0, z=0.0, yaw=0.5, child_frame_id="base_link"):
    import math

    return SimpleNamespace(
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=x, y=y, z=z),
                orientation=SimpleNamespace(
                    x=0.0,
                    y=0.0,
                    z=math.sin(yaw * 0.5),
                    w=math.cos(yaw * 0.5),
                ),
            )
        ),
        child_frame_id=child_frame_id,
    )


def _make_bridge_stub(module):
    published = []

    class DummyBridge:
        def __init__(self):
            self.stats = {
                "ros_odom_count": 0,
                "ros_odom_raw_count": 0,
                "mqtt_pub_odom_count": 0,
                "mqtt_pub_odom_raw_count": 0,
                "errors_count": 0,
            }
            self.last_msg_time = {"odom": None, "odom_raw": None}
            self._odom_lock = threading.Lock()
            self.last_odom_time = None
            self.logger = MagicMock()
            self.client = SimpleNamespace(
                publish=lambda topic, payload: published.append((topic, json.loads(payload)))
            )

        def get_logger(self):
            return self.logger

    DummyBridge._publish_odometry = module.Ros2MqttBridge._publish_odometry
    return DummyBridge(), published


def test_bridge_publishes_fused_odom_to_robot_odom():
    module = _load_bridge_module("fused")
    bridge, published = _make_bridge_stub(module)

    module.Ros2MqttBridge._on_odom(bridge, _make_odometry_message())

    assert bridge.stats["ros_odom_count"] == 1
    assert bridge.stats["mqtt_pub_odom_count"] == 1
    assert bridge.last_msg_time["odom"] is not None
    assert published[0][0] == module.MQTT_TOPICS["odom"]
    assert published[0][1]["source"] == "odom"


def test_bridge_publishes_raw_odom_to_debug_topic_only():
    module = _load_bridge_module("raw")
    bridge, published = _make_bridge_stub(module)

    module.Ros2MqttBridge._on_odom_raw(bridge, _make_odometry_message())

    assert bridge.stats["ros_odom_raw_count"] == 1
    assert bridge.stats["mqtt_pub_odom_count"] == 0
    assert bridge.stats["mqtt_pub_odom_raw_count"] == 1
    assert bridge.last_msg_time["odom_raw"] is not None
    assert published[0][0] == module.MQTT_TOPICS["odom_raw"]
    assert published[0][1]["source"] == "odom_raw"


def test_bridge_main_odom_topic_can_still_be_overridden_to_raw(monkeypatch):
    monkeypatch.setenv("ROS_TOPIC_ODOM", "/odom_raw")
    module = _load_bridge_module("override")

    assert module.ROS_TOPICS["odom"] == "/odom_raw"


def _make_map_message(width=2, height=2):
    return SimpleNamespace(
        info=SimpleNamespace(
            width=width,
            height=height,
            resolution=0.05,
            origin=SimpleNamespace(
                position=SimpleNamespace(x=0.0, y=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            ),
        ),
        data=[0, 100, -1, 0],
    )


def _make_map_bridge_stub(module):
    published = []

    class DummyBridge:
        def __init__(self):
            self.stats = {
                "ros_map_count": 0,
                "mqtt_pub_map_count": 0,
                "errors_count": 0,
            }
            self.last_msg_time = {"map": None}
            self.map_compression_level = 1
            self.logger = MagicMock()
            self.client = SimpleNamespace(
                publish=lambda topic, payload: published.append((topic, json.loads(payload)))
            )

        def get_logger(self):
            return self.logger

    DummyBridge._on_map = module.Ros2MqttBridge._on_map
    return DummyBridge(), published


def test_bridge_realtime_map_mode_publishes_every_map_frame():
    module = _load_bridge_module("map_realtime")
    bridge, published = _make_map_bridge_stub(module)

    module.Ros2MqttBridge._on_map(bridge, _make_map_message())
    module.Ros2MqttBridge._on_map(bridge, _make_map_message())

    assert bridge.stats["ros_map_count"] == 2
    assert bridge.stats["mqtt_pub_map_count"] == 2
    assert [item[0] for item in published] == [module.MQTT_TOPICS["map"], module.MQTT_TOPICS["map"]]
