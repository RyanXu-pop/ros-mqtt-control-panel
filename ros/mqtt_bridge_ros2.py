#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROS 2 Humble <-> MQTT Bridge (运行于机器人端 Docker 容器内)

环境变量配置（必须）：
- MQTT_HOST: MQTT Broker 地址（通常是控制端 Mac 的 IP）
- MQTT_PORT: MQTT Broker 端口（默认 1883）
- MAP_COMPRESSION_LEVEL: /map zlib 压缩等级，0-9

Topic 约定（与本项目 config.yaml 保持一致）：
- ROS2 -> MQTT
  - /amcl_pose (geometry_msgs/PoseWithCovarianceStamped) -> robot/pose (json)
  - /odom (nav_msgs/Odometry) -> robot/odom (json) + 用于检测底盘存活状态
  - /odom_raw (nav_msgs/Odometry) -> robot/odom_raw (json, 调试用)
  - /battery (std_msgs/UInt16) -> 电池电压
  - /map (nav_msgs/OccupancyGrid) -> robot/map (compressed json)
  - /scan (sensor_msgs/LaserScan) -> robot/scan (json)
  - /plan (nav_msgs/Path) -> robot/path (json, 全局路径规划)
- MQTT -> ROS2
  - robot/goal (json) -> /goal_pose (geometry_msgs/PoseStamped)
  - robot/initial_pose (json) -> /initialpose (geometry_msgs/PoseWithCovarianceStamped)
