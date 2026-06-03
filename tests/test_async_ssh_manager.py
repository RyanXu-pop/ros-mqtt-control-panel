import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.network.async_ssh_manager import AsyncSSHManager


def test_graceful_stop_process_group_stops_on_sigint(monkeypatch):
    mgr = AsyncSSHManager()
    signals = []
    results = iter([False, True])

    async def fake_signal(patterns, signal_name):
        signals.append(signal_name)

    async def fake_verify(timeout_s):
        return next(results)

    monkeypatch.setattr(mgr, "_signal_process_patterns_async", fake_signal)

    stopped = asyncio.run(mgr._graceful_stop_process_group_async(("demo",), fake_verify, "demo"))

    assert stopped is True
    assert signals == ["SIGINT"]


def test_graceful_stop_process_group_returns_false_when_sigint_does_not_stop(monkeypatch):
    mgr = AsyncSSHManager()
    signals = []

    async def fake_signal(patterns, signal_name):
        signals.append(signal_name)

    async def fake_verify(timeout_s):
        return False

    monkeypatch.setattr(mgr, "_signal_process_patterns_async", fake_signal)

    stopped = asyncio.run(mgr._graceful_stop_process_group_async(("demo",), fake_verify, "demo"))

    assert stopped is False
    assert signals == ["SIGINT"]


def test_stop_navigation_mode_orders_zero_then_nav(monkeypatch):
    mgr = AsyncSSHManager()
    mgr.ssh_client = object()
    calls = []

    async def fake_connect():
        return None

    async def fake_zero():
        calls.append("zero")
        return True

    async def fake_stop_group(patterns, verify_fn, label, session_name=None):
        calls.append(label)
        return True

    async def fake_clear(session_name):
        calls.append(f"clear:{session_name}")

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_publish_zero_cmd_vel_async", fake_zero)
    monkeypatch.setattr(mgr, "_graceful_stop_process_group_async", fake_stop_group)
    monkeypatch.setattr(mgr, "_clear_launch_session_state_async", fake_clear)

    success, msg = asyncio.run(mgr.stop_navigation_mode_async())

    assert success is True
    assert "导航已关闭" in msg
    assert calls == ["zero", "Navigation2", "clear:navigation"]


def test_stop_navigation_mode_fails_when_navigation_does_not_stop(monkeypatch):
    mgr = AsyncSSHManager()
    mgr.ssh_client = object()

    async def fake_connect():
        return None

    async def fake_zero():
        return True

    async def fake_stop_group(patterns, verify_fn, label, session_name=None):
        return False

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_publish_zero_cmd_vel_async", fake_zero)
    monkeypatch.setattr(mgr, "_graceful_stop_process_group_async", fake_stop_group)

    success, msg = asyncio.run(mgr.stop_navigation_mode_async())

    assert success is False
    assert "导航进程" in msg


def test_start_navigation_amcl_check_uses_shell_timeout(monkeypatch):
    mgr = AsyncSSHManager()
    mgr.ssh_client = object()
    commands = []

    async def fake_connect():
        return None

    async def fake_exec(command, detach=False, timeout=20):
        commands.append(command)
        if "pgrep -f '[y]ahboomcar_bringup_launch.py'" in command:
            return 0, "123\n", ""
        if "test -f /root/yahboomcar_ws/src/yahboomcar_nav/maps/yahboom_map.yaml" in command:
            return 0, "MAP_EXISTS\n", ""
        if "pkill -f navigation_dwb_launch.py" in command:
            return 0, "", ""
        if "pkill -f nav2_bringup" in command:
            return 0, "", ""
        if "ros2 node list" in command:
            return 0, "/amcl\n/controller_server\n/planner_server\n", ""
        if "timeout 5 ros2 lifecycle get /amcl" in command:
            return 0, "AMCL_ACTIVE\n", ""
        raise AssertionError(f"unexpected command: {command}")

    async def fake_clear(_session_name):
        return None

    async def fake_start_tracked(session_name, launch_command):
        commands.append(f"{session_name}:{launch_command}")
        return True, "/root/navigation.log"

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_exec_in_container_async", fake_exec)
    monkeypatch.setattr(mgr, "_clear_launch_session_state_async", fake_clear)
    monkeypatch.setattr(mgr, "_start_tracked_launch_async", fake_start_tracked)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    success, msg = asyncio.run(mgr.start_navigation_async())

    assert success is True
    assert "Navigation2" in msg
    assert any("navigation:ros2 launch yahboomcar_nav navigation_dwb_launch.py" in cmd for cmd in commands)
    assert any("timeout 5 ros2 lifecycle get /amcl" in cmd for cmd in commands)


