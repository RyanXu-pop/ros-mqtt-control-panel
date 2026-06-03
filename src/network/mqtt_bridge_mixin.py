import asyncio
import glob
import logging
import os
import shlex
import tempfile
from typing import Optional, Tuple

class MQTTBridgeMixin:
    """提供 MQTT Bridge 脚本上传、依赖安装和启停管理"""

    DEFAULT_BRIDGE_LOCAL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ros", "mqtt_bridge_ros2.py")

    async def _upload_bridge_script_async(self, local_file_path: Optional[str] = None) -> str:
        if not self.ssh_client: raise RuntimeError("SSH 未连接")
        src_path = local_file_path or self.DEFAULT_BRIDGE_LOCAL_PATH
        if not os.path.exists(src_path): raise FileNotFoundError(f"本地桥接脚本不存在: {src_path}")

        def do_upload():
            with open(src_path, "r", encoding="utf-8") as rf: content = rf.read()
            local_fd, local_path = tempfile.mkstemp(prefix="mqtt_bridge_", suffix=".py")
            with os.fdopen(local_fd, "w", encoding="utf-8") as wf: wf.write(content)
            remote_tmp = "/tmp/mqtt_bridge.py"
            try:
                sftp = self.ssh_client.open_sftp()
                sftp.put(local_path, remote_tmp)
                sftp.close()
            finally:
                os.remove(local_path)
            return remote_tmp
            
        return await asyncio.to_thread(do_upload)

    async def _copy_into_container_async(self, remote_tmp: str, target_path: str = "/root/mqtt_bridge_ros2.py"):
        cid = await self._ensure_container_id_async()
        check_src_cmd = f"test -f {remote_tmp} && echo 'EXISTS' || echo 'NOT_FOUND'"
        code_src, out_src, _ = await self._run_host_async(check_src_cmd, timeout=5)
        if "NOT_FOUND" in out_src: raise RuntimeError(f"源文件不存在: {remote_tmp}")
        
        await self._run_host_async(f"docker exec {cid} rm -f {target_path}", timeout=5)
        code, out, err = await self._run_host_async(f"docker cp {remote_tmp} {cid}:{target_path}", timeout=30)
        if code != 0: raise RuntimeError(f"docker cp 失败: {err or out}")
        
        verify_cmd = f"docker exec {cid} test -f {target_path} && echo 'EXISTS' || echo 'NOT'"
        _, out_verify, _ = await self._run_host_async(verify_cmd, timeout=10)
        if "NOT" in out_verify: raise RuntimeError(f"验证失败: 容器内文件不存在 {target_path}")
        await self._run_host_async(f"rm -f {remote_tmp}", timeout=5)

    async def _install_paho_dependency_async(self) -> Tuple[bool, str]:
        try:
            logging.info("开始安装 paho-mqtt...")
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            wheel_files = glob.glob(os.path.join(project_root, "scripts", "paho_mqtt*.whl"))
            if not wheel_files: return False, f"未找到 paho_mqtt*.whl 文件: {project_root}"
            wheel_path = wheel_files[0]
            
            def do_upload_wheel():
                sftp = self.ssh_client.open_sftp()
                try: sftp.put(wheel_path, "/tmp/paho_mqtt.whl")
                finally: sftp.close()
                return "/tmp/paho_mqtt.whl"
                
            remote_tmp = await asyncio.to_thread(do_upload_wheel)
            cid = await self._ensure_container_id_async()
            container_wheel = "/root/paho_mqtt.whl"
            code, out, err = await self._run_host_async(f"docker cp {remote_tmp} {cid}:{container_wheel}", timeout=30)
            if code != 0: return False, f"复制 wheel 失败: {err}"
            
            install_script = '''import sys, os, zipfile
wheel_path = "/root/paho_mqtt.whl"
site_packages = next((p for p in sys.path if "site-packages" in p or "dist-packages" in p), None)
if not site_packages:
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    paths = [f"/usr/local/lib/python{ver}/site-packages", f"/usr/lib/python{ver}/site-packages", f"/usr/lib/python{ver}/dist-packages"]
    site_packages = next((p for p in paths if os.path.exists(p)), None)
if not site_packages: sys.exit(1)
try:
    with zipfile.ZipFile(wheel_path, 'r') as w: w.extractall(site_packages)
except: sys.exit(1)
'''
            host_script = "/tmp/install_paho.py"
            def do_upload_script():
                sftp = self.ssh_client.open_sftp()
                try: 
                    with sftp.file(host_script, 'w') as f: f.write(install_script)
                finally: sftp.close()
            
            await asyncio.to_thread(do_upload_script)
            container_script = "/root/install_paho.py"
            await self._run_host_async(f"docker cp {host_script} {cid}:{container_script}", timeout=10)
            
            code, out, err = await self._exec_in_container_async(f"python3 {container_script}", detach=False, timeout=60)
            await self._run_host_async(f"docker exec {cid} rm -f {container_script} {container_wheel}", timeout=5)
            await self._run_host_async(f"rm -f {remote_tmp} {host_script}", timeout=5)
            
            return (True, "paho-mqtt 已安装") if code == 0 else (False, f"安装失败: {err or out}")
        except Exception as e:
            return False, str(e)

    async def start_mqtt_bridge_async(self) -> Tuple[bool, str]:
        if self.mock_mode: return True, "[Mock] MQTT 桥接已启动"
        await self._connect_async()
        try:
            await self._exec_in_container_async("pkill -9 -f mqtt_bridge_ros2.py || true", detach=False, timeout=8)
            await self._exec_in_container_async("pkill -9 -f run_bridge.sh || true", detach=False, timeout=8)
            await asyncio.sleep(2)
            await self._exec_in_container_async("rm -f /root/mqtt_bridge_ros2.log", detach=False, timeout=5)
            
            paho_ok, paho_msg = await self._install_paho_dependency_async()
            if not paho_ok: return False, f"paho-mqtt 安装失败: {paho_msg}"
            
            from src.core.constants import load_config
            cfg = load_config(strict=False)
            m_cfg, r_cfg = cfg.get("mqtt", {}), cfg.get("topics", {})
            bridge_cfg = m_cfg.get("bridge", {}) or {}
            m_topics = m_cfg.get("topics", {}) or {}
            m_host, m_port = m_cfg.get("host", ""), int(m_cfg.get("port", 1883))
            
            if not m_host: raise RuntimeError("MQTT 配置 host 为空")

            cid = await self._ensure_container_id_async()
            await self._exec_in_container_async("rm -f /root/mqtt_bridge_ros2.py /root/run_bridge.sh || true", detach=False)
            remote_tmp = await self._upload_bridge_script_async(self.DEFAULT_BRIDGE_LOCAL_PATH)
            await self._copy_into_container_async(remote_tmp, "/root/mqtt_bridge_ros2.py")

            ros_env = {
                "ROS_TOPIC_AMCL": r_cfg.get("amcl_pose", "/amcl_pose"),
                "ROS_TOPIC_ODOM": r_cfg.get("odom", "/odom"),
                "ROS_TOPIC_ODOM_RAW": r_cfg.get("odom_raw", "/odom_raw"),
                "ROS_TOPIC_BATTERY": r_cfg.get("power_voltage", "/battery"),
                "ROS_TOPIC_MAP": r_cfg.get("map", "/map"),
                "ROS_TOPIC_SCAN": r_cfg.get("laser_scan", "/scan"),
                "ROS_TOPIC_PLAN": r_cfg.get("global_plan", "/plan"),
                "ROS_TOPIC_TF": r_cfg.get("tf", "/tf"),
                "ROS_TOPIC_TF_STATIC": r_cfg.get("tf_static", "/tf_static"),
                "ROS_TOPIC_CMD_VEL": r_cfg.get("cmd_vel", "/cmd_vel"),
                "ROS_TOPIC_GOAL": r_cfg.get("move_base_goal", "/goal_pose"),
                "ROS_TOPIC_INITIALPOSE": r_cfg.get("initial_pose", "/initialpose"),
            }
            mqtt_env = {
                "MQTT_TOPIC_POSE": m_topics.get("pose", "robot/pose"),
                "MQTT_TOPIC_ODOM": m_topics.get("odom", "robot/odom"),
                "MQTT_TOPIC_ODOM_RAW": m_topics.get("odom_raw", "robot/odom_raw"),
                "MQTT_TOPIC_STATUS": m_topics.get("status", "robot/status"),
                "MQTT_TOPIC_VOLTAGE": m_topics.get("voltage", "robot/voltage"),
                "MQTT_TOPIC_MAP": m_topics.get("map", "robot/map"),
                "MQTT_TOPIC_SCAN": m_topics.get("scan", "robot/scan"),
                "MQTT_TOPIC_PATH": m_topics.get("path", "robot/path"),
                "MQTT_TOPIC_TF": m_topics.get("tf", "robot/tf"),
                "MQTT_TOPIC_GOAL": m_topics.get("goal", "robot/goal"),
                "MQTT_TOPIC_INITIAL_POSE": m_topics.get("initial_pose", "robot/initial_pose"),
                "MQTT_TOPIC_CMD_VEL": m_topics.get("cmd_vel", "robot/cmd_vel"),
                "MAP_COMPRESSION_LEVEL": bridge_cfg.get("map_compression_level", 1),
            }
            env_exports = "\n".join(
                f"export {key}={shlex.quote(str(value))}"
                for key, value in {**ros_env, **mqtt_env}.items()
            )
            
            wrapper = f'''#!/bin/bash
	export MQTT_HOST={shlex.quote(str(m_host))}
	export MQTT_PORT={shlex.quote(str(m_port))}
	export ROS_DOMAIN_ID=20
	{env_exports}
	if [ -f /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash
	elif [ -f /opt/ros/humble/install/setup.bash ]; then source /opt/ros/humble/install/setup.bash
	else exit 1; fi
cd /root
python3 /root/mqtt_bridge_ros2.py >> /root/mqtt_bridge_ros2.log 2>&1
'''
            host_wrapper = "/tmp/run_bridge.sh"
            def do_upload_wrapper():
                sftp = self.ssh_client.open_sftp()
                try: 
                    with sftp.file(host_wrapper, 'w') as f: f.write(wrapper)
                finally: sftp.close()
            await asyncio.to_thread(do_upload_wrapper)
            
            await self._run_host_async(f"docker cp {host_wrapper} {cid}:/root/run_bridge.sh", timeout=10)
            code, out, err = await self._exec_in_container_async("chmod +x /root/mqtt_bridge_ros2.py /root/run_bridge.sh && nohup bash /root/run_bridge.sh &", detach=False)
            await self._run_host_async(f"rm -f {host_wrapper}", timeout=5)
            
            if code == 0:
                await asyncio.sleep(3)
                _, log_out, _ = await self._exec_in_container_async("head -n 30 /root/mqtt_bridge_ros2.log 2>&1", detach=False, timeout=5)
                if any(m in log_out.lower() for m in ["fully initialized", "started", "subscribed:"]):
                    return True, "MQTT 桥接节点已启动"
                
                await asyncio.sleep(2)
                _, proc_out, _ = await self._exec_in_container_async("pgrep -f mqtt_bridge_ros2.py && echo 'Y'", detach=False, timeout=5)
                if "Y" in proc_out: return True, "MQTT 桥接节点已启动(运行中)"
                return False, f"MQTT 桥接启动状态未知: {log_out[:300]}"
            return False, f"MQTT 启动异常: {err or out}"
        except Exception as e:
            return False, f"启动 MQTT 桥接异常: {e}"

    async def stop_mqtt_bridge_async(self):
        if not self.ssh_client: return
        try:
            await self._exec_in_container_async("pkill -f mqtt_bridge_ros2.py || true", detach=False, timeout=8)
            await self._exec_in_container_async("pkill -f run_bridge.sh || true", detach=False, timeout=8)
            await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"停止 MQTT 异常: {e}")
