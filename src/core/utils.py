import logging
from collections import OrderedDict
from typing import List, Optional, Tuple

import numpy as np


def convert_to_float(item: str) -> Optional[float]:
    try:
        return float(item)
    except (ValueError, TypeError):
        logging.warning("Unable to convert %r to float", item)
        return None


def compute_affine_transform(
    src_points: List[Tuple[float, float]],
    dst_points: List[Tuple[float, float]],
) -> np.ndarray:
    if len(src_points) < 3 or len(dst_points) < 3:
        raise ValueError("Need at least 3 point pairs to compute an affine transform")

    a_rows = []
    b_rows = []
    for (x, y), (u, v) in zip(src_points, dst_points):
        a_rows.append([x, y, 1, 0, 0, 0])
        a_rows.append([0, 0, 0, x, y, 1])
        b_rows.extend([u, v])

    a = np.array(a_rows, dtype=np.float64)
    b = np.array(b_rows, dtype=np.float64)
    try:
        params = np.linalg.lstsq(a, b, rcond=None)[0]
    except np.linalg.LinAlgError as exc:
        raise ValueError("Unable to compute affine transform") from exc

    return np.array(
        [
            [params[0], params[1], params[2]],
            [params[3], params[4], params[5]],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )


def compute_inverse_affine_transform(m: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.inv(m)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Matrix is not invertible") from exc


def apply_affine_transform(m: np.ndarray, points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    points_hom = np.array([(x, y, 1) for x, y in points], dtype=np.float64).T
    transformed = m @ points_hom
    return [(x, y) for x, y, _ in transformed.T]


def normalize_angle_rad(angle: float) -> float:
    return float((angle + np.pi) % (2 * np.pi) - np.pi)


def apply_pose_transform(
    transform_x: float,
    transform_y: float,
    transform_yaw: float,
    pose_x: float,
    pose_y: float,
    pose_yaw: float,
) -> Tuple[float, float, float]:
    cos_yaw = np.cos(transform_yaw)
    sin_yaw = np.sin(transform_yaw)
    x = transform_x + cos_yaw * pose_x - sin_yaw * pose_y
    y = transform_y + sin_yaw * pose_x + cos_yaw * pose_y
    yaw = normalize_angle_rad(transform_yaw + pose_yaw)
    return float(x), float(y), float(yaw)


class BoundedCache(OrderedDict):
    def __init__(self, maxsize: int = 500):
        super().__init__()
        self._maxsize = maxsize
        self._keys_order: List[Tuple] = []

    def __setitem__(self, key, value):
        if key not in self:
            if len(self) >= self._maxsize:
                oldest = self._keys_order.pop(0)
                super().__delitem__(oldest)
            self._keys_order.append(key)
        super().__setitem__(key, value)
