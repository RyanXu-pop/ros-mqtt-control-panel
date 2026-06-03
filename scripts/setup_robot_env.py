#!/usr/bin/env python3
"""
离线安装 paho-mqtt 到 ROS 2 容器（无需 pip）
适用于无法联网且没有 pip 的嵌入式机器人环境
使用手动提取 wheel 文件的方式安装
"""
import sys
import os
import glob
import paramiko
from typing import Optional

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from constants import SSH_CONFIG


def find_wheel_file() -> Optional[str]:
    """在当前目录查找 paho_mqtt wheel 文件"""
    print("="*60)
    print("步骤 1: 查找 wheel 文件")
    print("="*60)
    
    # 搜索当前目录下的 wheel 文件
    patterns = [
        "paho_mqtt*.whl",
        "paho-mqtt*.whl",
    ]
    
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            wheel_file = matches[0]
            print(f"✅ 找到 wheel 文件: {wheel_file}")
            print(f"   文件大小: {os.path.getsize(wheel_file) / 1024:.2f} KB")
            return wheel_file
    
    print("❌ 未找到 paho_mqtt wheel 文件")
    print("\n请执行以下步骤:")
    print("1. 访问 https://pypi.org/project/paho-mqtt/#files")
    print("2. 下载 paho_mqtt-*-py3-none-any.whl")
    print("3. 将文件放到项目根目录")
    return None


def connect_ssh() -> paramiko.SSHClient:
    """建立 SSH 连接"""
    print("\n" + "="*60)
    print("步骤 2: SSH 连接到机器人")
    print("="*60)
    
    print(f"连接信息:")
    print(f"  Host: {SSH_CONFIG['host']}")
    print(f"  Port: {SSH_CONFIG['port']}")
    print(f"  Username: {SSH_CONFIG['username']}")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(
            SSH_CONFIG['host'],
            SSH_CONFIG['port'],
            SSH_CONFIG['username'],
            SSH_CONFIG['password'],
            timeout=10
        )
        print("✅ SSH 连接成功")
        return ssh
    except paramiko.AuthenticationException:
        print("❌ SSH 认证失败")
        raise
    except Exception as e:
        print(f"❌ SSH 连接失败: {e}")
        raise