"""

import json
import math
import os
import threading
import time
import base64
import zlib
from datetime import datetime
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

# ============================================================================== #
# 话题配置 (优先从环境变量读取，否则使用默认值)
# ============================================================================== #

# ROS 话题名称
ROS_TOPICS = {
    "amcl_pose": os.getenv("ROS_TOPIC_AMCL", "/amcl_pose"),
    "odom": os.getenv("ROS_TOPIC_ODOM", "/odom"),
    "odom_raw": os.getenv("ROS_TOPIC_ODOM_RAW", "/odom_raw"),
    "battery": os.getenv("ROS_TOPIC_BATTERY", "/battery"),
    "map": os.getenv("ROS_TOPIC_MAP", "/map"),
    "scan": os.getenv("ROS_TOPIC_SCAN", "/scan"),
    "plan": os.getenv("ROS_TOPIC_PLAN", "/plan"),
    "tf": os.getenv("ROS_TOPIC_TF", "/tf"),
    "tf_static": os.getenv("ROS_TOPIC_TF_STATIC", "/tf_static"),
    "cmd_vel": os.getenv("ROS_TOPIC_CMD_VEL", "/cmd_vel"),
    "goal": os.getenv("ROS_TOPIC_GOAL", "/goal_pose"),
    "initialpose": os.getenv("ROS_TOPIC_INITIALPOSE", "/initialpose"),
}

# MQTT 话题名称 (与控制端 config.yaml 保持一致)
MQTT_TOPICS = {
    "pose": os.getenv("MQTT_TOPIC_POSE", "robot/pose"),
    "odom": os.getenv("MQTT_TOPIC_ODOM", "robot/odom"),
    "odom_raw": os.getenv("MQTT_TOPIC_ODOM_RAW", "robot/odom_raw"),
    "status": os.getenv("MQTT_TOPIC_STATUS", "robot/status"),
    "voltage": os.getenv("MQTT_TOPIC_VOLTAGE", "robot/voltage"),
    "map": os.getenv("MQTT_TOPIC_MAP", "robot/map"),
    "scan": os.getenv("MQTT_TOPIC_SCAN", "robot/scan"),
    "path": os.getenv("MQTT_TOPIC_PATH", "robot/path"),
    "tf": os.getenv("MQTT_TOPIC_TF", "robot/tf"),
    "goal": os.getenv("MQTT_TOPIC_GOAL", "robot/goal"),
    "initial_pose": os.getenv("MQTT_TOPIC_INITIAL_POSE", "robot/initial_pose"),
    "cmd_vel": os.getenv("MQTT_TOPIC_CMD_VEL", "robot/cmd_vel"),
}

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy, QoSHistoryPolicy, qos_profile_sensor_data
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
    from nav_msgs.msg import Odometry, OccupancyGrid, Path
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import UInt16
    from tf2_msgs.msg import TFMessage
except Exception:
    rclpy = None
    Node = object
    ExternalShutdownException = Exception
    QoSProfile = object
    QoSDurabilityPolicy = object
    QoSReliabilityPolicy = object
    QoSHistoryPolicy = object
    qos_profile_sensor_data = object
    PoseStamped = object
    PoseWithCovarianceStamped = object
    Twist = object
    Odometry = object
    OccupancyGrid = object
    Path = object
    LaserScan = object
    UInt16 = object
    TFMessage = object


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    """从四元数计算 yaw（弧度）"""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def quaternion_from_yaw(yaw: float) -> Dict[str, float]:
    """从 yaw（弧度）构造平面旋转四元数"""
    return {"x": 0.0, "y": 0.0, "z": math.sin(yaw * 0.5), "w": math.cos(yaw * 0.5)}


def int_from_env(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


class Ros2MqttBridge(Node):
    def __init__(self, mqtt_host: str, mqtt_port: int):
        super().__init__("mqtt_bridge_ros2")
        
        self.start_time = time.time()
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # ========== 统计计数器 ==========
        self.stats = {
            # ROS 订阅计数
            "ros_amcl_pose_count": 0,
            "ros_odom_count": 0,
            "ros_odom_raw_count": 0,
            "ros_battery_count": 0,
            "ros_map_count": 0,
            "ros_scan_count": 0,
            "ros_tf_count": 0,
            # MQTT 发布计数
            "mqtt_pub_pose_count": 0,
            "mqtt_pub_odom_count": 0,
            "mqtt_pub_odom_raw_count": 0,
            "mqtt_pub_status_count": 0,
            "mqtt_pub_map_count": 0,
            "mqtt_pub_scan_count": 0,
            "mqtt_pub_tf_count": 0,
            # MQTT 接收计数
            "mqtt_recv_goal_count": 0,
            "mqtt_recv_initial_pose_count": 0,
            # 错误计数
            "errors_count": 0,
        }
        
        # ========== 最后收到消息的时间戳 ==========
        self.last_msg_time = {
            "amcl_pose": None,
            "odom": None,
            "odom_raw": None,
            "battery": None,
            "map": None,
            "scan": None,
            "tf": None,
            "mqtt_goal": None,
            "mqtt_initial_pose": None,
        }

        # Chassis health monitoring
        self.last_odom_time: Optional[float] = None
        self.current_voltage: Optional[float] = None
        self._odom_lock = threading.Lock()

        # Gmapping 地图数据
        self.map_compression_level: int = int_from_env("MAP_COMPRESSION_LEVEL", 1, 0, 9)

        # ========== 启动诊断信息 ==========
        self._print_startup_banner()

        # ========== ROS 订阅 ==========
        self._setup_ros_subscriptions()
        
        # ========== ROS 发布者 ==========
        self.pub_goal = self.create_publisher(PoseStamped, ROS_TOPICS["goal"], 10)
        self.pub_initialpose = self.create_publisher(PoseWithCovarianceStamped, ROS_TOPICS["initialpose"], 10)
        self.pub_cmd_vel = self.create_publisher(Twist, ROS_TOPICS["cmd_vel"], 10)
        self.get_logger().info(f"📤 [ROS PUB] 已创建发布者: {ROS_TOPICS['goal']}, {ROS_TOPICS['initialpose']}, {ROS_TOPICS['cmd_vel']}")

        # Status heartbeat timer (every 1 second)
        self.status_timer = self.create_timer(1.0, self._publish_status_heartbeat)
        
        # 诊断定时器（每 30 秒打印一次统计信息）
        self.diag_timer = self.create_timer(30.0, self._print_diagnostics)

        # ========== MQTT 连接 ==========
        self._setup_mqtt_connection()

        # ========== 最终启动确认 ==========
        self._print_subscription_summary()
        self.get_logger().info("=" * 60)
        self.get_logger().info("✅ Bridge fully initialized | 桥接完全初始化完成")
        self.get_logger().info("=" * 60)

    def _print_startup_banner(self):
        """打印启动横幅和系统信息"""
        self.get_logger().info("=" * 60)
        self.get_logger().info("🚀 ROS 2 <-> MQTT Bridge 启动中...")
        self.get_logger().info("=" * 60)
        self.get_logger().info(f"⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.get_logger().info(f"🔧 ROS_DOMAIN_ID: {os.getenv('ROS_DOMAIN_ID', 'not set')}")
        self.get_logger().info(f"🌐 MQTT Broker: {self.mqtt_host}:{self.mqtt_port}")
        self.get_logger().info(f"📦 节点名称: {self.get_name()}")
        self.get_logger().info(f"🗺️ 地图转发: realtime, zlib_level={self.map_compression_level}")
        self.get_logger().info("-" * 60)

    def _setup_ros_subscriptions(self):
        """设置所有 ROS 订阅"""
        self.get_logger().info("📥 [ROS SUB] 开始设置 ROS 话题订阅...")
        
        # /amcl_pose - AMCL 定位位姿
        try:
            self.sub_amcl = self.create_subscription(
                PoseWithCovarianceStamped, ROS_TOPICS["amcl_pose"], self._on_amcl_pose, 10)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['amcl_pose']} (PoseWithCovarianceStamped) - AMCL 定位位姿")
        except Exception as e:
            self.get_logger().error(f"  ❌ {ROS_TOPICS['amcl_pose']} 订阅失败: {e}")
            self.sub_amcl = None

        # /odom - 融合里程计
        try:
            self.sub_odom = self.create_subscription(
                Odometry, ROS_TOPICS["odom"], self._on_odom, 10)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['odom']} (Odometry) - 融合里程计")
        except Exception as e:
            self.get_logger().error(f"  ❌ {ROS_TOPICS['odom']} 订阅失败: {e}")
            self.sub_odom = None

        # /odom_raw - 原始里程计
        try:
            self.sub_odom_raw = self.create_subscription(
                Odometry, ROS_TOPICS["odom_raw"], self._on_odom_raw, 10)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['odom_raw']} (Odometry) - 原始里程计")
        except Exception as e:
            self.get_logger().error(f"  ❌ {ROS_TOPICS['odom_raw']} 订阅失败: {e}")
            self.sub_odom_raw = None

        # /battery - 电池电压
        try:
            self.sub_battery_uint16 = self.create_subscription(
                UInt16, ROS_TOPICS["battery"], self._on_battery_uint16, 10)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['battery']} (UInt16) - 电池电压")
        except Exception as e:
            self.get_logger().error(f"  ❌ {ROS_TOPICS['battery']} 订阅失败: {e}")
            self.sub_battery_uint16 = None

        # /map - 地图数据（建图/导航）
        try:
            self.sub_map = self.create_subscription(
                OccupancyGrid, ROS_TOPICS["map"], self._on_map, 10)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['map']} (OccupancyGrid) - 地图数据")
        except Exception as e:
            self.get_logger().error(f"  ❌ {ROS_TOPICS['map']} 订阅失败: {e}")
            self.sub_map = None

        # /scan - 激光雷达数据
        try:
            self.sub_scan = self.create_subscription(
                LaserScan, ROS_TOPICS["scan"], self._on_scan, qos_profile_sensor_data)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['scan']} (LaserScan) - 激光雷达")
        except Exception as e:
            self.get_logger().warn(f"  ⚠️ {ROS_TOPICS['scan']} 订阅失败（可选）: {e}")
            self.sub_scan = None

        # /plan - Nav2 全局规划路径
        try:
            self.sub_plan = self.create_subscription(
                Path, ROS_TOPICS["plan"], self._on_plan, 10)
            self.get_logger().info(f"  ✅ {ROS_TOPICS['plan']} (nav_msgs/Path) - 全局路径规划")
        except Exception as e:
            self.get_logger().warn(f"  ⚠️ {ROS_TOPICS['plan']} 订阅失败（可选）: {e}")
            self.sub_plan = None

        # /tf - map->odom transform for mapping mode alignment
        try:
            self.sub_tf = self.create_subscription(
                TFMessage, ROS_TOPICS["tf"], self._on_tf, qos_profile_sensor_data)
            self.get_logger().info(f"  [ROS SUB] {ROS_TOPICS['tf']} (tf2_msgs/TFMessage) - map->odom transform")
        except Exception as e:
            self.get_logger().warn(f"  [ROS SUB] {ROS_TOPICS['tf']} optional subscription failed: {e}")
            self.sub_tf = None

        try:
            self.sub_tf_static = self.create_subscription(
                TFMessage,
                ROS_TOPICS["tf_static"],
                lambda msg: self._on_tf(msg, is_static=True),
                qos_profile_sensor_data,
            )
            self.get_logger().info(
                f"  [ROS SUB] {ROS_TOPICS['tf_static']} (tf2_msgs/TFMessage) - static transforms"
            )
        except Exception as e:
            self.get_logger().warn(f"  [ROS SUB] {ROS_TOPICS['tf_static']} optional subscription failed: {e}")
            self.sub_tf_static = None

    def _setup_mqtt_connection(self):
        """设置 MQTT 连接"""
        self.get_logger().info("🔌 [MQTT] 正在连接 MQTT Broker...")
        
        try:
            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            self.client = mqtt.Client()
        
        self.client.on_connect = self._on_mqtt_connect
        self.client.on_message = self._on_mqtt_message
        self.client.on_disconnect = self._on_mqtt_disconnect

        try:
            # 这里的 connect 会阻塞。如果不通，默认会卡很久
            self.get_logger().info(f"  ⏳ 正在向 {self.mqtt_host}:{self.mqtt_port} 发起 socket 连接 (如卡住请检查 Windows 防火墙或 IP 是否互通)...")
            # 缩短 keepalive 只是心跳，真正的连接超时依赖系统的 tcp_syn_retries
            self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self._mqtt_thread = threading.Thread(target=self.client.loop_forever, daemon=True)
            self._mqtt_thread.start()
            self.get_logger().info(f"  ✅ MQTT 连接成功: {self.mqtt_host}:{self.mqtt_port}")
        except Exception as e:
            self.get_logger().error(f"  ❌ MQTT 连接失败: {e}")
            self.stats["errors_count"] += 1

    def _print_subscription_summary(self):
        """打印订阅汇总"""
        self.get_logger().info("-" * 60)
        self.get_logger().info("📋 订阅状态汇总:")
        subscriptions_list = list(self.subscriptions)
        self.get_logger().info(f"   ROS 订阅数量: {len(subscriptions_list)}")
        for i, sub in enumerate(subscriptions_list):
            msg_type = sub.msg_type.__name__ if hasattr(sub.msg_type, '__name__') else str(sub.msg_type)
            self.get_logger().info(f"   [{i+1}] {sub.topic_name} ({msg_type})")
        self.get_logger().info("-" * 60)

    def _print_diagnostics(self):
        """定期打印诊断信息（每 30 秒）"""
        uptime = time.time() - self.start_time
        uptime_str = f"{int(uptime // 60)}m {int(uptime % 60)}s"
        
        self.get_logger().info("=" * 60)
        self.get_logger().info(f"📊 [诊断] 运行时间: {uptime_str}")
        self.get_logger().info("-" * 40)
        
        # ROS 消息统计
        self.get_logger().info("📥 ROS 话题接收统计:")
        self.get_logger().info(f"   /amcl_pose:  {self.stats['ros_amcl_pose_count']:>6} 条  (最后: {self._format_last_time('amcl_pose')})")
        self.get_logger().info(f"   /odom:       {self.stats['ros_odom_count']:>6} 条  (最后: {self._format_last_time('odom')})")
        self.get_logger().info(f"   /odom_raw:   {self.stats['ros_odom_raw_count']:>6} 条  (最后: {self._format_last_time('odom_raw')})")
        self.get_logger().info(f"   /battery:    {self.stats['ros_battery_count']:>6} 条  (最后: {self._format_last_time('battery')})")
        self.get_logger().info(f"   /map:        {self.stats['ros_map_count']:>6} 条  (最后: {self._format_last_time('map')})")
        self.get_logger().info(f"   /scan:       {self.stats['ros_scan_count']:>6} 条  (最后: {self._format_last_time('scan')})")
        
        # MQTT 消息统计
        self.get_logger().info("📤 MQTT 发布统计:")
        self.get_logger().info(f"   robot/pose:   {self.stats['mqtt_pub_pose_count']:>6} 条")
        self.get_logger().info(f"   robot/odom:   {self.stats['mqtt_pub_odom_count']:>6} 条")
        self.get_logger().info(f"   robot/odom_raw:{self.stats['mqtt_pub_odom_raw_count']:>6} 条")
        self.get_logger().info(f"   robot/status: {self.stats['mqtt_pub_status_count']:>6} 条")
        self.get_logger().info(f"   robot/map:    {self.stats['mqtt_pub_map_count']:>6} 条")
        self.get_logger().info(f"   robot/scan:   {self.stats['mqtt_pub_scan_count']:>6} 条")
        
        # MQTT 接收统计
        self.get_logger().info("📥 MQTT 接收统计:")
        self.get_logger().info(f"   robot/goal:         {self.stats['mqtt_recv_goal_count']:>6} 条  (最后: {self._format_last_time('mqtt_goal')})")
        self.get_logger().info(f"   robot/initial_pose: {self.stats['mqtt_recv_initial_pose_count']:>6} 条  (最后: {self._format_last_time('mqtt_initial_pose')})")
        
        # 错误统计
        if self.stats["errors_count"] > 0:
            self.get_logger().warn(f"⚠️ 错误总数: {self.stats['errors_count']}")
        
        # 当前状态
        self.get_logger().info("-" * 40)
        self.get_logger().info("📍 当前状态:")
        self.get_logger().info(f"   电池电压: {self.current_voltage:.2f}V" if self.current_voltage else "   电池电压: 未知")
        with self._odom_lock:
            if self.last_odom_time:
                odom_age = time.time() - self.last_odom_time
                self.get_logger().info(f"   底盘状态: {'🟢 在线' if odom_age < 3.0 else '🔴 离线'} ({odom_age:.1f}s 前)")
            else:
                self.get_logger().info("   底盘状态: 🔴 未收到数据")
        
        self.get_logger().info("=" * 60)

    def _format_last_time(self, key: str) -> str:
        """格式化最后消息时间"""
        t = self.last_msg_time.get(key)
        if t is None:
            return "从未"
        age = time.time() - t
        if age < 60:
            return f"{age:.1f}s 前"
        elif age < 3600:
            return f"{age/60:.1f}m 前"
        else:
            return f"{age/3600:.1f}h 前"

    # ========== MQTT 回调 ==========
    def _on_mqtt_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc, properties=None):
        """MQTT 连接回调"""
        if hasattr(rc, 'value'):
            rc_value = rc.value
        elif hasattr(rc, '__int__'):
            rc_value = int(rc)
        else:
            rc_value = rc
        
        if rc_value != 0:
            self.get_logger().error(f"❌ [MQTT] 连接失败: rc={rc_value}")
            self.stats["errors_count"] += 1
            return
        
        self.get_logger().info("✅ [MQTT] 已连接到 Broker")
        # 订阅来自控制端的消息
        for key in ["goal", "initial_pose", "cmd_vel"]:
            topic = MQTT_TOPICS[key]
            client.subscribe(topic)
            self.get_logger().info(f"  📥 [MQTT SUB] 已订阅: {topic}")

    def _on_mqtt_disconnect(self, client, userdata, rc, properties=None):
        """MQTT 断开回调"""
        self.get_logger().warn(f"⚠️ [MQTT] 连接断开: rc={rc}")
        self.stats["errors_count"] += 1

    def _on_mqtt_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
        """MQTT 消息回调"""
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="ignore")
        
        self.get_logger().info(f"📩 [MQTT RECV] {topic}: {payload[:200]}{'...' if len(payload) > 200 else ''}")
        
        try:
            data = json.loads(payload)
        except Exception as e:
            self.get_logger().warn(f"⚠️ [MQTT] JSON 解析失败 ({topic}): {e}")
            self.stats["errors_count"] += 1
            return

        try:
            if topic == MQTT_TOPICS["goal"]:
                self.stats["mqtt_recv_goal_count"] += 1
                self.last_msg_time["mqtt_goal"] = time.time()
                self._publish_goal(data)
            elif topic == MQTT_TOPICS["initial_pose"]:
                self.stats["mqtt_recv_initial_pose_count"] += 1
                self.last_msg_time["mqtt_initial_pose"] = time.time()
                self._publish_initial_pose(data)
            elif topic == MQTT_TOPICS["cmd_vel"]:
                self._publish_cmd_vel(data)
            else:
                self.get_logger().debug(f"[MQTT] 未处理的话题: {topic}")
        except Exception as e:
            self.get_logger().error(f"❌ [MQTT] 处理消息失败 ({topic}): {e}")
            self.stats["errors_count"] += 1

    # ========== ROS 回调 ==========
    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped):
        """处理 AMCL 位姿"""
        self.stats["ros_amcl_pose_count"] += 1
        self.last_msg_time["amcl_pose"] = time.time()
        
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)
        yaw_deg = math.degrees(yaw)
        
        self.get_logger().info(f"📍 [ROS] {ROS_TOPICS['amcl_pose']}: x={p.x:.3f}, y={p.y:.3f}, yaw={yaw_deg:.1f}°")
        
        payload = {"x": p.x, "y": p.y, "z": p.z, "yaw": yaw, "timestamp": time.time()}
        try:
            self.client.publish(MQTT_TOPICS["pose"], json.dumps(payload, ensure_ascii=False))
            self.stats["mqtt_pub_pose_count"] += 1
            self.get_logger().debug(f"📤 [MQTT PUB] {MQTT_TOPICS['pose']}: {payload}")
        except Exception as e:
            self.get_logger().error(f"❌ 发布 {MQTT_TOPICS['pose']} 失败: {e}")
            self.stats["errors_count"] += 1

    def _publish_odometry(
        self,
        msg: Odometry,
        *,
        ros_topic_key: str,
        mqtt_topic_key: str,
        ros_count_key: str,
        mqtt_count_key: str,
        last_msg_key: str,
        source: str,
        update_health: bool,
    ):
        self.stats[ros_count_key] += 1
        self.last_msg_time[last_msg_key] = time.time()

        if update_health:
            with self._odom_lock:
                self.last_odom_time = time.time()

        try:
            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)
            payload = {
                "x": p.x,
                "y": p.y,
                "z": p.z,
                "yaw": yaw,
                "source": source,
                "child_frame_id": str(getattr(msg, "child_frame_id", "")).lstrip("/"),
                "timestamp": time.time(),
            }
            self.client.publish(MQTT_TOPICS[mqtt_topic_key], json.dumps(payload, ensure_ascii=False))
            self.stats[mqtt_count_key] += 1

            if self.stats[ros_count_key] % 100 == 0:
                yaw_deg = math.degrees(yaw)
                self.get_logger().info(
                    f"📍 [ROS] {ROS_TOPICS[ros_topic_key]} (每100条): "
                    f"x={p.x:.3f}, y={p.y:.3f}, yaw={yaw_deg:.1f}°"
                )
        except Exception:
            self.stats["errors_count"] += 1

    def _on_odom(self, msg: Odometry):
        """处理融合里程计"""
        self._publish_odometry(
            msg,
            ros_topic_key="odom",
            mqtt_topic_key="odom",
            ros_count_key="ros_odom_count",
            mqtt_count_key="mqtt_pub_odom_count",
            last_msg_key="odom",
            source="odom",
            update_health=True,
        )

    def _on_odom_raw(self, msg: Odometry):
        """处理原始里程计"""
        self._publish_odometry(
            msg,
            ros_topic_key="odom_raw",
            mqtt_topic_key="odom_raw",
            ros_count_key="ros_odom_raw_count",
            mqtt_count_key="mqtt_pub_odom_raw_count",
            last_msg_key="odom_raw",
            source="odom_raw",
            update_health=True,
        )

    def _on_tf(self, msg: TFMessage, is_static: bool = False):
        self.stats["ros_tf_count"] += 1
        self.last_msg_time["tf"] = time.time()

        for transform_stamped in getattr(msg, "transforms", []):
            parent = str(transform_stamped.header.frame_id).lstrip("/")
            child = str(transform_stamped.child_frame_id).lstrip("/")
            if not parent or not child:
                continue

            transform = transform_stamped.transform
            translation = transform.translation
            rotation = transform.rotation
            yaw = yaw_from_quaternion(rotation.x, rotation.y, rotation.z, rotation.w)
            payload = {
                "parent": parent,
                "child": child,
                "x": translation.x,
                "y": translation.y,
                "yaw": yaw,
                "static": bool(is_static),
                "timestamp": time.time(),
            }

            try:
                self.client.publish(MQTT_TOPICS["tf"], json.dumps(payload, ensure_ascii=False))
                self.stats["mqtt_pub_tf_count"] += 1
            except Exception as e:
                self.get_logger().warn(f"[MQTT] failed to publish {MQTT_TOPICS['tf']}: {e}")
                self.stats["errors_count"] += 1

    def _on_battery_uint16(self, msg: UInt16):
        """处理电池电压"""
        self.stats["ros_battery_count"] += 1
        self.last_msg_time["battery"] = time.time()
        
        try:
            raw_value = int(msg.data)
            
            # 电压转换逻辑
            if raw_value > 10000:
                voltage = float(raw_value) / 1000.0
            elif raw_value > 100:
                voltage = float(raw_value) / 100.0
            else:
                if raw_value < 10:
                    voltage = float(raw_value)
                else:
                    voltage = float(raw_value) / 10.0
            
            self.current_voltage = voltage
            try:
                self.client.publish(MQTT_TOPICS["voltage"], f"{voltage:.3f}")
            except Exception as pub_exc:
                self.get_logger().warn(f"⚠️ 发布电池电压失败: {pub_exc}")
                self.stats["errors_count"] += 1
            self.get_logger().info(f"🔋 [ROS] /battery: raw={raw_value}, voltage={voltage:.2f}V")
        except Exception as e:
            self.get_logger().warn(f"⚠️ 解析电池电压失败: {e}")
            self.stats["errors_count"] += 1

    def _on_map(self, msg: OccupancyGrid):
        """处理地图数据"""
        self.stats["ros_map_count"] += 1
        self.last_msg_time["map"] = time.time()
        current_time = time.time()
        
        # 第一次收到地图
        if self.stats["ros_map_count"] == 1:
            self.get_logger().info(f"🗺️ [ROS] 首次收到 {ROS_TOPICS['map']}: {msg.info.width}x{msg.info.height}, "
                                   f"resolution={msg.info.resolution:.3f}m/px")
        
        try:
            width = msg.info.width
            height = msg.info.height
            resolution = msg.info.resolution
            origin_x = msg.info.origin.position.x
            origin_y = msg.info.origin.position.y
            origin_q = msg.info.origin.orientation
            origin_yaw = yaw_from_quaternion(origin_q.x, origin_q.y, origin_q.z, origin_q.w)
            free_count = sum(1 for x in msg.data if 0 <= x <= 25)
            occupied_count = sum(1 for x in msg.data if 65 <= x <= 100)
            unknown_count = sum(1 for x in msg.data if x < 0)
            
            # 转换数据
            map_data = bytes([(x if x >= 0 else 255) for x in msg.data])
            compressed = zlib.compress(map_data, level=self.map_compression_level)
            data_b64 = base64.b64encode(compressed).decode('ascii')
            
            payload = {
                "width": width,
                "height": height,
                "resolution": resolution,
                "origin_x": origin_x,
                "origin_y": origin_y,
                "origin_yaw": origin_yaw,
                "data": data_b64,
                "compressed": True,
                "timestamp": current_time
            }
            
            self.client.publish(MQTT_TOPICS["map"], json.dumps(payload, ensure_ascii=False))
            self.stats["mqtt_pub_map_count"] += 1
            
            original_size = len(msg.data)
            compressed_size = len(compressed)
            ratio = compressed_size / original_size * 100 if original_size > 0 else 0
            
            self.get_logger().info(
                f"🗺️ [MQTT PUB] {MQTT_TOPICS['map']}: {width}x{height}, "
                f"origin=({origin_x:.2f}, {origin_y:.2f}, {origin_yaw:.2f}), "
                f"free={free_count}, occupied={occupied_count}, unknown={unknown_count}, "
                f"压缩: {original_size} -> {compressed_size} bytes ({ratio:.1f}%)"
            )
        except Exception as e:
            self.get_logger().error(f"❌ 发布地图失败: {e}")
            self.stats["errors_count"] += 1

    def _on_scan(self, msg: LaserScan):
        """处理激光雷达数据"""
        self.stats["ros_scan_count"] += 1
        self.last_msg_time["scan"] = time.time()
        current_time = time.time()
        
        try:
            ranges = list(msg.ranges)
            
            payload = {
                "frame_id": str(msg.header.frame_id).lstrip("/"),
                "angle_min": msg.angle_min,
                "angle_max": msg.angle_max,
                "angle_increment": msg.angle_increment,
                "range_min": msg.range_min,
                "range_max": msg.range_max,
                "ranges": ranges,
                "timestamp": current_time,
            }
            
            self.client.publish(MQTT_TOPICS["scan"], json.dumps(payload, ensure_ascii=False))
            self.stats["mqtt_pub_scan_count"] += 1
            self.get_logger().debug(f"📡 [MQTT PUB] {MQTT_TOPICS['scan']}: {len(ranges)} points")
        except Exception as e:
            self.get_logger().warn(f"⚠️ 发布激光数据失败: {e}")
            self.stats["errors_count"] += 1

    def _on_plan(self, msg):
        """处理 Nav2 全局路径规划"""
        self.last_msg_time["plan"] = time.time()

        poses = msg.poses
        if not poses:
            return

        total = len(poses)
        path_points = [
            {"x": round(p.pose.position.x, 3), "y": round(p.pose.position.y, 3)}
            for p in poses
        ]

        try:
            self.client.publish(MQTT_TOPICS["path"], json.dumps(path_points, ensure_ascii=False))
            self.get_logger().info(f"🛤️ [MQTT PUB] {MQTT_TOPICS['path']}: {len(path_points)} points (原始 {total})")
        except Exception as e:
            self.get_logger().warn(f"⚠️ 发布路径数据失败: {e}")
            self.stats["errors_count"] += 1

    def _publish_status_heartbeat(self):
        """定期发布状态心跳"""
        current_time = time.time()
        
        with self._odom_lock:
            if self.last_odom_time is None:
                is_alive = False
                odom_age = -1
            else:
                odom_age = current_time - self.last_odom_time
                is_alive = odom_age < 3.0
        
        status = {
            "chassis_alive": is_alive,
            "voltage": self.current_voltage if self.current_voltage is not None else None,
            "timestamp": current_time,
        }
        
        try:
            status_json = json.dumps(status, ensure_ascii=False)
            self.client.publish(MQTT_TOPICS["status"], status_json)
            self.stats["mqtt_pub_status_count"] += 1
            
            # 每 10 秒打印一次详细状态
            if int(current_time) % 10 == 0:
                voltage_str = f"{self.current_voltage:.2f}V" if self.current_voltage else "N/A"
                self.get_logger().info(
                    f"💓 [MQTT PUB] {MQTT_TOPICS['status']}: alive={is_alive}, voltage={voltage_str}, "
                    f"odom_age={odom_age:.1f}s"
                )
        except Exception as e:
            self.get_logger().error(f"❌ 发布状态失败: {e}")
            self.stats["errors_count"] += 1

    def _publish_cmd_vel(self, data: Dict[str, Any]):
        """发布 Twist 指令到 ROS"""
        try:
            msg = Twist()
            msg.linear.x = float(data.get("linear", {}).get("x", 0.0))
            msg.linear.y = float(data.get("linear", {}).get("y", 0.0))
            msg.linear.z = float(data.get("linear", {}).get("z", 0.0))
            msg.angular.x = float(data.get("angular", {}).get("x", 0.0))
            msg.angular.y = float(data.get("angular", {}).get("y", 0.0))
            msg.angular.z = float(data.get("angular", {}).get("z", 0.0))
            self.pub_cmd_vel.publish(msg)
        except Exception as e:
            self.get_logger().error(f"❌ 解析/发布 cmd_vel 失败: {e}")
            self.stats["errors_count"] += 1

    # ========== ROS 发布方法 ==========
    def _publish_goal(self, data: Dict[str, Any]):
        """发布导航目标点"""
        x = float(data.get("x", 0.0))
        y = float(data.get("y", 0.0))
        yaw = float(data.get("yaw", 0.0))

        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = "map"
        pose.pose.position.x = x
        pose.pose.position.y = y
        q = quaternion_from_yaw(yaw)
        pose.pose.orientation.x = q["x"]
        pose.pose.orientation.y = q["y"]
        pose.pose.orientation.z = q["z"]
        pose.pose.orientation.w = q["w"]
        
        self.pub_goal.publish(pose)
        yaw_deg = math.degrees(yaw)
        self.get_logger().info(f"🎯 [ROS PUB] {ROS_TOPICS['goal']}: x={x:.3f}, y={y:.3f}, yaw={yaw_deg:.1f}°")

    def _publish_initial_pose(self, data: Dict[str, Any]):
        """发布初始位姿"""
        x = float(data.get("x", 0.0))
        y = float(data.get("y", 0.0))
        yaw = float(data.get("yaw", 0.0))
        cov = data.get("covariance", None)

        msg = PoseWithCovarianceStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        q = quaternion_from_yaw(yaw)
        msg.pose.pose.orientation.z = q["z"]
        msg.pose.pose.orientation.w = q["w"]

        if isinstance(cov, list) and len(cov) == 36:
            try:
                msg.pose.covariance = [float(v) for v in cov]
            except Exception:
                pass

        self.pub_initialpose.publish(msg)
        yaw_deg = math.degrees(yaw)
        self.get_logger().info(f"📍 [ROS PUB] {ROS_TOPICS['initialpose']}: x={x:.3f}, y={y:.3f}, yaw={yaw_deg:.1f}°")


def main():
    if rclpy is None:
        raise RuntimeError("缺少 ROS2 Python 依赖。请在 ROS2 容器内运行该脚本。")
    
    mqtt_host = os.getenv("MQTT_HOST")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    if not mqtt_host:
        raise RuntimeError("MQTT_HOST 环境变量未设置")

    domain_id = os.getenv("ROS_DOMAIN_ID", "20")
    os.environ["ROS_DOMAIN_ID"] = domain_id
    
    print("=" * 60, flush=True)
    print(f"🚀 MQTT Bridge 启动", flush=True)
    print(f"   MQTT_HOST: {mqtt_host}", flush=True)
    print(f"   MQTT_PORT: {mqtt_port}", flush=True)
    print(f"   ROS_DOMAIN_ID: {domain_id}", flush=True)
    print("=" * 60, flush=True)
    
    rclpy.init()
    node = Ros2MqttBridge(mqtt_host=mqtt_host, mqtt_port=mqtt_port)
    
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        print("\n⚠️ 收到中断信号，正在关闭...", flush=True)
    except ExternalShutdownException:
        pass
    finally:
        try:
            executor.remove_node(node)
        except Exception:
            pass
        try:
            node.client.disconnect()
        except Exception:
            pass
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass
        print("✅ Bridge 已关闭", flush=True)


if __name__ == "__main__":
    main()
