# constants.py
import os
import yaml
import logging
import sys

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# 抑制 paramiko 的底层日志（如 sftp session opened/closed），只保留 WARNING 及以上
logging.getLogger("paramiko").setLevel(logging.WARNING)


def _maybe_chdir_for_frozen():
    """PyInstaller 打包后资源在 exe 同目录的 _internal 下，切换 cwd 以便 config/maps/data 相对路径可用。"""
    if not getattr(sys, "frozen", False):
        return
    base = os.path.dirname(os.path.abspath(sys.executable))
    internal = os.path.join(base, "_internal")
    os.chdir(internal if os.path.isdir(internal) else base)


def resolve_config_path() -> str:
    """优先 config.yaml，否则使用仓库中的 config.example.yaml（便于首次运行与分发）。"""
    for name in ("config.yaml", "config.example.yaml"):
        p = os.path.join("config", name)
        if os.path.isfile(p):
            return p
    return os.path.join("config", "config.yaml")


_maybe_chdir_for_frozen()
CONFIG_PATH = resolve_config_path()


def load_config(path: str | None = None, strict: bool = True) -> dict:
    """
    从YAML文件加载配置
    
    Args:
        path: 配置文件路径
        strict: 是否进行严格验证（默认 True，用于主程序）
                False 时只验证存在的部分，不要求所有部分都存在（用于测试脚本）
    
    Returns:
        配置字典
    """
    if path is None:
        path = CONFIG_PATH
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        if not strict:
            # 宽松模式：只验证存在的部分，不要求所有部分都存在
            return config
        
        # 严格模式：验证所有必需字段（用于主程序）
        # 注意：ros 配置已移除，因为现在通过 SSH + MQTT 通信，不再需要直接 ROS 连接
        required_fields = {
            'ssh': ['host', 'port', 'username', 'password'],
            'paths': ['map_yaml', 'record_xlsx', 'initial_pose_json'],
            'params': ['map_bounds'],

            'topics': ['amcl_pose', 'move_base_goal', 'initial_pose',
                      'amcl_pose_msg_type', 'pose_stamped_msg_type'],
            'mqtt': ['host', 'port']
        }
        for section, fields in required_fields.items():
            if section not in config:
                logging.error(f"配置文件缺少 '{section}' 部分")
                sys.exit(1)
            for field in fields:
                if field not in config[section]:
                    logging.error(f"配置文件缺少 '{section}.{field}'")
                    sys.exit(1)
        
        return config
    except FileNotFoundError:
        logging.error(f"配置文件 '{path}' 未找到")
        sys.exit(1)
    except yaml.YAMLError as e:
        logging.error(f"解析配置文件 '{path}' 出错: {e}")
        sys.exit(1)

# 加载全局配置
# 使用宽松模式加载，避免测试脚本因缺少某些配置而失败
# 主程序会在启动时进行必要的验证
CONFIG = load_config(CONFIG_PATH, strict=False)

# 安全地获取配置，如果不存在则返回空字典
ROS_CONFIG = CONFIG.get('ros', {})
SSH_CONFIG = CONFIG.get('ssh', {})
PATHS_CONFIG = CONFIG.get('paths', {})
PARAMS_CONFIG = CONFIG.get('params', {})
TOPICS_CONFIG = CONFIG.get('topics', {})
# 新增 MQTT 配置
MQTT_CONFIG = CONFIG.get('mqtt', {})
MQTT_TOPICS_CONFIG = MQTT_CONFIG.get('topics', {})


def validate_config_for_main_app():
    """
    为主程序验证配置完整性
    在主程序启动时调用此函数进行严格验证
    """
    load_config(CONFIG_PATH, strict=True)