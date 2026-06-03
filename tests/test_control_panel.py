import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ui_v2.panels.control_panel import ControlPanel
from src.ui_v2.robot_state_hub import RobotStateHub
from src.core.models import MapMetadata


def test_navigation_busy_starting_updates_button(qapp):
    store = RobotStateHub()
    panel = ControlPanel(store)

    store.set_navigation_busy(True, "starting")

    assert panel.btn_toggle_navigation.text() == "启动中..."
    assert not panel.btn_toggle_navigation.isEnabled()


def test_navigation_busy_stop_success_restores_idle_state(qapp):
    store = RobotStateHub()
    panel = ControlPanel(store)

    store.set_chassis_running(True)
    store.set_mqtt_running(True)
    store.update_map(MapMetadata(width=10, height=10, data=[[0]]))
    store.set_navigation_running(True)
    store.set_navigation_busy(True, "stopping")
    assert panel.btn_toggle_navigation.text() == "停止中..."

    store.set_navigation_running(False)
    store.set_navigation_busy(False)

    assert panel.btn_toggle_navigation.text() == "启动导航"
    assert panel.btn_toggle_navigation.isEnabled()


def test_primary_action_follows_startup_sequence(qapp):
    store = RobotStateHub()
    panel = ControlPanel(store)

    assert panel.btn_primary_action.text() == "启动底盘"

    store.set_chassis_running(True)
    assert panel.btn_primary_action.text() == "启动 MQTT 节点"

    store.set_mqtt_running(True)
    assert panel.btn_primary_action.text() == "开始建图"

    store.update_map(MapMetadata(width=10, height=10, data=[[0]]))
    assert panel.btn_primary_action.text() == "启动导航"


def test_disabled_navigation_shows_dependency_reason(qapp):
    store = RobotStateHub()
    panel = ControlPanel(store)

    assert not panel.btn_toggle_navigation.isEnabled()
    assert panel.navigation_hint.text() == "需先启动底盘"

    store.set_chassis_running(True)
    assert panel.navigation_hint.text() == "需先启动 MQTT 节点"
