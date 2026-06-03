import asyncio
import logging
import paramiko
from typing import Optional, Tuple

from src.core.constants import SSH_CONFIG

class SSHBaseMixin:
    """提供底层的 SSH 与 Docker 容器通信能力"""
    
    def __init__(self):
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.container_id: Optional[str] = None
        self.mock_mode: bool = False
        self._connect_lock = asyncio.Lock()

    async def _connect_async(self) -> None:
        if self.mock_mode: return
        async with self._connect_lock:
            if self.ssh_client: return
            logging.info("初始化 SSH 客户端 (Async)...")
            
            def do_connect():
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                try:
                    client.connect(
                        SSH_CONFIG["host"], SSH_CONFIG["port"], SSH_CONFIG["username"], SSH_CONFIG["password"], timeout=5
                    )
                except Exception as e:
                    raise RuntimeError(f"无法建立 SSH 连接，请检查电脑是否已连上小车的 WiFi 并且 IP 正确！\n(底层错误: {str(e)})")
                return client
            
            try:
                self.ssh_client = await asyncio.to_thread(do_connect)
                logging.info("SSH 连接成功")
            except Exception as outer_e:
                self.ssh_client = None
                raise outer_e

    async def _run_host_async(self, command: str, timeout: int = 15) -> Tuple[int, str, str]:
        if not self.ssh_client: raise RuntimeError("SSH 未连接")
        def run_cmd():
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            return exit_code, out, err
        return await asyncio.to_thread(run_cmd)

    async def _ensure_container_id_async(self) -> str:
        if self.container_id: return self.container_id
        cmd_yahboom = r"""docker ps --format '{{.ID}} {{.Image}}' | grep 'yahboomtechnology/ros-humble' | head -n1 | awk '{print $1}'"""
        code, out, err = await self._run_host_async(cmd_yahboom)
        cid = out.strip()
        
        if code != 0 or not cid:
            cmd_fallback = r"""docker ps --format '{{.ID}} {{.Image}}' | grep -Ei '(humble|ros)' | head -n1 | awk '{print $1}'"""
            code, out, err = await self._run_host_async(cmd_fallback)
            cid = out.strip()
        
        if code != 0 or not cid: raise RuntimeError(f"未找到运行中的 ROS2 容器. err: {err}")
        
        self.container_id = cid
        logging.info(f"✅ 找到 ROS2 容器: {cid}")
        return cid

    async def _exec_in_container_async(self, command: str, detach: bool = False, timeout: int = 20) -> Tuple[int, str, str]:
        cid = await self._ensure_container_id_async()
        dash_d = "-d" if detach else ""
        wrapped = (
            f'docker exec {dash_d} {cid} bash -c '
            f'"source /root/.bashrc 2>/dev/null || true; '
            f'source /opt/ros/humble/setup.bash 2>/dev/null || true; '
            f'source /root/yahboomcar_ws/install/setup.bash 2>/dev/null || true; '
            f'export ROS_DOMAIN_ID=20; '
            f'{command}"'
        )
        return await self._run_host_async(wrapped, timeout=timeout)
