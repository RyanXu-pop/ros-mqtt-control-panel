import json, paho.mqtt.client as mqtt

def on_message(c, u, m):
    data = json.loads(m.payload)
    print(f"Got scan: len={len(data.get('ranges', []))} min={data.get('angle_min')} max={data.get('angle_max')} inc={data.get('angle_increment')}")
    c.disconnect()

c = mqtt.Client()
c.on_message = on_message
c.connect("127.0.0.1")
c.subscribe("robot/scan")
c.loop_forever()
