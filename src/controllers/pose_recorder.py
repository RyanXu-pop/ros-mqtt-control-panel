# pose_recorder.py
# -*- coding: utf-8 -*-
"""
PoseRecorder — 位置记录模块

负责机器人轨迹数据的实时追加、手动标记和 XLSX 持久化。
纯数据逻辑，不依赖 Qt UI，通过 status_cb 回调通知上层更新状态栏。
"""

import os
import time
import math
import logging
from datetime import datetime
from typing import List, Optional, Any, Tuple
import numpy as np

from PySide6.QtCore import QObject, Signal
import pandas as pd
from src.core.models import RobotPose
from src.core.utils import apply_affine_transform



class PoseRecorder(QObject):
    """
    位置记录器。

    典型用法::

        recorder = PoseRecorder(xlsx_path)
        recorder.start()          # 开始记录
        recorder.append(x, y, z, angle)  # 在 update_plot 里调用
        recorder.stop()           # 停止并写 XLSX
    """

    COLUMNS = ['日期', '时间', '距离', 'X', 'Y', 'Z', '角度']
    status_message = Signal(str)

    def __init__(self, xlsx_path: str, parent=None):
        """
        Args:
            xlsx_path:  XLSX 输出路径
        """
        super().__init__(parent)
        self.xlsx_path = xlsx_path
        self.last_saved_path = xlsx_path

        self.recording: bool = False
        self._records: List[List[Any]] = []

    # ------------------------------------------------------------------ #
    # 控制
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """开始新一轮记录（清空已有数据，删除旧 XLSX）。"""
        self.recording = True
        self._records.clear()
        if os.path.exists(self.xlsx_path):
            try:
                os.remove(self.xlsx_path)
                logging.info(f"[PoseRecorder] 旧文件已删除: {self.xlsx_path}")
            except PermissionError:
                logging.error(f"[PoseRecorder] 无法删除文件（被占用）: {self.xlsx_path}")
            except Exception as e:
                logging.error(f"[PoseRecorder] 删除文件时出错: {e}")
        self.status_message.emit("状态: 开始记录位置信息")


    def stop(self) -> bool:
        """
        停止记录并将已积累的数据写入 XLSX。

        Returns:
            True 表示成功写入，False 表示无数据或写入失败
        """
        self.recording = False
        if not self._records:
            self.status_message.emit("状态: 没有位置信息需要保存")

            return False
        try:
            df = pd.DataFrame(self._records, columns=self.COLUMNS)
            save_path = self.xlsx_path
            try:
                df.to_excel(save_path, index=False)
            except ImportError as exc:
                if "openpyxl" not in str(exc):
                    raise
                save_path = os.path.splitext(self.xlsx_path)[0] + ".csv"
                df.to_csv(save_path, index=False, encoding="utf-8-sig")
            self.last_saved_path = save_path
            msg = f"位置信息已保存到 {save_path}"
            self.status_message.emit(f"状态: {msg}")

            logging.info(f"[PoseRecorder] {msg}")
            return True
        except Exception as e:
            msg = f"保存位置信息失败 - {e}"
            self.status_message.emit(f"状态: {msg}")

            logging.error(f"[PoseRecorder] {msg}")
            return False

    # ------------------------------------------------------------------ #
    # 数据追加
    # ------------------------------------------------------------------ #

    def append(self, x: float, y: float, z: float, angle: float) -> None:
        """
        在 update_plot 定时器回调中调用，将当前变换后坐标追加到缓冲区。
        仅在 recording=True 时有效。
        """
        if not self.recording:
            return
        now = datetime.now()
        dist = math.hypot(x, y)
        self._records.append([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S.%f"),
            dist, x, y, z, angle,
        ])

    @property
    def has_records(self) -> bool:
        return bool(self._records)

    # ------------------------------------------------------------------ #
    # 手动标记（UI 列表）
    # ------------------------------------------------------------------ #

    def format_current(self, last_data: Optional[RobotPose], affine_M) -> Optional[str]:
        """
        将 last_data 中的坐标变换后格式化为可读字符串。
        返回 None 表示数据不可用。

        Args:
            last_data:  当前最新的位姿实体 (RobotPose)
            affine_M:   仿射变换矩阵（3×3 ndarray）
        """
        if last_data and isinstance(last_data, RobotPose):
            current_time_str = time.strftime("%H:%M:%S")
            prefix = f"{current_time_str} - "
            x, y = apply_affine_transform(affine_M, [(last_data.x, last_data.y)])[0]
            return f"{prefix}X: {x:.3f}, Y: {y:.3f}, Yaw: {last_data.angle:.1f}°"
        return None
