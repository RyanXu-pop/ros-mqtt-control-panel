import asyncio
import logging
import os
import re
import tempfile
from typing import Tuple

class MapSyncMixin:
    """提供栅格地图的文件保存、上传与下载能力"""

    YAHBOOM_MAP_DIR = "/root/yahboomcar_ws/src/yahboomcar_nav/maps"
    YAHBOOM_DEFAULT_MAP_NAME = "yahboom_map"

    async def save_map_async(self, map_name: str = "my_map") -> Tuple[bool, str]:
        if self.mock_mode:
            await asyncio.sleep(1)
            return True, f"[Mock] 地图已保存"
        await self._connect_async()
        try:
            check_topic_cmd = "ros2 topic list 2>/dev/null | grep -q '/map' && echo 'TOPIC_EXISTS' || echo 'NO_TOPIC'"
            code_t, out_t, _ = await self._exec_in_container_async(check_topic_cmd, detach=False, timeout=10)
            if "NO_TOPIC" in out_t:
                return False, "❌ /map 话题不存在！\n\n请确保：\n1. Gmapping 已启动\n2. 机器人已移动过"
            
            cleanup_cmd = f"rm -f {self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.pgm {self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.yaml"
            await self._exec_in_container_async(cleanup_cmd, detach=False, timeout=5)
            await self._exec_in_container_async("pkill -f 'save_map_launch.py' || true", detach=False, timeout=5)
            await self._exec_in_container_async("pkill -f 'map_saver' || true", detach=False, timeout=5)
            
            save_cmd = "ros2 launch yahboomcar_nav save_map_launch.py"
            nohup_cmd = f"nohup bash -c 'source /opt/ros/humble/setup.bash && source /root/yahboomcar_ws/install/setup.bash 2>/dev/null && export ROS_DOMAIN_ID=20 && {save_cmd}' > /root/save_map.log 2>&1 &"
            code, out, err = await self._exec_in_container_async(nohup_cmd, detach=False, timeout=10)
            
            if code != 0: return False, f"启动保存地图失败: {err or out}"
            
            max_wait = 15
            waited = 0
            map_saved = False
            while waited < max_wait:
                verify_cmd = f"test -f {self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.pgm && test -f {self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.yaml && echo 'FILES_EXIST'"
                code_v, out_v, _ = await self._exec_in_container_async(verify_cmd, detach=False, timeout=5)
                if "FILES_EXIST" in out_v:
                    map_saved = True
                    break
                await asyncio.sleep(2)
                waited += 2
            
            await self._exec_in_container_async("pkill -f save_map_launch.py || true", detach=False, timeout=5)
            
            if not map_saved:
                log_cmd = "cat /root/save_map.log 2>/dev/null | tail -30"
                _, log_out, _ = await self._exec_in_container_async(log_cmd, detach=False, timeout=5)
                return False, f"地图保存超时\n日志:\n{log_out[:600]}"
            
            if map_name != self.YAHBOOM_DEFAULT_MAP_NAME:
                custom_dir = "/root/maps"
                await self._exec_in_container_async(f"mkdir -p {custom_dir}", detach=False, timeout=5)
                src_pgm = f"{self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.pgm"
                src_yaml = f"{self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.yaml"
                dst_pgm = f"{custom_dir}/{map_name}.pgm"
                dst_yaml = f"{custom_dir}/{map_name}.yaml"
                await self._exec_in_container_async(f"cp {src_pgm} {dst_pgm}", detach=False, timeout=10)
                await self._exec_in_container_async(f"sed 's/image: {self.YAHBOOM_DEFAULT_MAP_NAME}.pgm/image: {map_name}.pgm/' {src_yaml} > {dst_yaml}", detach=False, timeout=10)
                return True, f"地图已保存并生成副本: {custom_dir}/{map_name}.*"
            
            return True, f"地图已保存: {self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}.pgm"
        except Exception as e:
            return False, f"保存地图异常: {e}"

    async def download_map_async(self, map_name: str, local_dir: str) -> Tuple[bool, str]:
        await self._connect_async()
        try:
            cid = await self._ensure_container_id_async()
            search_paths = [(f"/root/maps/{map_name}", map_name), (f"{self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}", self.YAHBOOM_DEFAULT_MAP_NAME)]
            
            found_path = None
            found_name = None
            for path, name in search_paths:
                code, out, _ = await self._exec_in_container_async(f"test -f {path}.pgm && echo 'EXISTS' || echo 'NOT'", detach=False, timeout=5)
                if "EXISTS" in out:
                    found_path, found_name = path, name
                    break
            
            if not found_path: return False, "未找到相应的地图文件"
            
            host_tmp_dir = "/tmp/map_download"
            await self._run_host_async(f"mkdir -p {host_tmp_dir}", timeout=5)
            
            for ext in [".pgm", ".yaml"]:
                cp_cmd = f"docker cp {cid}:{found_path}{ext} {host_tmp_dir}/{map_name}{ext}"
                code, out, err = await self._run_host_async(cp_cmd, timeout=30)
                if code != 0: return False, f"复制失败: {err or out}"
            
            if found_name != map_name:
                await self._run_host_async(f"sed -i 's/image: {found_name}.pgm/image: {map_name}.pgm/' {host_tmp_dir}/{map_name}.yaml", timeout=5)
            
            os.makedirs(local_dir, exist_ok=True)
            
            def do_download():
                sftp = self.ssh_client.open_sftp()
                try:
                    for ext in [".pgm", ".yaml"]:
                        sftp.get(f"{host_tmp_dir}/{map_name}{ext}", os.path.join(local_dir, f"{map_name}{ext}"))
                finally:
                    sftp.close()
            
            await asyncio.to_thread(do_download)
            await self._run_host_async(f"rm -rf {host_tmp_dir}", timeout=5)
            return True, f"地图已下载: {local_dir}/{map_name}.pgm"
        except Exception as e:
            return False, f"下载异常: {e}"

    async def upload_map_async(self, local_pgm_path: str, local_yaml_path: str) -> Tuple[bool, str]:
        await self._connect_async()
        if not os.path.exists(local_pgm_path) or not os.path.exists(local_yaml_path): return False, "本地文件不存在"
        try:
            cid = await self._ensure_container_id_async()
            host_tmp_dir = "/tmp/map_upload"
            await self._run_host_async(f"mkdir -p {host_tmp_dir}", timeout=5)
            
            def do_upload():
                sftp = self.ssh_client.open_sftp()
                try:
                    sftp.put(local_pgm_path, f"{host_tmp_dir}/{self.YAHBOOM_DEFAULT_MAP_NAME}.pgm")
                    with open(local_yaml_path, 'r') as f: content = f.read()
                    content = re.sub(r'image:\s*\S+\.pgm', f'image: {self.YAHBOOM_DEFAULT_MAP_NAME}.pgm', content)
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
                        tmp.write(content)
                        tmp_path = tmp.name
                    try:
                        sftp.put(tmp_path, f"{host_tmp_dir}/{self.YAHBOOM_DEFAULT_MAP_NAME}.yaml")
                    finally:
                        os.unlink(tmp_path)
                finally:
                    sftp.close()
            
            await asyncio.to_thread(do_upload)
            
            for ext in [".pgm", ".yaml"]:
                cp_cmd = f"docker cp {host_tmp_dir}/{self.YAHBOOM_DEFAULT_MAP_NAME}{ext} {cid}:{self.YAHBOOM_MAP_DIR}/{self.YAHBOOM_DEFAULT_MAP_NAME}{ext}"
                code, out, err = await self._run_host_async(cp_cmd, timeout=30)
                if code != 0: return False, f"复制到容器失败: {err}"
            
            await self._run_host_async(f"rm -rf {host_tmp_dir}", timeout=5)
            return True, "地图已成功上传"
        except Exception as e:
            return False, f"上传异常: {e}"
