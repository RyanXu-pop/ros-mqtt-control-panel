import math

import pytest

from src.ui_v2.panels.pose_panel import PoseRecordPanel


def test_go_to_selected_converts_degrees_to_radians(qapp):
    panel = PoseRecordPanel()
    panel.list_widget.addItem("[08:12:33] X:1.20 Y:3.40 Yaw:90.00°")
    panel.list_widget.setCurrentRow(0)

    captured = []
    panel.sig_go_to_selected.connect(lambda x, y, yaw: captured.append((x, y, yaw)))

    panel._on_go_to()

    assert len(captured) == 1
    x, y, yaw = captured[0]
    assert x == pytest.approx(1.2)
    assert y == pytest.approx(3.4)
    assert yaw == pytest.approx(math.pi / 2)
