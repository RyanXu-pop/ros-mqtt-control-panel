import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.controllers.workflow_controller import WorkflowController


import pytest


@pytest.fixture
def workflow_ctrl():
    async_ssh = MagicMock()
    map_mgr = MagicMock()
    return WorkflowController(async_ssh, map_mgr)


def test_execute_navigation_workflow_aborts_on_map_upload_failure(workflow_ctrl):
    events = []
    workflow_ctrl.workflow_finished.connect(lambda name, ok, msg: events.append((name, ok, msg)))
    workflow_ctrl._upload_local_map = AsyncMock(return_value=(False, "boom"))
    workflow_ctrl.start_service_async = AsyncMock(return_value=(False, "boom"))

    asyncio.run(workflow_ctrl.execute_navigation_workflow())

    assert events[-1] == ("navigation", False, "地图上传失败: boom")
    workflow_ctrl.start_service_async.assert_not_awaited()


def test_execute_navigation_workflow_uploads_map_before_starting_navigation(workflow_ctrl):
    workflow_ctrl._upload_local_map = AsyncMock(return_value=(True, "uploaded"))
    workflow_ctrl.start_service_async = AsyncMock(return_value=(True, "started"))

    asyncio.run(workflow_ctrl.execute_navigation_workflow("my_map"))

    workflow_ctrl._upload_local_map.assert_awaited_once_with("my_map")
    workflow_ctrl.start_service_async.assert_awaited_once_with("navigation")


def test_execute_stop_navigation_workflow_emits_result(workflow_ctrl):
    events = []
    workflow_ctrl.workflow_finished.connect(lambda name, ok, msg: events.append((name, ok, msg)))
    workflow_ctrl.stop_service_async = AsyncMock(return_value=(True, "stopped"))

    asyncio.run(workflow_ctrl.execute_stop_navigation_workflow())

    assert events[-1] == ("stop_navigation", True, "stopped")


def test_save_and_stop_mapping_stops_after_success(workflow_ctrl):
    workflow_ctrl.save_and_sync_map_async = AsyncMock(return_value=(True, "saved"))
    workflow_ctrl.stop_service_async = AsyncMock(return_value=(True, "gmapping stopped"))
    events = []
    workflow_ctrl.workflow_finished.connect(lambda name, ok, msg: events.append((name, ok, msg)))

    asyncio.run(workflow_ctrl.execute_save_and_stop_mapping_workflow("my_map"))

    workflow_ctrl.save_and_sync_map_async.assert_awaited_once()
    workflow_ctrl.stop_service_async.assert_awaited_once_with("gmapping")
    assert events[-1] == ("stop_mapping", True, "gmapping stopped")


def test_save_and_stop_mapping_keeps_mapping_running_when_save_fails(workflow_ctrl):
    workflow_ctrl.save_and_sync_map_async = AsyncMock(return_value=(False, "save failed"))
    workflow_ctrl.stop_service_async = AsyncMock(return_value=(True, "should not stop"))

    asyncio.run(workflow_ctrl.execute_save_and_stop_mapping_workflow("my_map"))

    workflow_ctrl.stop_service_async.assert_not_awaited()
