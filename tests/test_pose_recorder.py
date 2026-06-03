import sys
import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

# Need to adjust import path since tests is a subdirectory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.controllers.pose_recorder import PoseRecorder
from src.core.models import RobotPose
import numpy as np

def test_recorder_start_and_append(tmp_path):
    # Use pytest's tmp_path fixture to create a temporary test Excel file path
    xlsx_file = tmp_path / "test_records.xlsx"
    recorder = PoseRecorder(str(xlsx_file))
    
    recorder.start()
    assert recorder.recording is True
    assert len(recorder._records) == 0
    
    # Append a couple of frames
    recorder.append(1.0, 2.0, 0.0, 45.0)
    recorder.append(3.0, 4.0, 0.0, 90.0)
    
    assert len(recorder._records) == 2

def test_recorder_stop_writes_to_file(tmp_path):
    xlsx_file = tmp_path / "test_records.xlsx"
    recorder = PoseRecorder(str(xlsx_file))
    
    recorder.start()
    recorder.append(1.0, 0.0, 0.0, 90.0)
    
    # Should return True because records exist
    result = recorder.stop()
    assert result is True
    assert recorder.recording is False
    
    # Check if file was created
    assert xlsx_file.exists()
    
    # Verify content using pandas
    df = pd.read_excel(str(xlsx_file))
    assert len(df) == 1
    assert df.iloc[0]['X'] == 1.0
    assert df.iloc[0]['Y'] == 0.0
    assert df.iloc[0]['角度'] == 90.0

def test_recorder_stop_empty(tmp_path):
    xlsx_file = tmp_path / "test_records.xlsx"
    recorder = PoseRecorder(str(xlsx_file))
    
    recorder.start()
    # No append
    result = recorder.stop()
    assert result is False
    assert not xlsx_file.exists()

def test_format_current():
    recorder = PoseRecorder("dummy.xlsx")
    affine_M = np.eye(3)
    
    # Create strong-typed RobotPose
    pose = RobotPose(x=5.0, y=-5.0, angle=180.0)
    
    formatted = recorder.format_current(pose, affine_M)
    assert formatted is not None
    assert "X: 5.000, Y: -5.000, Yaw: 180.0°" in formatted
    
    # Test with None
    assert recorder.format_current(None, affine_M) is None
