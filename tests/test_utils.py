import math

import pytest

from src.core.utils import apply_pose_transform


def test_apply_pose_transform_rotates_and_translates_pose():
    x, y, yaw = apply_pose_transform(
        transform_x=1.0,
        transform_y=2.0,
        transform_yaw=math.pi / 2,
        pose_x=1.0,
        pose_y=0.0,
        pose_yaw=0.0,
    )

    assert x == pytest.approx(1.0)
    assert y == pytest.approx(3.0)
    assert yaw == pytest.approx(math.pi / 2)
