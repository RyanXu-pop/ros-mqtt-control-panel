# map_manager.py

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml
from PIL import Image
from scipy.ndimage import rotate

from src.core.constants import PATHS_CONFIG


class MapManager:
    def __init__(self, map_bounds: List[float], map_rotation: float = 0.0, transform_cache=None):
        self.map_data: Optional[Dict[str, Any]] = None
        self.cached_map: Optional[np.ndarray] = None
        self.map_bounds: List[float] = list(map_bounds)
        self.map_rotation: float = map_rotation
        self.transform_cache = transform_cache if transform_cache is not None else {}

    def load(self, yaml_path: str) -> bool:
        try:
            yaml_dir = os.path.dirname(yaml_path)
            with open(yaml_path, "r", encoding="utf-8") as f:
                map_config = yaml.safe_load(f)

            image_path = self._resolve_map_image_path(yaml_dir, map_config.get("image", ""))
            raw_image = self._load_image_array(image_path)
            map_array, encoding = self._build_map_array(raw_image, map_config)

            self.map_data = {
                "resolution": float(map_config["resolution"]),
                "origin": list(map_config["origin"]),
                "image": raw_image,
                "data": map_array,
                "encoding": encoding,
                "extent": self.map_bounds,
            }
            self.cached_map = rotate(raw_image, self.map_rotation, reshape=False)
            logging.info("[MapManager] map loaded: %s shape=%s encoding=%s", image_path, raw_image.shape, encoding)
            return True
        except (FileNotFoundError, KeyError, TypeError, ValueError) as e:
            logging.error("[MapManager] failed to load map: %s", e)
            self.map_data = None
            self.cached_map = None
            return False

    def reload_display(self, map_png_path: str, map_yaml_path: str = None) -> bool:
        try:
            raw_image = self._load_image_array(map_png_path)

            resolution = 0.05
            origin = [0.0, 0.0, 0.0]
            encoding = "image"
            map_array = raw_image

            if map_yaml_path and os.path.exists(map_yaml_path):
                with open(map_yaml_path, "r", encoding="utf-8") as f:
                    info = yaml.safe_load(f) or {}
                resolution = float(info.get("resolution", 0.05))
                origin = list(info.get("origin", [0.0, 0.0, 0.0]))
                map_array, encoding = self._build_map_array(raw_image, info)
                logging.info("[MapManager] reload map params: resolution=%s origin=%s encoding=%s", resolution, origin, encoding)

            height, width = raw_image.shape[:2]
            x_min = origin[0]
            y_min = origin[1]
            x_max = x_min + width * resolution
            y_max = y_min + height * resolution

            self.map_bounds = [x_min, x_max, y_min, y_max]
            self.map_data = {
                "resolution": resolution,
                "origin": origin,
                "image": raw_image,
                "data": map_array,
                "encoding": encoding,
                "extent": self.map_bounds,
            }
            self.cached_map = rotate(raw_image, self.map_rotation, reshape=False)
            logging.info("[MapManager] map reloaded: %s size=%s", map_png_path, raw_image.shape)
            return True
        except Exception as e:
            logging.error("[MapManager] failed to reload map: %s", e)
            return False

    def update_origin(self, new_x: float, new_y: float) -> bool:
        if not self.map_data:
            logging.warning("[MapManager] update_origin called before map is loaded")
            return False
        try:
            old_origin = self.map_data["origin"]
            self.map_data["origin"] = [new_x, new_y, 0.0]

            yaml_path = PATHS_CONFIG["map_yaml"]
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}

            map_config = {
                "image": existing.get("image", os.path.basename(PATHS_CONFIG.get("map_image", "map.png"))),
                "resolution": existing.get("resolution", self.map_data.get("resolution", 0.05)),
                "origin": [new_x, new_y, 0.0],
                "negate": existing.get("negate", 0),
                "occupied_thresh": existing.get("occupied_thresh", 0.65),
                "free_thresh": existing.get("free_thresh", 0.196),
            }
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(map_config, f, default_flow_style=False, sort_keys=False)

            self.load(yaml_path)
            logging.info("[MapManager] map origin updated: %s -> [%s, %s, 0.0]", old_origin, new_x, new_y)
            return True
        except Exception as e:
            logging.error("[MapManager] failed to update origin: %s", e)
            return False

    @staticmethod
    def rotate_coords(x: float, y: float, angle: float, origin_x: float = 0.0, origin_y: float = 0.0) -> Tuple[float, float]:
        angle_rad = np.deg2rad(angle)
        xs = x - origin_x
        ys = y - origin_y
        new_x = xs * np.cos(angle_rad) - ys * np.sin(angle_rad) + origin_x
        new_y = xs * np.sin(angle_rad) + ys * np.cos(angle_rad) + origin_y
        return new_x, new_y

    @staticmethod
    def inverse_rotate_coords(x: float, y: float, angle: float, origin_x: float = 0.0, origin_y: float = 0.0) -> Tuple[float, float]:
        return MapManager.rotate_coords(x, y, -angle, origin_x, origin_y)

    @staticmethod
    def calc_direction_angle(x1: float, y1: float, x2: float, y2: float) -> float:
        return np.degrees(np.arctan2(y2 - y1, x2 - x1))

    @staticmethod
    def _resolve_map_image_path(yaml_dir: str, image_name: str) -> str:
        base_name = os.path.splitext(image_name)[0]
        png_path = os.path.join(yaml_dir, f"{base_name}.png")
        pgm_path = os.path.join(yaml_dir, f"{base_name}.pgm")

        if os.path.exists(png_path):
            return png_path
        if os.path.exists(pgm_path):
            return pgm_path

        image_path = os.path.join(yaml_dir, image_name)
        if not os.path.exists(image_path):
            raise FileNotFoundError(image_path)
        return image_path

    @staticmethod
    def _load_image_array(image_path: str) -> np.ndarray:
        image = np.array(Image.open(image_path))

        if image.ndim == 2:
            return image.astype(np.uint8)

        if image.shape[2] == 4:
            rgb = image[:, :, :3]
        else:
            rgb = image[:, :, :3]
        return rgb.astype(np.uint8)

    @staticmethod
    def _build_map_array(raw_image: np.ndarray, map_config: Dict[str, Any]) -> Tuple[np.ndarray, str]:
        mode = str(map_config.get("mode", "trinary")).lower()
        if raw_image.ndim == 2:
            grayscale = raw_image.astype(np.uint8)
            alpha = None
        else:
            grayscale = np.rint(raw_image[:, :, :3].mean(axis=2)).astype(np.uint8)
            alpha = raw_image[:, :, 3] if raw_image.shape[2] == 4 else None

        if mode == "trinary":
            grid = MapManager._to_trinary_occupancy(grayscale, alpha, map_config)
            # Map image files are stored top-down; convert to OccupancyGrid row order
            # so row 0 matches the map origin at the bottom-left corner.
            return np.flipud(grid), "occupancy_grid"

        return raw_image, "image"

    @staticmethod
    def _to_trinary_occupancy(
        grayscale: np.ndarray,
        alpha: Optional[np.ndarray],
        map_config: Dict[str, Any],
    ) -> np.ndarray:
        negate = int(map_config.get("negate", 0))
        occupied_thresh = float(map_config.get("occupied_thresh", 0.65))
        free_thresh = float(map_config.get("free_thresh", 0.196))

        if negate:
            occ = grayscale.astype(np.float32) / 255.0
        else:
            occ = (255.0 - grayscale.astype(np.float32)) / 255.0

        grid = np.full(grayscale.shape, 255, dtype=np.uint8)
        grid[occ > occupied_thresh] = 100
        grid[occ < free_thresh] = 0

        if alpha is not None:
            grid[alpha == 0] = 255

        return grid
