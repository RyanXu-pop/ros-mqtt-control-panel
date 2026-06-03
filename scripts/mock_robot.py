import paho.mqtt.client as mqtt
import time
import json
import math
import threading

# ======== 配置区 ========
BROKER_IP = "127.0.0.1"
BROKER_PORT = 1883

# 话题定义 (需要和 config.yaml 中保持一致)
TOPICS = {
    "status": "robot/status",
    "pose": "robot/pose",
    "odom": "robot/odom",
    "goal": "robot/goal",
    "initial_pose": "robot/initial_pose"
}

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[MockRobot] 已连接到 MQTT Broker: {BROKER_IP}")
    # 订阅客户端下发的控制指令
    client.subscribe(TOPICS["goal"])
    client.subscribe(TOPICS["initial_pose"])
    print(f"[MockRobot] 已订阅控制话题: {TOPICS['goal']} 和 {TOPICS['initial_pose']}")

# 状态变量
current_x = 0.0
current_y = 0.0
current_angle = 0.0

goal_x = 0.0
goal_y = 0.0
goal_angle = 0.0
is_moving = False

# 锁，保护状态修改
state_lock = threading.Lock()

def on_message(client, userdata, msg):
    global current_x, current_y, current_angle, goal_x, goal_y, goal_angle, is_moving
    payload = msg.payload.decode('utf-8')
    print(f"\n[MockRobot] 收到客户端发来的指令:")
    print(f"  -> 话题: {msg.topic}")
    print(f"  -> 内容: {payload}")
    
    try:
        data = json.loads(payload)
    except Exception as e:
        print(f"[MockRobot] 解析 JSON 失败: {e}")
        return

    with state_lock:
        if msg.topic == TOPICS["initial_pose"]:
            # 重置初始位置
            current_x = float(data.get("x", current_x))
            current_y = float(data.get("y", current_y))
            # 兼容 yaw 或 angle 键名
            if "yaw" in data:
                current_angle = float(data["yaw"])
            else:
                current_angle = float(data.get("angle", current_angle))
                
            is_moving = False # 停止当前移动
            print(f"[MockRobot] 已根据 initial_pose 重置位置: x={current_x:.2f}, y={current_y:.2f}, angle={current_angle:.2f}")

        elif msg.topic == TOPICS["goal"]:
            # 设置新目标开启移动
            goal_x = float(data.get("x", current_x))
            goal_y = float(data.get("y", current_y))
            if "yaw" in data:
                goal_angle = float(data["yaw"])
            else:
                goal_angle = float(data.get("angle", current_angle))
            is_moving = True
            print(f"[MockRobot] 收到新目标 -> x={goal_x:.2f}, y={goal_y:.2f}, yaw={math.degrees(goal_angle):.1f}°")


def publish_telemetry():
    """后台线程：定时发布状态和位姿，让客户端 UI 动起来"""
    global current_x, current_y, current_angle, is_moving
    
    t = 0
    step = 0.1 # 每次循环移动的距离
    
    while True:
        # 1. 模拟底盘状态与电池电压 (每1秒发一次)
        t += 1
        if t % 10 == 0:
            status_msg = {
                "chassis_alive": True,
                "voltage": 12.0 + math.sin(t/10.0) * 0.5  # 电压在 11.5~12.5 之间波动
            }
            client.publish(TOPICS["status"], json.dumps(status_msg))

        # 2. 计算向目标移动的逻辑
        with state_lock:
            if is_moving:
                dx = goal_x - current_x
                dy = goal_y - current_y
                dist = math.hypot(dx, dy)
                
                if dist < step:
                    # 已经到达目标，应用用户指定的目标角度
                    current_x = goal_x
                    current_y = goal_y
                    current_angle = goal_angle  # 使用用户指定的目标朝向
                    is_moving = False
                    print(f"[MockRobot] 已到达目标！最终朝向: {math.degrees(current_angle):.1f}°")
                else:
                    # 朝目标方向移动一小步
                    move_angle = math.atan2(dy, dx)
                    current_x += math.cos(move_angle) * step
                    current_y += math.sin(move_angle) * step
                    current_angle = move_angle # 移动过程中朝向运动方向

            # 发送当前最新的 amcl_pose
            pose_msg = {
                "x": current_x,
                "y": current_y,
                "yaw": current_angle,
                "angle": current_angle # 均返回弧度
            }
            
            # 使用 try-except 防止因为没有连接等问题报错
            try:
                client.publish(TOPICS["pose"], json.dumps(pose_msg))
            except Exception:
                pass

        time.sleep(0.1)

client.on_connect = on_connect
client.on_message = on_message

print(f"[MockRobot] 准备模拟小车启动...")
try:
    client.connect(BROKER_IP, BROKER_PORT, 60)
except Exception as e:
    print(f"[MockRobot] 连接Broker失败: {e}")
    exit(1)

# 开启后台遥测发布线程
telemetry_thread = threading.Thread(target=publish_telemetry, daemon=True)
telemetry_thread.start()

print("[MockRobot] 小车模拟器正在运行，按 Ctrl+C 停止")
client.loop_forever()
