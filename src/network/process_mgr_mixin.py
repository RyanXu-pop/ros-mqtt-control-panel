import asyncio
import logging
import shlex
import time
from typing import Optional, Sequence, Tuple

class ProcessManagerMixin:
    """提供基于会话与信号的通用进程守护能力"""
    
    SESSION_STATE_DIR = "/tmp/robot_panel"
    STOP_SIGNAL_TIMEOUT_S = 5.0

    def _launch_session_paths(self, session_name: str) -> Tuple[str, str, str]:
        pid_file = f"{self.SESSION_STATE_DIR}/{session_name}.pid"
        pgid_file = f"{self.SESSION_STATE_DIR}/{session_name}.pgid"
        if session_name == "chassis":
            return pid_file, pgid_file, "/root/bringup.log"
        if session_name == "gmapping":
            return pid_file, pgid_file, "/root/gmapping.log"
        if session_name == "navigation":
            return pid_file, pgid_file, "/root/navigation.log"
        raise ValueError(f"unknown launch session: {session_name}")

    async def _clear_launch_session_state_async(self, session_name: str) -> None:
        pid_file, pgid_file, _ = self._launch_session_paths(session_name)
        await self._exec_in_container_async(
            f"mkdir -p {self.SESSION_STATE_DIR} && rm -f {pid_file} {pgid_file}", detach=False, timeout=5
        )

    async def _launch_session_running_async(self, session_name: str) -> bool:
        pid_file, pgid_file, _ = self._launch_session_paths(session_name)
        cmd = (
            f"PID=''; PGID=''; "
            f"[ -f {pid_file} ] && PID=$(cat {pid_file} 2>/dev/null); "
            f"[ -f {pgid_file} ] && PGID=$(cat {pgid_file} 2>/dev/null); "
            f"if [ -n \"$PGID\" ] && kill -0 -- -$PGID 2>/dev/null; then echo RUNNING; "
            f"elif [ -n \"$PID\" ] && kill -0 $PID 2>/dev/null; then echo RUNNING; "
            f"else echo NOT_RUNNING; fi"
        )
        _, out, _ = await self._exec_in_container_async(cmd, detach=False, timeout=5)
        return "RUNNING" in out

    async def _wait_for_launch_session_start_async(self, session_name: str, timeout_s: float = 5.0, poll_interval: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if await self._launch_session_running_async(session_name): return True
            await asyncio.sleep(poll_interval)
        return await self._launch_session_running_async(session_name)

    async def _start_tracked_launch_async(self, session_name: str, launch_command: str) -> Tuple[bool, str]:
        pid_file, pgid_file, log_path = self._launch_session_paths(session_name)
        await self._clear_launch_session_state_async(session_name)
        start_cmd = (
            f"mkdir -p {self.SESSION_STATE_DIR} && rm -f {log_path} && nohup setsid bash -lc "
            f"'echo $$ > {pid_file}; echo $$ > {pgid_file}; exec {launch_command}' "
            f"> {log_path} 2>&1 < /dev/null &"
        )
        code, out, err = await self._exec_in_container_async(start_cmd, detach=False, timeout=10)
        if code != 0: return False, err or out
        if not await self._wait_for_launch_session_start_async(session_name):
            return False, f"launch session did not stay alive: {log_path}"
        return True, log_path

    async def _signal_launch_session_async(self, session_name: str, signal_name: str, fallback_patterns: Sequence[str]) -> None:
        pid_file, pgid_file, _ = self._launch_session_paths(session_name)
        cmd = (
            f"PID=''; PGID=''; "
            f"[ -f {pid_file} ] && PID=$(cat {pid_file} 2>/dev/null); "
            f"[ -f {pgid_file} ] && PGID=$(cat {pgid_file} 2>/dev/null); "
            f"if [ -n \"$PGID\" ] && kill -0 -- -$PGID 2>/dev/null; then kill -{signal_name} -- -$PGID 2>/dev/null && echo SIGNALLED; "
            f"elif [ -n \"$PID\" ] && kill -0 $PID 2>/dev/null; then kill -{signal_name} $PID 2>/dev/null && echo SIGNALLED; "
            f"else echo FALLBACK; fi"
        )
        _, out, _ = await self._exec_in_container_async(cmd, detach=False, timeout=5)
        if "SIGNALLED" not in out:
            logging.debug("[%s] tracked launch session missing, falling back to legacy patterns", session_name)
            await self._signal_process_patterns_async(fallback_patterns, signal_name)

    async def _signal_process_patterns_async(self, patterns: Sequence[str], signal_name: str) -> None:
        for pattern in patterns:
            cmd = f"pkill -{signal_name} -f {shlex.quote(pattern)} || true"
            await self._exec_in_container_async(cmd, detach=False, timeout=5)

    async def _process_patterns_running_async(self, patterns: Sequence[str]) -> bool:
        for pattern in patterns:
            code, out, _ = await self._exec_in_container_async(f"pgrep -f {shlex.quote(pattern)} || true", detach=False, timeout=5)
            if code == 0 and out.strip(): return True
        return False

    async def _launch_log_contains_markers_async(self, log_path: str, markers: Sequence[str], tail_lines: int = 200) -> bool:
        if not markers: return False
        marker_cmd = " ".join(f"-e {shlex.quote(marker)}" for marker in markers)
        cmd = f"test -f {log_path} || exit 0; tail -n {tail_lines} {log_path} 2>/dev/null | grep -F {marker_cmd} >/dev/null && echo MARKER_SEEN || true"
        _, out, _ = await self._exec_in_container_async(cmd, detach=False, timeout=8)
        return "MARKER_SEEN" in out

    async def _graceful_stop_process_group_async(self, patterns: Sequence[str], verify_fn, label: str, session_name: Optional[str] = None) -> bool:
        logging.info("[%s] 发送 SIGINT，等价于终端 Ctrl+C", label)
        if await verify_fn(timeout_s=0.0):
            logging.info("[%s] 已处于停止状态", label)
            return True
        if session_name: await self._signal_launch_session_async(session_name, "SIGINT", patterns)
        else: await self._signal_process_patterns_async(patterns, "SIGINT")
        if await verify_fn(timeout_s=self.STOP_SIGNAL_TIMEOUT_S):
            logging.info("[%s] 已完成停止校验", label)
            return True
        logging.warning("[%s] SIGINT 后仍未完全停止", label)
        return False
