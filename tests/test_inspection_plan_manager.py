import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.controllers.inspection_plan_manager import InspectionPlanManager


def test_inspection_plan_manager_creates_edits_and_persists_plans(tmp_path):
    path = tmp_path / "inspection_plans.json"
    manager = InspectionPlanManager(str(path))

    plan = manager.create_plan("实验室巡检")
    assert manager.current_plan()["id"] == plan["id"]

    point = manager.add_waypoint(1.2, -0.5, 0.3, name="门口")
    manager.update_waypoint(point["id"], name="入口", enabled=False)
    manager.update_current_plan(mode="manual", loop=False, arrival_threshold=0.42, dwell_seconds=2.0)

    reloaded = InspectionPlanManager(str(path))
    current = reloaded.current_plan()
    assert current["name"] == "实验室巡检"
    assert current["mode"] == "manual"
    assert current["loop"] is False
    assert current["arrival_threshold"] == 0.42
    assert current["dwell_seconds"] == 2.0
    assert current["waypoints"][0]["name"] == "入口"
    assert current["waypoints"][0]["enabled"] is False


def test_inspection_plan_manager_deletes_current_plan_but_keeps_one_plan(tmp_path):
    path = tmp_path / "inspection_plans.json"
    manager = InspectionPlanManager(str(path))
    first_id = manager.current_plan()["id"]
    second = manager.create_plan("二号方案")

    manager.delete_current_plan()

    assert manager.current_plan()["id"] != second["id"]
    assert len(manager.plans()) == 1
    assert manager.current_plan()["id"] == first_id
    assert json.loads(path.read_text(encoding="utf-8"))["plans"]
