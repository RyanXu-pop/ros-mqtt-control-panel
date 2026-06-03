import asyncio
import logging
import time
import shlex
from typing import Tuple

class ROSServiceMixin:
    """提供 ROS 2 具体业务模块（底盘、建图、导航）的启停逻辑"""

    CHASSIS_SESSION_NAME = "chassis"
    GMAPPING_SESSION_NAME = "gmapping"
    NAVIGATION_SESSION_NAME = "navigation"
    
    CHASSIS_SIGNAL_PATTERNS = ("yahboomcar_bringup_launch.py",)
    GMAPPING_SIGNAL_PATTERNS = ("map_gmapping_launch.py", "slam_gmapping")
    NAVIGATION_SIGNAL_PATTERNS = ("navigation_dwb_launch.py", "nav2_bringup", "amcl", "controller_server", 
                                "planner_server", "bt_navigator", "behavior_server", "recoveries_server", 
                                "smoother_server", "velocity_smoother", "waypoint_follower", "map_server", "lifecycle_manager")
    
    CHASSIS_STOP_MARKERS = ("user interrupted with ctrl-c (SIGINT)", "signal_handler(signum=2)", "process has finished cleanly")
    GMAPPING_STOP_MARKERS = ("user interrupted with ctrl-c (SIGINT)", "signal_handler(signum=2)", "GridSlamProcessor::~GridSlamProcessor(): Start", "Deleting tree", "process has finished cleanly")
    NAVIGATION_STOP_MARKERS = ("user interrupted with ctrl-c (SIGINT)", "signal_handler(signum=2)", "Running Nav2 LifecycleManager rcl preshutdown", "process has finished cleanly")
    
    NAVIGATION_NODE_GREP = "amcl|controller_server|planner_server|bt_navigator|behavior_server|recoveries_server|smoother_server|velocity_smoother|waypoint_follower|map_server|lifecycle_manager"
    
    # ---------- Chassis ----------
    async def start_chassis_async(self) -> Tuple[bool, str]:
        if self.mock_mode:
            await asyncio.sleep(1)
            return True, "[Mock] 底盘 Bringup 已启动"
        await self._connect_async()
        try:
            await self._clear_launch_session_state_async(self.CHASSIS_SESSION_NAME)
            await self._exec_in_container_async("pkill -f yahboomcar_bringup_launch.py || true", detach=False, timeout=5)
            await asyncio.sleep(1)
            _, _, log_path = self._launch_session_paths(self.CHASSIS_SESSION_NAME)
            await self._exec_in_container_async(f"rm -f {log_path}", detach=False, timeout=5)

            start_cmd = (
                "nohup bash -lc "
                "'ros2 launch yahboomcar_bringup yahboomcar_bringup_launch.py' "
                f"> {log_path} 2>&1 < /dev/null &"
            )
            code, out, err = await self._exec_in_container_async(start_cmd, detach=False, timeout=10)
            if code != 0:
                return False, f"底盘启动命令下发失败: {err or out}"

            logging.info("等待底盘启动...")
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                process_running = await self._process_patterns_running_async(self.CHASSIS_SIGNAL_PATTERNS)
                if process_running:
                    return True, "底盘启动成功（进程运行中）"
                await asyncio.sleep(1)

            _, log_out, _ = await self._exec_in_container_async(f"tail -n 80 {log_path} 2>&1 || true", detach=False, timeout=5)
            detail = log_out.strip() or "无日志输出"
            return False, f"底盘进程未检测到，可能启动失败\n日志:\n{detail[-1200:]}"
        except Exception as e:
            logging.error(f"启动底盘异常: {e}")
            return False, f"启动底盘异常: {e}"

    async def stop_chassis_async(self) -> Tuple[bool, str]:
        if self.mock_mode: return True, "[Mock] 底盘 Bringup 已停止"
        try:
            await self._connect_async()
            if not self.ssh_client: return False, "SSH 未连接"
            
            stopped = await self._graceful_stop_process_group_async(
                self.CHASSIS_SIGNAL_PATTERNS, self._wait_for_chassis_stop_async, "Chassis Bringup", session_name=self.CHASSIS_SESSION_NAME
            )
            if not stopped: return False, "底盘 Bringup 未完全退出"

            await self._clear_launch_session_state_async(self.CHASSIS_SESSION_NAME)
            return True, "底盘 Bringup 已关闭"
        except Exception as e:
            return False, f"停止底盘异常: {e}"

    async def _odom_publishers_active_async(self) -> bool:
        _, out, err = await self._exec_in_container_async("ros2 topic info /odom 2>/dev/null || true", detach=False, timeout=8)
        text = f"{out}\n{err}".strip()
        if not text or "Publisher count: 0" in text or "Unknown topic" in text: return False
        return "Publisher count:" in text

    async def _wait_for_chassis_stop_async(self, timeout_s: float = 6.0, poll_interval: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            processes_running = await self._process_patterns_running_async(self.CHASSIS_SIGNAL_PATTERNS)
            odom_active = await self._odom_publishers_active_async()
            marker_seen = await self._launch_log_contains_markers_async(self._launch_session_paths(self.CHASSIS_SESSION_NAME)[2], self.CHASSIS_STOP_MARKERS)
            if not odom_active and (not processes_running or marker_seen): return True
            await asyncio.sleep(poll_interval)
        processes_running = await self._process_patterns_running_async(self.CHASSIS_SIGNAL_PATTERNS)
        odom_active = await self._odom_publishers_active_async()
        marker_seen = await self._launch_log_contains_markers_async(self._launch_session_paths(self.CHASSIS_SESSION_NAME)[2], self.CHASSIS_STOP_MARKERS)
        return not odom_active and (not processes_running or marker_seen)

    # ---------- Gmapping ----------
    async def start_gmapping_async(self) -> Tuple[bool, str]:
        if self.mock_mode: return True, "[Mock] Gmapping 已启动！"
        await self._connect_async()
        try:
            await self._clear_launch_session_state_async(self.GMAPPING_SESSION_NAME)
            await self._exec_in_container_async("pkill -f map_gmapping_launch.py || true", detach=False, timeout=5)
            await self._exec_in_container_async("pkill -f slam_gmapping || true", detach=False, timeout=5)

            check_cmd = "pgrep -f '[y]ahboomcar_bringup_launch.py' || echo 'NOT_RUNNING'"
            _, out_check, _ = await self._exec_in_container_async(check_cmd, detach=False, timeout=5)
            if "NOT_RUNNING" in out_check:
                return False, "请先启动底盘 (Bringup)，建图需要底盘的里程计数据"

            launch_ok, launch_msg = await self._start_tracked_launch_async(self.GMAPPING_SESSION_NAME, "ros2 launch yahboomcar_nav map_gmapping_launch.py")
            if not launch_ok: return False, f"Gmapping 启动失败: {launch_msg}"

            await asyncio.sleep(3)
            map_check_cmd = "ros2 topic list 2>/dev/null | grep '/map' || echo 'NO_MAP_TOPIC'"
            _, out_m, _ = await self._exec_in_container_async(map_check_cmd, detach=False, timeout=10)
            if "NO_MAP_TOPIC" in out_m:
                return True, "Gmapping 已启动！\n\n⚠️ 注意：/map 话题尚未出现\n请移动机器人以生成地图数据"
            return True, "Gmapping 建图已启动！"
        except Exception as e:
            return False, f"启动 Gmapping 异常: {e}"

    async def stop_gmapping_async(self) -> Tuple[bool, str]:
        if self.mock_mode: return True, "[Mock] Gmapping 已停止"
        try:
            await self._connect_async()
            if not self.ssh_client: return False, "SSH 未连接"
            
            stopped = await self._graceful_stop_process_group_async(
                self.GMAPPING_SIGNAL_PATTERNS, self._wait_for_gmapping_stop_async, "Gmapping", session_name=self.GMAPPING_SESSION_NAME
            )
            if not stopped: return False, "Gmapping 未完全退出"

            await self._clear_launch_session_state_async(self.GMAPPING_SESSION_NAME)
            return True, "Gmapping 建图已关闭"
        except Exception as e:
            return False, f"停止 Gmapping 异常: {e}"

    async def _wait_for_gmapping_stop_async(self, timeout_s: float = 6.0, poll_interval: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            processes_running = await self._process_patterns_running_async(self.GMAPPING_SIGNAL_PATTERNS)
            marker_seen = await self._launch_log_contains_markers_async(self._launch_session_paths(self.GMAPPING_SESSION_NAME)[2], self.GMAPPING_STOP_MARKERS)
            if not processes_running or marker_seen: return True
            await asyncio.sleep(poll_interval)
        processes_running = await self._process_patterns_running_async(self.GMAPPING_SIGNAL_PATTERNS)
        marker_seen = await self._launch_log_contains_markers_async(self._launch_session_paths(self.GMAPPING_SESSION_NAME)[2], self.GMAPPING_STOP_MARKERS)
        return not processes_running or marker_seen

    # ---------- Navigation ----------
    async def start_navigation_async(self) -> Tuple[bool, str]:
        if self.mock_mode: return True, "[Mock] Navigation2 已启动！"
        await self._connect_async()
        try:
            check_chassis_cmd = "pgrep -f '[y]ahboomcar_bringup_launch.py' || echo ''"
            code_c, out_c, _ = await self._exec_in_container_async(check_chassis_cmd, detach=False, timeout=5)
            if code_c != 0 or not out_c.strip(): return False, "底盘未启动！"

            map_path = "/root/yahboomcar_ws/src/yahboomcar_nav/maps/yahboom_map.yaml"
            check_map_cmd = f"test -f {map_path} && echo 'MAP_EXISTS' || echo 'NO_MAP'"
            _, out_m, _ = await self._exec_in_container_async(check_map_cmd, detach=False, timeout=5)
            if "NO_MAP" in out_m: return False, f"地图文件不存在: {map_path}\n请先建图并保存"

            await self._clear_launch_session_state_async(self.NAVIGATION_SESSION_NAME)
            await self._exec_in_container_async("pkill -f navigation_dwb_launch.py || true", detach=False, timeout=5)
            await self._exec_in_container_async("pkill -f nav2_bringup || true", detach=False, timeout=5)
            await asyncio.sleep(1)

            launch_ok, launch_msg = await self._start_tracked_launch_async(self.NAVIGATION_SESSION_NAME, "ros2 launch yahboomcar_nav navigation_dwb_launch.py")
            if not launch_ok: return False, f"导航启动失败: {launch_msg}"

            await asyncio.sleep(5)
            check_nav_cmd = "ros2 node list 2>/dev/null | grep -E 'amcl|controller_server|planner_server' | head -3"
            for _ in range(3):
                _, out_n, _ = await self._exec_in_container_async(check_nav_cmd, detach=False, timeout=10)
                if "amcl" in out_n or "controller_server" in out_n: break
                await asyncio.sleep(3)
            else:
                return False, "导航节点启动超时"

            check_amcl_cmd = "timeout 5 ros2 lifecycle get /amcl 2>/dev/null | grep -i 'active' >/dev/null && echo 'AMCL_ACTIVE' || echo 'AMCL_NOT'"
            _, out_amcl, _ = await self._exec_in_container_async(check_amcl_cmd, detach=False, timeout=10)
            if "AMCL_ACTIVE" in out_amcl: return True, "Navigation2 已启动（AMCL 已激活）"
            return True, "导航节点已启动（等待 AMCL 初始化...）"
        except Exception as e:
            return False, f"启动导航异常: {e}"

    async def _publish_zero_cmd_vel_async(self) -> bool:
        cmd = "timeout 5 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}'"
        code, out, err = await self._exec_in_container_async(cmd, detach=False, timeout=8)
        return code == 0

    async def _amcl_publishers_active_async(self) -> bool:
        _, out, err = await self._exec_in_container_async("ros2 topic info /amcl_pose 2>/dev/null || true", detach=False, timeout=8)
        text = f"{out}\n{err}".strip()
        if not text or "Publisher count: 0" in text or "Unknown topic" in text: return False
        return "Publisher count:" in text

    async def stop_navigation_mode_async(self) -> Tuple[bool, str]:
        if self.mock_mode: return True, "[Mock] 导航已停止"
        try:
            await self._connect_async()
            if not self.ssh_client: return False, "SSH 未连接"
            await self._publish_zero_cmd_vel_async()
            
            nav_stopped = await self._graceful_stop_process_group_async(
                self.NAVIGATION_SIGNAL_PATTERNS, self._wait_for_navigation_stop_async, "Navigation2", session_name=self.NAVIGATION_SESSION_NAME
            )

            if nav_stopped: await self._clear_launch_session_state_async(self.NAVIGATION_SESSION_NAME)

            if nav_stopped: return True, "导航已关闭"
            return False, "导航进程未能正常退出，请检查容器日志"
        except Exception as e:
            return False, f"停止异常: {e}"

    async def _wait_for_navigation_stop_async(self, timeout_s: float = 6.0, poll_interval: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            amcl_active = await self._amcl_publishers_active_async()
            processes_running = await self._process_patterns_running_async(self.NAVIGATION_SIGNAL_PATTERNS)
            marker_seen = await self._launch_log_contains_markers_async(self._launch_session_paths(self.NAVIGATION_SESSION_NAME)[2], self.NAVIGATION_STOP_MARKERS)
            if not amcl_active and (not processes_running or marker_seen): return True
            await asyncio.sleep(poll_interval)
        amcl_active = await self._amcl_publishers_active_async()
        processes_running = await self._process_patterns_running_async(self.NAVIGATION_SIGNAL_PATTERNS)
        marker_seen = await self._launch_log_contains_markers_async(self._launch_session_paths(self.NAVIGATION_SESSION_NAME)[2], self.NAVIGATION_STOP_MARKERS)
        return not amcl_active and (not processes_running or marker_seen)
