#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mock_lidar.py

用于在没有真实机器人的情况下，向本地 MQTT Broker 发送伪造的 robot/scan 激光雷达数据。
运行此脚本后，ROS 控制面板的主界面上小车周围应该会出现红色的激光雷达点阵（呈现一个圆形房间的轮廓）。
"""

import paho.mqtt.client as mqtt
import json
import time
import math
import random
import threading

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
TOPIC_SCAN = "robot/scan"

class MockLidar:
    def __init__(self):
        self.client = mqtt.Client()
        self.running = False
        
        # 激光雷达参数 (模拟 360 度，1 度 1 个点，共 360 个点)
        self.angle_min = -math.pi
        self.angle_max = math.pi
        self.angle_increment = (self.angle_max - self.angle_min) / 360.0
        
        # 虚拟房间环境参数 (模拟小车在一个 5x5 米的房间中心)
        self.room_radius = 2.5
        
    def connect(self):
        try:
            self.client.connect(MQTT_HOST, MQTT_PORT, 60)
            self.client.loop_start()
            print(f"[Mock LiDAR] 成功连接到 MQTT Broker ({MQTT_HOST}:{MQTT_PORT})")
            return True
        except Exception as e:
            print(f"[Mock LiDAR] 连接失败: {e}")
            return False

    def generate_fake_scan(self):
        """生成一帧假的雷达扫描数据 (一个带有随机噪点的圆形轮廓，前方有一个虚拟障碍物)"""
        ranges = []
        
        # 当前的时间用于制造动态的“虚拟行人”
        t = time.time()
        dynamic_obstacle_angle = (t * 0.5) % (2 * math.pi) - math.pi
        
        for i in range(360):
            current_angle = self.angle_min + i * self.angle_increment
            
            # 基础距离：圆形房间半径 2.5m + 一点点传感器噪声
            dist = self.room_radius + random.uniform(-0.05, 0.05)
            
            # 在前方 (-15度 到 15度) 模拟一堵墙，距离 1.2 米
            if -min(0.26, abs(current_angle)) < current_angle < min(0.26, abs(current_angle)):
                dist = 1.2 + random.uniform(-0.02, 0.02)
                
            # 模拟一个绕着小车转圈的动态障碍物 (距离 1.5 米, 宽度约 10 度)
            if abs(current_angle - dynamic_obstacle_angle) < 0.1:
                dist = 1.5 + random.uniform(-0.01, 0.01)
                
            # 模拟偶尔雷达丢失数据 (吸光材质等) 设为无穷大
            if random.random() < 0.02:
                dist = float('inf')
                
            ranges.append(dist)
            
        return {
            "angle_min": self.angle_min,
            "angle_max": self.angle_max,
            "angle_increment": self.angle_increment,
            "ranges": ranges
        }

    def run(self):
        if not self.connect():
            return
            
        self.running = True
        print(f"[Mock LiDAR] 开始发布虚拟激光雷达数据 (Topic: {TOPIC_SCAN}) ...")
        
        try:
            while self.running:
                scan_data = self.generate_fake_scan()
                self.client.publish(TOPIC_SCAN, json.dumps(scan_data))
                time.sleep(0.1)  # 10Hz 频率发布
        except KeyboardInterrupt:
            print("\n[Mock LiDAR] 停止发布。")
        finally:
            self.running = False
            self.client.disconnect()


if __name__ == "__main__":
    mock = MockLidar()
    mock.run()
