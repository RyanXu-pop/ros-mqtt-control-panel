import math

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.core.models import MapMetadata

from src.ui_v2.map.layers import LidarLayer, OccupancyMapLayer, PathLayer


def test_occupancy_grid_rgba_matches_rviz_semantics():
    grid = np.array([[0, 100, 255, 50]], dtype=np.uint8)

    rgba = OccupancyMapLayer._occupancy_to_rgba(grid)

    assert rgba[0, 0].tolist() == [255, 255, 255, 255]
    assert rgba[0, 1].tolist() == [0, 0, 0, 255]
    assert rgba[0, 2].tolist() == [242, 244, 247, 255]
    assert rgba[0, 3].tolist() == [242, 244, 247, 255]


def test_path_layer_bounding_rect_covers_positive_world_y():
    layer = PathLayer()
    layer.set_path([{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])

    rect = layer.boundingRect()

    assert rect.left() <= 0.0
    assert rect.right() >= 1.0
    assert rect.top() <= 0.0
    assert rect.bottom() >= 1.0


def test_map_layer_applies_origin_yaw(qapp):
    layer = OccupancyMapLayer()
    meta = MapMetadata(
        width=2,
        height=2,
        resolution=0.5,
        origin_x=1.0,
        origin_y=2.0,
        origin_yaw=math.pi / 2,
        data=np.zeros((2, 2), dtype=np.uint8),
        encoding="occupancy_grid",
    )

    layer.set_map_data(meta)
    transform = layer.transform()

    assert layer.transformationMode() == Qt.FastTransformation
    assert layer.pos().x() == 1.0
    assert layer.pos().y() == 2.0
    assert transform.m11() == pytest.approx(0.0, abs=1e-6)
    assert transform.m12() == pytest.approx(0.5, abs=1e-6)
    assert transform.m21() == pytest.approx(-0.5, abs=1e-6)
    assert transform.m22() == pytest.approx(0.0, abs=1e-6)


def test_occupancy_grid_pixmap_keeps_bottom_row_without_extra_flip(qapp):
    layer = OccupancyMapLayer()
    meta = MapMetadata(
        width=1,
        height=2,
        resolution=1.0,
        data=np.array([[0], [100]], dtype=np.uint8),
        encoding="occupancy_grid",
    )

    layer.set_map_data(meta)
    image = layer.pixmap().toImage()

    assert QColor(image.pixel(0, 0)).getRgb()[:3] == (255, 255, 255)
    assert QColor(image.pixel(0, 1)).getRgb()[:3] == (0, 0, 0)


def test_map_layer_clear_removes_existing_pixmap(qapp):
    layer = OccupancyMapLayer()
    meta = MapMetadata(
        width=1,
        height=1,
        resolution=1.0,
        data=np.array([[0]], dtype=np.uint8),
        encoding="occupancy_grid",
    )

    layer.set_map_data(meta)
    assert not layer.pixmap().isNull()

    layer.clear_map()
    assert layer.pixmap().isNull()


def test_map_layer_replaces_previous_pixmap(qapp):
    layer = OccupancyMapLayer()
    first = MapMetadata(width=1, height=1, data=np.array([[0]], dtype=np.uint8), encoding="occupancy_grid")
    second = MapMetadata(width=2, height=1, data=np.array([[0, 100]], dtype=np.uint8), encoding="occupancy_grid")

    layer.set_map_data(first)
    assert layer.pixmap().width() == 1

    layer.set_map_data(second)
    assert layer.pixmap().width() == 2
    image = layer.pixmap().toImage()
    assert QColor(image.pixel(0, 0)).getRgb()[:3] == (255, 255, 255)
    assert QColor(image.pixel(1, 0)).getRgb()[:3] == (0, 0, 0)


def test_lidar_layer_replaces_previous_frame_instead_of_accumulating(qapp):
    layer = LidarLayer()

    first_scan = {
        "angle_min": 0.0,
        "angle_increment": math.pi / 2,
        "ranges": [1.0, 1.0],
    }
    second_scan = {
        "angle_min": 0.0,
        "angle_increment": math.pi / 2,
        "ranges": [2.0],
    }

    layer.set_scan(first_scan, 0.0, 0.0, 0.0)
    assert len(layer.points) == 2

    layer.set_scan(second_scan, 0.0, 0.0, 0.0)
    assert len(layer.points) == 1
    assert layer.points[0].x() == pytest.approx(2.0)
    assert layer.points[0].y() == pytest.approx(0.0)


def test_path_and_lidar_layers_can_be_cleared(qapp):
    path_layer = PathLayer()
    path_layer.set_path([{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}])
    assert path_layer.path_points

    path_layer.clear_path()
    assert path_layer.path_points == []

    lidar_layer = LidarLayer()
    lidar_layer.set_scan({"angle_min": 0.0, "angle_increment": math.pi / 2, "ranges": [1.0]}, 0.0, 0.0, 0.0)
    assert lidar_layer.points

    lidar_layer.clear_scan()
    assert lidar_layer.points == []
