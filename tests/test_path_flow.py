"""
集成测试：验证全局路径规划的数据流
MqttAgent -> MainWindow -> MapLabel
"""
import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock QApplication for Qt elements
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from src.network.mqtt_agent import MqttAgent
from src.ui.main_window import MyMainWindow
from src.ui.views import MapLabel

def test_path_data_propagation():
    # 1. Mock MqttAgent and its client
    mqtt_agent = MqttAgent()
    mqtt_agent.client = MagicMock()
    
    # 2. Instantiate MyMainWindow with the mocked agent
    # We use a partial mock or just check the internal label
    with patch('src.ui.main_window.AsyncSSHManager'), \
         patch('src.ui.main_window.WorkflowController'), \
         patch('src.ui.main_window.UIManager'):
        
        window = MyMainWindow(mqtt_agent=mqtt_agent)
        
        # Mock the MapLabel inside window.ui
        window.ui.map_label = MagicMock(spec=MapLabel)
        
        # 3. Simulate receiving a path message
        test_path = [
            {"x": 1.0, "y": 2.0},
            {"x": 1.5, "y": 2.5},
            {"x": 2.0, "y": 3.0}
        ]
        payload = json.dumps(test_path).encode('utf-8')
        
        # Simulate MQTT callback on robot/path topic
        class MockMsg:
            def __init__(self, topic, payload):
                self.topic = topic
                self.payload = payload
        
        msg = MockMsg("robot/path", payload)
        
        # Directly call the internal callback
        mqtt_agent.on_message(None, None, msg)
        
        # 4. Verify propagation
        # MqttAgent should emit path_updated
        # MyMainWindow should have its update_global_path called (via signal)
        # MapLabel should have set_path_data called with the test_path
        
        # Since signals are asynchronous in Qt, we might need to process events
        QApplication.processEvents()
        
        window.ui.map_label.set_path_data.assert_called_once_with(test_path)
        print("\n✅ Verification Successful: Path data propagated from MQTT to MapLabel.")

if __name__ == "__main__":
    test_path_data_propagation()
