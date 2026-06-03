import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.controllers.service_controller import ServiceController
from src.core.models import AppSystemState


@pytest.fixture
def mock_ssh():
    ssh = MagicMock()
    ssh.start_mqtt_bridge_async = AsyncMock(return_value=(True, "ok"))
    ssh.stop_mqtt_bridge_async = AsyncMock()
    ssh.start_chassis_async = AsyncMock(return_value=(True, "ok"))
    ssh.stop_chassis_async = AsyncMock()
    ssh.start_gmapping_async = AsyncMock(return_value=(True, "ok"))
    ssh.stop_gmapping_async = AsyncMock()
    ssh.start_navigation_async = AsyncMock(return_value=(True, "ok"))
    ssh.stop_navigation_async = AsyncMock()
    ssh.stop_navigation_mode_async = AsyncMock(return_value=(True, "stopped"))
    return ssh


@pytest.fixture
def app_state():
    return AppSystemState()


@pytest.fixture
def service_ctrl(app_state, mock_ssh):
    workflow = MagicMock()
    return ServiceController(
        app_state=app_state,
        async_ssh=mock_ssh,
        workflow_ctrl=workflow,
    )


def test_can_start_mapping_navigation_conflict(service_ctrl, app_state):
    app_state.navigation_running = True
    can, reason = service_ctrl.can_start_mapping()
    assert can is False
    assert "导航" in reason


def test_can_start_mapping_chassis_required(service_ctrl, app_state):
    app_state.chassis_running = False
    app_state.navigation_running = False
    can, reason = service_ctrl.can_start_mapping()
    assert can is False
    assert "底盘" in reason


def test_can_start_mapping_mqtt_check(service_ctrl, app_state):
    app_state.chassis_running = True
    app_state.navigation_running = False
    app_state.mqtt_running = False
    can, reason = service_ctrl.can_start_mapping()
    assert can is False
    assert reason == "MQTT_NOT_RUNNING"


def test_can_start_mapping_all_ok(service_ctrl, app_state):
    app_state.chassis_running = True
    app_state.navigation_running = False
    app_state.mqtt_running = True
    can, reason = service_ctrl.can_start_mapping()
    assert can is True
    assert reason == ""


def test_can_start_navigation_mapping_conflict(service_ctrl, app_state):
    app_state.mapping_running = True
    can, reason = service_ctrl.can_start_navigation()
    assert can is False
    assert "建图" in reason


def test_can_start_navigation_chassis_required(service_ctrl, app_state):
    app_state.mapping_running = False
    app_state.chassis_running = False
    can, reason = service_ctrl.can_start_navigation()
    assert can is False
    assert "底盘" in reason


def test_can_start_navigation_all_ok(service_ctrl, app_state):
    app_state.mapping_running = False
    app_state.chassis_running = True
    can, reason = service_ctrl.can_start_navigation()
    assert can is True
    assert reason == ""


def test_toggle_navigation_stop_updates_state_only_on_success(service_ctrl, app_state, mock_ssh):
    app_state.chassis_running = True
    app_state.navigation_running = True
    mock_ssh.stop_navigation_mode_async.return_value = (True, "stopped")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(service_ctrl.toggle_navigation_async())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert app_state.navigation_running is False
    assert app_state.chassis_running is False
    mock_ssh.stop_navigation_mode_async.assert_awaited_once()


def test_toggle_navigation_stop_keeps_state_on_failure(service_ctrl, app_state, mock_ssh):
    app_state.chassis_running = True
    app_state.navigation_running = True
    mock_ssh.stop_navigation_mode_async.return_value = (False, "still running")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(service_ctrl.toggle_navigation_async())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert app_state.navigation_running is True
    assert app_state.chassis_running is True
    mock_ssh.stop_navigation_mode_async.assert_awaited_once()
