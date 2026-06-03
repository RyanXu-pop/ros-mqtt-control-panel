"""
Simulate a Nav2 path message.
Run this while the application is running to see the green path on the map.
"""
import paho.mqtt.client as mqtt
import json
import time

def simulate_path():
    client = mqtt.Client()
    try:
        # Use localhost as configured in config.yaml
        client.connect("127.0.0.1", 1883, 60)
        client.loop_start()
        
        # A simple zigzag path
        path = [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.5},
            {"x": 2.0, "y": -0.5},
            {"x": 3.0, "y": 0.8},
            {"x": 4.0, "y": 0.0},
            {"x": 5.0, "y": 1.0},
        ]
        
        print(f"Sending test path to robot/path...")
        client.publish("robot/path", json.dumps(path))
        
        time.sleep(1)
        client.loop_stop()
        client.disconnect()
        print("Done. If the app is open and connected to 127.0.0.1, you should see a green path.")
    except Exception as e:
        print(f"Failed to connect to MQTT broker: {e}")
        print("Make sure an MQTT broker (like Mosquitto) is running on 127.0.0.1:1883")

if __name__ == "__main__":
    simulate_path()