def test_start_chassis_uses_detached_compat_launch(monkeypatch):
    mgr = AsyncSSHManager()
    mgr.ssh_client = object()
    commands = []

    async def fake_connect():
        return None

    async def fake_clear(_session_name):
        commands.append("clear:chassis")

    async def fake_exec(command, detach=False, timeout=20):
        commands.append(command)
        if "pkill -f yahboomcar_bringup_launch.py" in command:
            return 0, "", ""
        if "rm -f /root/bringup.log" in command:
            return 0, "", ""
        if "nohup bash -lc 'ros2 launch yahboomcar_bringup yahboomcar_bringup_launch.py'" in command:
            return 0, "", ""
        if "pgrep -f yahboomcar_bringup_launch.py" in command:
            return 0, "123\n", ""
        raise AssertionError(f"unexpected command: {command}")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_clear_launch_session_state_async", fake_clear)
    monkeypatch.setattr(mgr, "_exec_in_container_async", fake_exec)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    success, msg = asyncio.run(mgr.start_chassis_async())

    assert success is True
    assert "底盘启动成功" in msg
    assert any("nohup bash -lc 'ros2 launch yahboomcar_bringup yahboomcar_bringup_launch.py'" in cmd for cmd in commands)


def test_start_chassis_returns_bringup_log_when_process_missing(monkeypatch):
    from src.network import ros_services_mixin

    mgr = AsyncSSHManager()
    mgr.ssh_client = object()
    times = iter([0, 0, 1, 2, 3, 4, 5, 6, 7, 8.5])

    async def fake_connect():
        return None

    async def fake_clear(_session_name):
        return None

    async def fake_exec(command, detach=False, timeout=20):
        if "pkill -f yahboomcar_bringup_launch.py" in command:
            return 0, "", ""
        if "rm -f /root/bringup.log" in command:
            return 0, "", ""
        if "nohup bash -lc 'ros2 launch yahboomcar_bringup yahboomcar_bringup_launch.py'" in command:
            return 0, "", ""
        if "pgrep -f yahboomcar_bringup_launch.py" in command:
            return 0, "", ""
        if "tail -n 80 /root/bringup.log" in command:
            return 0, "bringup error detail\n", ""
        raise AssertionError(f"unexpected command: {command}")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_clear_launch_session_state_async", fake_clear)
    monkeypatch.setattr(mgr, "_exec_in_container_async", fake_exec)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(ros_services_mixin.time, "monotonic", lambda: next(times))

    success, msg = asyncio.run(mgr.start_chassis_async())

    assert success is False
    assert "底盘进程未检测到" in msg
    assert "bringup error detail" in msg


def test_start_gmapping_only_launches_remote_robot_mapping(monkeypatch):
    mgr = AsyncSSHManager()
    mgr.ssh_client = object()
    commands = []

    async def fake_connect():
        return None

    async def fake_exec(command, detach=False, timeout=20):
        commands.append(command)
        if "pgrep -f '[y]ahboomcar_bringup_launch.py'" in command:
            return 0, "123\n", ""
        if "pkill -f map_gmapping_launch.py" in command:
            return 0, "", ""
        if "pkill -f slam_gmapping" in command:
            return 0, "", ""
        if "ros2 topic list" in command:
            return 0, "/map\n", ""
        raise AssertionError(f"unexpected command: {command}")

    async def fake_clear(_session_name):
        return None

    async def fake_start_tracked(session_name, launch_command):
        commands.append(f"{session_name}:{launch_command}")
        return True, "/root/gmapping.log"

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_exec_in_container_async", fake_exec)
    monkeypatch.setattr(mgr, "_clear_launch_session_state_async", fake_clear)
    monkeypatch.setattr(mgr, "_start_tracked_launch_async", fake_start_tracked)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    success, msg = asyncio.run(mgr.start_gmapping_async())

    assert success is True
    assert "Gmapping" in msg
    assert any("gmapping:ros2 launch yahboomcar_nav map_gmapping_launch.py" in cmd for cmd in commands)


