import logging
import asyncio

from src.network.ssh_base_mixin import SSHBaseMixin
from src.network.process_mgr_mixin import ProcessManagerMixin
from src.network.ros_services_mixin import ROSServiceMixin
from src.network.map_sync_mixin import MapSyncMixin
from src.network.mqtt_bridge_mixin import MQTTBridgeMixin

class AsyncSSHManager(
    ROSServiceMixin, 
    MapSyncMixin, 
    MQTTBridgeMixin, 
    ProcessManagerMixin, 
    SSHBaseMixin
):
    """
    异步版本的 SSH 管理器。
    
    架构说明：
    为了解决 1100+ 行无序代码造成的维护地狱，本作已被重构为 5 个功能单一的 Mixin：
    - SSHBaseMixin: 负责最底层的 SSH 与 Docker shell 通信代理
    - ProcessManagerMixin: 负责 ROS 进程的生命周期注入与守护逻辑
    - ROSServiceMixin: 负责底盘 Bringup、Gmapping 和 Navigation2 业务启停
    - MapSyncMixin: 负责 SFTP 协议相关的地图配置序列化与反序列化及远端交互
    - MQTTBridgeMixin: 负责定制 Python 下发的 MQTT 桥接脚本部署与启动
    
    采用多重继承直接组装出的此类，保留了与原有调用方 100% 同样的方法签名（即插即用）。
    """
    def __init__(self):
        # 初始化基类中需要的共享状态变量 (ssh_client, mock_mode 等)
        SSHBaseMixin.__init__(self)
        
    async def close_async(self, stop_services: bool = True):
        """完全清理并断开连接"""
        if self.ssh_client:
            if stop_services:
                await self.stop_navigation_mode_async()
                await self.stop_gmapping_async()
                await self.stop_chassis_async()
            self.ssh_client.close()
            logging.info("SSH 客户端已断开")
