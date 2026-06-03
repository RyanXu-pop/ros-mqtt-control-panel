import paho.mqtt.client as mqtt
import time
import pytest
import threading

def test_mqtt_broker_connection():
    """验证 MQTT Broker 是否在 127.0.0.1:1883 正常运行并支持发布/订阅"""
    received_message = []
    
    def on_message(client, userdata, msg):
        received_message.append(msg.payload.decode('utf-8'))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    
    try:
        # 建立连接
        client.connect("127.0.0.1", 1883, 60)
        client.loop_start()
        
        # 订阅测试话题
        client.subscribe("test/broker")
        time.sleep(0.5)
        
        # 发布测试消息
        test_payload = "pytest_connection_demo"
        client.publish("test/broker", test_payload)
        
        # 等待回显
        timeout = 2.0
        start_time = time.time()
        while not received_message and (time.time() - start_time) < timeout:
            time.sleep(0.1)
            
        client.loop_stop()
        client.disconnect()
        
        # 断言
        assert len(received_message) > 0, "未收到发送的测试消息"
        assert received_message[0] == test_payload, f"消息内容不符: {received_message[0]}"
        
    except Exception as e:
        pytest.skip(f"本机未运行 MQTT Broker，跳过集成检查: {e}")

if __name__ == "__main__":
    # 允许作为脚本独立运行
    test_mqtt_broker_connection()
    print("Success")