def test_start_mqtt_bridge_exports_odom_topics_from_config(monkeypatch):
    mgr = AsyncSSHManager()
    uploaded = {}

    class FakeRemoteFile:
        def __init__(self, store, path):
            self.store = store
            self.path = path
            self.buffer = ""

        def write(self, data):
            self.buffer += data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.store[self.path] = self.buffer

    class FakeSFTP:
        def __init__(self, store):
            self.store = store

        def file(self, path, _mode):
            return FakeRemoteFile(self.store, path)

        def close(self):
            return None

    mgr.ssh_client = SimpleNamespace(open_sftp=lambda: FakeSFTP(uploaded))

    async def fake_connect():
        return None

    async def fake_install():
        return True, "ok"

    async def fake_ensure_container():
        return "cid"

    async def fake_upload_bridge(_path):
        return "/tmp/mqtt_bridge_ros2.py"

    async def fake_copy_into_container(_remote_tmp, target_path="/root/mqtt_bridge_ros2.py"):
        return None

    async def fake_exec(command, detach=False, timeout=20):
        if "head -n 30 /root/mqtt_bridge_ros2.log" in command:
            return 0, "subscribed:", ""
        return 0, "", ""

    async def fake_run_host(_command, timeout=20):
        return 0, "", ""

    async def fake_sleep(_seconds):
        return None

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(mgr, "_connect_async", fake_connect)
    monkeypatch.setattr(mgr, "_install_paho_dependency_async", fake_install)
    monkeypatch.setattr(mgr, "_ensure_container_id_async", fake_ensure_container)
    monkeypatch.setattr(mgr, "_upload_bridge_script_async", fake_upload_bridge)
    monkeypatch.setattr(mgr, "_copy_into_container_async", fake_copy_into_container)
    monkeypatch.setattr(mgr, "_exec_in_container_async", fake_exec)
    monkeypatch.setattr(mgr, "_run_host_async", fake_run_host)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    import src.core.constants as constants

    monkeypatch.setattr(
        constants,
        "load_config",
        lambda strict=False: {
            "mqtt": {
                "host": "10.0.0.2",
                "port": 1883,
                "topics": {
                    "odom": "robot/odom",
                    "odom_raw": "robot/odom_raw",
                    "voltage": "robot/custom_voltage",
                    "path": "robot/custom_path",
                    "cmd_vel": "robot/custom_cmd_vel",
                },
            },
            "topics": {
                "odom": "/odom",
                "odom_raw": "/odom_raw",
                "global_plan": "/custom_plan",
                "cmd_vel": "/custom_cmd_vel",
            },
        },
    )

    success, _msg = asyncio.run(mgr.start_mqtt_bridge_async())

    wrapper_script = uploaded["/tmp/run_bridge.sh"]
    assert success is True
    assert "export ROS_TOPIC_ODOM=/odom" in wrapper_script
    assert "export ROS_TOPIC_ODOM_RAW=/odom_raw" in wrapper_script
    assert "export ROS_TOPIC_PLAN=/custom_plan" in wrapper_script
    assert "export ROS_TOPIC_CMD_VEL=/custom_cmd_vel" in wrapper_script
    assert "export MQTT_TOPIC_ODOM=robot/odom" in wrapper_script
    assert "export MQTT_TOPIC_ODOM_RAW=robot/odom_raw" in wrapper_script
    assert "export MQTT_TOPIC_VOLTAGE=robot/custom_voltage" in wrapper_script
    assert "export MQTT_TOPIC_PATH=robot/custom_path" in wrapper_script
    assert "export MQTT_TOPIC_CMD_VEL=robot/custom_cmd_vel" in wrapper_script