def find_container(ssh: paramiko.SSHClient) -> str:
    """查找运行中的 ROS 2 容器"""
    print("\n" + "="*60)
    print("步骤 3: 查找 ROS 2 容器")
    print("="*60)
    
    cmd = r"""docker ps --format '{{.ID}} {{.Image}}' | grep -Ei '(humble|ros)' | head -n1 | awk '{print $1}'"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
    exit_code = stdout.channel.recv_exit_status()
    container_id = stdout.read().decode('utf-8').strip()
    err = stderr.read().decode('utf-8', errors='ignore')
    
    if exit_code != 0 or not container_id:
        raise RuntimeError(f"未找到运行中的 ROS 2 容器. err: {err}")
    
    print(f"✅ 找到容器: {container_id}")
    return container_id


def upload_wheel_file(ssh: paramiko.SSHClient, local_wheel_path: str) -> str:
    """上传 wheel 文件到机器人主机"""
    print("\n" + "="*60)
    print("步骤 4: 上传 wheel 文件到机器人")
    print("="*60)
    
    wheel_filename = os.path.basename(local_wheel_path)
    remote_path = f"/tmp/{wheel_filename}"
    
    print(f"本地文件: {local_wheel_path}")
    print(f"目标路径: {remote_path}")
    print("正在上传...")
    
    sftp = ssh.open_sftp()
    try:
        sftp.put(local_wheel_path, remote_path)
        print(f"✅ 文件已上传到: {remote_path}")
        return remote_path
    finally:
        sftp.close()


def copy_to_container(ssh: paramiko.SSHClient, container_id: str, remote_wheel_path: str) -> str:
    """将 wheel 文件复制到容器内"""
    print("\n" + "="*60)
    print("步骤 5: 复制文件到容器")
    print("="*60)
    
    wheel_filename = os.path.basename(remote_wheel_path)
    container_path = f"/root/{wheel_filename}"
    
    print(f"容器内路径: {container_path}")
    print("正在复制...")
    
    # 使用 docker cp 复制文件
    cmd = f'docker cp {remote_wheel_path} {container_id}:{container_path}'
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode('utf-8', errors='ignore')
    
    if exit_code != 0:
        raise RuntimeError(f"复制文件到容器失败: {err}")
    
    print(f"✅ 文件已复制到容器: {container_path}")
    return container_path


def force_install_no_pip(ssh: paramiko.SSHClient, container_id: str, container_wheel_path: str) -> bool:
    """
    手动提取 wheel 文件安装（无需 pip）
    wheel 文件本质上是 ZIP 压缩包，可以直接解压到 site-packages 目录
    """
    print("\n" + "="*60)
    print("步骤 6: 手动提取安装 paho-mqtt（无需 pip）")
    print("="*60)
    
    # 构建安装脚本内容
    install_script = f'''import sys
import os
import zipfile

wheel_path = "{container_wheel_path}"

# 查找 site-packages 目录
site_packages = None
for path in sys.path:
    if "site-packages" in path or "dist-packages" in path:
        site_packages = path
        break

if not site_packages:
    # 如果找不到，尝试常见路径
    python_version = f"{{sys.version_info.major}}.{{sys.version_info.minor}}"
    common_paths = [
        f"/usr/local/lib/python{{python_version}}/site-packages",
        f"/usr/lib/python{{python_version}}/site-packages",
        f"/usr/lib/python{{python_version}}/dist-packages",
    ]
    for path in common_paths:
        if os.path.exists(path):
            site_packages = path
            break

if not site_packages:
    print("ERROR: 无法找到 site-packages 目录")
    print(f"sys.path = {{sys.path}}")
    sys.exit(1)

print(f"找到 site-packages 目录: {{site_packages}}")

# 打开 wheel 文件（ZIP 格式）
try:
    with zipfile.ZipFile(wheel_path, 'r') as wheel:
        print(f"正在解压 wheel 文件: {{wheel_path}}")
        
        # 提取所有文件到 site-packages
        wheel.extractall(site_packages)
        
        print(f"✅ 成功提取到: {{site_packages}}")
        print(f"已安装的文件:")
        for name in wheel.namelist():
            if not name.endswith('/'):
                print(f"  - {{name}}")
        
except zipfile.BadZipFile:
    print(f"ERROR: {{wheel_path}} 不是有效的 ZIP 文件")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: 提取失败: {{e}}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("✅ 安装完成")
'''
    
    # 将脚本上传到主机，然后复制到容器
    script_filename = "install_paho.py"
    host_script_path = f"/tmp/{script_filename}"
    container_script_path = f"/root/{script_filename}"
    
    print("正在创建安装脚本...")
    
    # 通过 SFTP 上传脚本到主机
    sftp = ssh.open_sftp()
    try:
        with sftp.file(host_script_path, 'w') as f:
            f.write(install_script)
        print(f"✅ 脚本已上传到主机: {host_script_path}")
    finally:
        sftp.close()
    
    # 复制脚本到容器
    copy_cmd = f'docker cp {host_script_path} {container_id}:{container_script_path}'
    stdin, stdout, stderr = ssh.exec_command(copy_cmd, timeout=10)
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        err = stderr.read().decode('utf-8', errors='ignore')
        print(f"❌ 复制脚本到容器失败: {err}")
        return False
    
    # 执行安装脚本
    print("正在执行安装脚本...")
    cmd = f'docker exec {container_id} bash -c "source /root/.bashrc && python3 {container_script_path}"'
    
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    
    # 清理临时文件
    cleanup_cmd1 = f'docker exec {container_id} rm -f {container_script_path}'
    cleanup_cmd2 = f'rm -f {host_script_path}'
    ssh.exec_command(cleanup_cmd1, timeout=5)
    ssh.exec_command(cleanup_cmd2, timeout=5)
    
    print("\n安装输出:")
    print("-" * 60)
    if out:
        print(out)
    if err:
        print("错误输出:")
        print(err)
    print("-" * 60)
    
    return exit_code == 0


def verify_installation(ssh: paramiko.SSHClient, container_id: str) -> bool:
    """验证安装是否成功（通过导入测试）"""
    print("\n" + "="*60)
    print("步骤 7: 验证安装")
    print("="*60)
    
    # 构建验证脚本
    verify_script = '''import sys
try:
    import paho.mqtt.client as mqtt
    print("✅ paho.mqtt 导入成功")
    print(f"   模块路径: {mqtt.__file__}")
    print(f"   版本信息: {getattr(mqtt, '__version__', 'unknown')}")
    sys.exit(0)
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)
except Exception as e:
    print(f"⚠️  导入时出错: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
'''
    
    verify_script_filename = "verify_paho.py"
    host_verify_path = f"/tmp/{verify_script_filename}"
    container_verify_path = f"/root/{verify_script_filename}"
    
    # 上传验证脚本到主机
    sftp = ssh.open_sftp()
    try:
        with sftp.file(host_verify_path, 'w') as f:
            f.write(verify_script)
    finally:
        sftp.close()
    
    # 复制到容器
    copy_cmd = f'docker cp {host_verify_path} {container_id}:{container_verify_path}'
    stdin, stdout, stderr = ssh.exec_command(copy_cmd, timeout=10)
    
    # 执行验证脚本
    cmd = f'docker exec {container_id} bash -c "source /root/.bashrc && python3 {container_verify_path}"'
    
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    
    # 清理临时文件
    cleanup_cmd1 = f'docker exec {container_id} rm -f {container_verify_path}'
    cleanup_cmd2 = f'rm -f {host_verify_path}'
    ssh.exec_command(cleanup_cmd1, timeout=5)
    ssh.exec_command(cleanup_cmd2, timeout=5)
    
    print("\n验证输出:")
    print("-" * 60)
    if out:
        print(out)
    if err:
        print("错误输出:")
        print(err)
    print("-" * 60)
    
    return exit_code == 0


def cleanup(ssh: paramiko.SSHClient, container_id: str, remote_path: str, container_path: str):
    """清理临时文件"""
    print("\n" + "="*60)
    print("步骤 8: 清理临时文件")
    print("="*60)
    
    try:
        # 删除容器内文件
        cmd1 = f'docker exec {container_id} rm -f {container_path}'
        ssh.exec_command(cmd1, timeout=5)
        
        # 删除宿主机文件
        cmd2 = f"rm -f {remote_path}"
        ssh.exec_command(cmd2, timeout=5)
        
        print("✅ 临时文件已清理")
    except Exception as e:
        print(f"⚠️  清理时出错（可忽略）: {e}")


def main():
    """主流程"""
    print("\n" + "="*60)
    print("ROS 2 容器环境设置工具")
    print("离线安装 paho-mqtt（无需 pip）")
    print("="*60)
    
    ssh = None
    remote_path = None
    container_path = None
    
    try:
        # 1. 查找 wheel 文件
        wheel_file = find_wheel_file()
        if not wheel_file:
            return 1
        
        # 2. SSH 连接
        ssh = connect_ssh()
        
        # 3. 查找容器
        container_id = find_container(ssh)
        
        # 4. 上传文件
        remote_path = upload_wheel_file(ssh, wheel_file)
        
        # 5. 复制到容器
        container_path = copy_to_container(ssh, container_id, remote_path)
        
        # 6. 手动提取安装（无需 pip）
        success = force_install_no_pip(ssh, container_id, container_path)
        
        if not success:
            print("\n" + "="*60)
            print("❌ 安装失败")
            print("="*60)
            return 1
        
        # 7. 验证安装
        if not verify_installation(ssh, container_id):
            print("\n" + "="*60)
            print("⚠️  验证失败，但文件可能已安装")
            print("="*60)
        
        # 8. 清理临时文件
        cleanup(ssh, container_id, remote_path, container_path)
        
        # 完成
        print("\n" + "="*60)
        print("✅ 环境设置完成")
        print("="*60)
        print("\n现在可以运行 MQTT 桥接节点了:")
        print("  python main.py")
        print("\n或运行测试脚本验证连通性:")
        print("  python test/test_ros_mqtt_connectivity.py")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⚠️  操作被用户中断")
        return 1
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if ssh:
            ssh.close()
            print("\n✅ SSH 连接已关闭")


if __name__ == "__main__":
    sys.exit(main())
