import copy
import json
import os
import uuid
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal


class InspectionPlanManager(QObject):
    """Local inspection plan storage for patrol/inspection workflows."""

    plans_changed = Signal(list)
    current_plan_changed = Signal(dict)

    DEFAULT_MODE = "nav2"

    def __init__(self, path: str = "data/inspection_plans.json", parent=None):
        super().__init__(parent)
        self.path = path
        self._data = {"version": 1, "current_plan_id": "", "plans": []}
        self.load()

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                if isinstance(data.get("plans"), list):
                    self._data = data
        except Exception:
            self._data = {"version": 1, "current_plan_id": "", "plans": []}

        if not self._data.get("plans"):
            plan = self._new_plan("默认巡检方案")
            self._data = {"version": 1, "current_plan_id": plan["id"], "plans": [plan]}
            self.save()

        if not self.current_plan():
            self._data["current_plan_id"] = self._data["plans"][0]["id"]
        self._emit()

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def plans(self) -> List[Dict]:
        return self._data.get("plans", [])

    def current_plan(self) -> Optional[Dict]:
        current_id = self._data.get("current_plan_id", "")
        for plan in self.plans():
            if plan.get("id") == current_id:
                return plan
        return None

    def set_current_plan(self, plan_id: str):
        if any(plan.get("id") == plan_id for plan in self.plans()):
            self._data["current_plan_id"] = plan_id
            self.save()
            self._emit()

    def create_plan(self, name: str = "新巡检方案") -> Dict:
        plan = self._new_plan(name)
        self._data.setdefault("plans", []).append(plan)
        self._data["current_plan_id"] = plan["id"]
        self.save()
        self._emit()
        return plan

    def duplicate_current_plan(self) -> Optional[Dict]:
        plan = self.current_plan()
        if not plan:
            return None
        duplicate = copy.deepcopy(plan)
        duplicate["id"] = self._make_id("plan")
        duplicate["name"] = f"{plan.get('name', '巡检方案')} 副本"
        for point in duplicate.get("waypoints", []):
            point["id"] = self._make_id("wp")
        for point in duplicate.get("route_points", []):
            point["id"] = self._make_id("route")
        self._data.setdefault("plans", []).append(duplicate)
        self._data["current_plan_id"] = duplicate["id"]
        self.save()
        self._emit()
        return duplicate

    def delete_current_plan(self) -> bool:
        if len(self.plans()) <= 1:
            return False
        current_id = self._data.get("current_plan_id", "")
        self._data["plans"] = [plan for plan in self.plans() if plan.get("id") != current_id]
        self._data["current_plan_id"] = self._data["plans"][0]["id"]
        self.save()
        self._emit()
        return True

    def update_current_plan(self, **fields):
        plan = self.current_plan()
        if not plan:
            return
        for key, value in fields.items():
            if key in {"name", "description", "mode"}:
                plan[key] = str(value)
            elif key in {"loop"}:
                plan[key] = bool(value)
            elif key in {"arrival_threshold", "dwell_seconds", "direct_max_linear", "direct_max_angular"}:
                plan[key] = float(value)
        self.save()
        self._emit()

    def add_waypoint(self, x: float, y: float, yaw: float, name: str = "") -> Optional[Dict]:
        plan = self.current_plan()
        if not plan:
            return None
        waypoints = plan.setdefault("waypoints", [])
        order = len(waypoints) + 1
        point = {
            "id": self._make_id("wp"),
            "name": name.strip() or f"P{order}",
            "x": float(x),
            "y": float(y),
            "yaw": float(yaw),
            "enabled": True,
            "order": order,
        }
        waypoints.append(point)
        self._normalize_orders(plan)
        self.save()
        self._emit()
        return point

    def update_waypoint(self, waypoint_id: str, **fields):
        point = self._find_waypoint(waypoint_id)
        if not point:
            return
        for key, value in fields.items():
            if key == "name":
                point[key] = str(value).strip() or point.get("name", "P")
            elif key in {"enabled"}:
                point[key] = bool(value)
            elif key in {"x", "y", "yaw"}:
                point[key] = float(value)
        self.save()
        self._emit()

    def remove_waypoint(self, waypoint_id: str):
        plan = self.current_plan()
        if not plan:
            return
        plan["waypoints"] = [p for p in plan.get("waypoints", []) if p.get("id") != waypoint_id]
        self._normalize_orders(plan)
        self.save()
        self._emit()

    def move_waypoint(self, waypoint_id: str, direction: int):
        plan = self.current_plan()
        if not plan:
            return
        waypoints = sorted(plan.get("waypoints", []), key=lambda p: int(p.get("order", 0)))
        index = next((i for i, p in enumerate(waypoints) if p.get("id") == waypoint_id), -1)
        new_index = index + direction
        if index < 0 or new_index < 0 or new_index >= len(waypoints):
            return
        waypoints[index], waypoints[new_index] = waypoints[new_index], waypoints[index]
        plan["waypoints"] = waypoints
        self._normalize_orders(plan)
        self.save()
        self._emit()

    def enabled_waypoints(self) -> List[Dict]:
        plan = self.current_plan() or {}
        points = sorted(plan.get("waypoints", []), key=lambda p: int(p.get("order", 0)))
        return [p for p in points if p.get("enabled", True)]

    def route_points(self) -> List[Dict]:
        plan = self.current_plan() or {}
        return list(plan.get("route_points", []))

    def set_route_points(self, points: List[Dict]):
        plan = self.current_plan()
        if not plan:
            return
        route_points = []
        for idx, point in enumerate(points, start=1):
            route_points.append({
                "id": point.get("id") or self._make_id("route"),
                "name": point.get("name") or f"R{idx}",
                "x": float(point.get("x", 0.0)),
                "y": float(point.get("y", 0.0)),
                "yaw": float(point.get("yaw", 0.0)),
                "enabled": True,
                "order": idx,
            })
        plan["route_points"] = route_points
        self.save()
        self._emit()

    def _find_waypoint(self, waypoint_id: str) -> Optional[Dict]:
        plan = self.current_plan()
        if not plan:
            return None
        for point in plan.get("waypoints", []):
            if point.get("id") == waypoint_id:
                return point
        return None

    def _emit(self):
        self.plans_changed.emit(self.plans())
        self.current_plan_changed.emit(self.current_plan() or {})

    def _new_plan(self, name: str) -> Dict:
        return {
            "id": self._make_id("plan"),
            "name": name,
            "description": "",
            "mode": self.DEFAULT_MODE,
            "loop": True,
            "arrival_threshold": 0.45,
            "dwell_seconds": 1.0,
            "direct_max_linear": 0.15,
            "direct_max_angular": 0.45,
            "waypoints": [],
            "route_points": [],
        }

    @staticmethod
    def _make_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    @staticmethod
    def _normalize_orders(plan: Dict):
        for idx, point in enumerate(plan.get("waypoints", []), start=1):
            point["order"] = idx
