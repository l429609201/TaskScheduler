"""
WinSCP 连接器 - 高性能 SFTP 实现
使用 WinSCP CLI 实现超高速文件传输（50-60 MB/s）
"""

import os
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Callable
import logging

from .models import FileConnector, FileInfo, ConnectionConfig

logger = logging.getLogger(__name__)


class WinSCPConnector(FileConnector):
    """WinSCP 连接器 - 使用 WinSCP CLI 实现高性能传输"""
    
    # WinSCP 便携版下载地址
    WINSCP_DOWNLOAD_URL = "https://winscp.net/download/WinSCP-6.3.5-Portable.zip"
    
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.winscp_path = None
        self.base_path = config.path or '/'
        self._cancel_flag = False
        self._transfer_callback = None
        
    def set_transfer_callback(self, callback: Optional[Callable] = None):
        """设置传输进度回调"""
        self._transfer_callback = callback
    
    def cancel(self):
        """取消当前传输"""
        self._cancel_flag = True
    
    def reset_cancel(self):
        """重置取消标志"""
        self._cancel_flag = False
    
    def _ensure_winscp(self) -> bool:
        """确保 WinSCP 可用"""
        # 1. 检查系统是否已安装 WinSCP
        system_winscp = r"C:\Program Files (x86)\WinSCP\winscp.com"
        if os.path.exists(system_winscp):
            self.winscp_path = system_winscp
            logger.info(f"使用系统 WinSCP: {system_winscp}")
            return True
        
        # 2. 检查本地便携版
        local_winscp = os.path.join(os.path.dirname(__file__), '..', 'tools', 'winscp.com')
        if os.path.exists(local_winscp):
            self.winscp_path = os.path.abspath(local_winscp)
            logger.info(f"使用本地 WinSCP: {self.winscp_path}")
            return True
        
        # 3. 下载便携版
        try:
            logger.info("WinSCP 未找到，正在下载便携版...")
            tools_dir = os.path.join(os.path.dirname(__file__), '..', 'tools')
            os.makedirs(tools_dir, exist_ok=True)
            
            zip_path = os.path.join(tools_dir, 'winscp.zip')
            
            # 下载
            urllib.request.urlretrieve(self.WINSCP_DOWNLOAD_URL, zip_path)
            
            # 解压
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tools_dir)
            
            # 删除压缩包
            os.remove(zip_path)
            
            self.winscp_path = os.path.join(tools_dir, 'winscp.com')
            logger.info(f"WinSCP 下载成功: {self.winscp_path}")
            return True
            
        except Exception as e:
            logger.error(f"下载 WinSCP 失败: {e}")
            return False
    
    def _build_session_url(self) -> str:
        """构建 WinSCP 会话 URL"""
        # sftp://user:password@host:port/path
        password = self.config.password.replace('@', '%40')  # URL 编码
        
        url = f"sftp://{self.config.username}:{password}@{self.config.host}:{self.config.port}"
        
        # 添加指纹验证（接受任何指纹）
        url += " -hostkey=*"
        
        return url
    
    def _create_script(self, commands: List[str]) -> str:
        """创建 WinSCP 脚本文件"""
        script_content = "\n".join([
            "option batch abort",
            "option confirm off",
            f"open {self._build_session_url()}",
            *commands,
            "exit"
        ])
        
        # 创建临时脚本文件
        fd, script_path = tempfile.mkstemp(suffix='.txt', text=True)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        return script_path
    
    def _run_winscp(self, commands: List[str], capture_output: bool = False) -> tuple[bool, str]:
        """运行 WinSCP 命令"""
        if not self.winscp_path:
            return False, "WinSCP 未初始化"
        
        script_path = None
        try:
            script_path = self._create_script(commands)
            
            cmd = [
                self.winscp_path,
                '/script=' + script_path,
                '/log=' + os.path.join(tempfile.gettempdir(), 'winscp.log')
            ]
            
            if capture_output:
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
                return result.returncode == 0, result.stdout
            else:
                result = subprocess.run(cmd)
                return result.returncode == 0, ""
                
        except Exception as e:
            logger.error(f"运行 WinSCP 失败: {e}")
            return False, str(e)
        finally:
            # 清理脚本文件
            if script_path and os.path.exists(script_path):
                try:
                    os.remove(script_path)
                except:
                    pass

    def connect(self) -> bool:
        """建立连接"""
        try:
            # 确保 WinSCP 可用
            if not self._ensure_winscp():
                return False

            # 测试连接
            success, _ = self._run_winscp(["pwd"])
            return success

        except Exception as e:
            logger.error(f"WinSCP 连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接（WinSCP 每次运行都是独立会话，无需断开）"""
        pass

    def _full_path(self, path: str) -> str:
        """转换为完整路径"""
        if path.startswith('/'):
            return path
        return f"{self.base_path.rstrip('/')}/{path.lstrip('/')}"

    def list_files(self, path: str = '') -> List[FileInfo]:
        """列出文件"""
        full_path = self._full_path(path) if path else self.base_path

        # 使用 ls -la 命令获取详细信息
        commands = [f'ls -la "{full_path}"']
        success, output = self._run_winscp(commands, capture_output=True)

        if not success:
            return []

        files = []
        for line in output.strip().split('\n'):
            # 解析 ls 输出（WinSCP 格式）
            # 示例：drwxr-xr-x   3 user group     4096 Jan 18 12:34 dirname
            parts = line.split()
            if len(parts) < 9:
                continue

            perms = parts[0]
            size = int(parts[4]) if parts[4].isdigit() else 0
            name = ' '.join(parts[8:])

            if name in ['.', '..']:
                continue

            is_dir = perms.startswith('d')
            file_path = f"{path}/{name}" if path else name

            files.append(FileInfo(
                path=file_path,
                name=name,
                size=size,
                mtime=0,  # WinSCP ls 不容易解析时间，暂时用0
                is_dir=is_dir
            ))

        return files

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        full_path = self._full_path(path)
        commands = [f'stat "{full_path}"']
        success, _ = self._run_winscp(commands)
        return success

    def create_directory(self, path: str) -> bool:
        """创建目录"""
        full_path = self._full_path(path)
        commands = [f'mkdir "{full_path}"']
        success, _ = self._run_winscp(commands)
        return success

    def delete_file(self, path: str) -> bool:
        """删除文件"""
        full_path = self._full_path(path)
        commands = [f'rm "{full_path}"']
        success, _ = self._run_winscp(commands)
        return success

    def delete_directory(self, path: str) -> bool:
        """删除目录"""
        full_path = self._full_path(path)
        commands = [f'rmdir "{full_path}"']
        success, _ = self._run_winscp(commands)
        return success

    def get_file_info(self, path: str) -> Optional[FileInfo]:
        """获取文件信息"""
        # 简单实现：从 list_files 的父目录中找
        parent = os.path.dirname(path)
        name = os.path.basename(path)
        files = self.list_files(parent)
        for f in files:
            if f.name == name:
                return f
        return None

    def stream_read_to_local(self, src_path: str, local_path: str, file_size: int = 0,
                             start_pos: int = 0, progress_callback=None) -> int:
        """下载文件到本地"""
        full_path = self._full_path(src_path)

        # 确保本地目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        # WinSCP 下载命令（支持断点续传）
        resume_flag = "-resumesupport=on" if start_pos > 0 else ""
        commands = [
            f'get {resume_flag} "{full_path}" "{local_path}"'
        ]

        success, _ = self._run_winscp(commands)

        if success and os.path.exists(local_path):
            transferred = os.path.getsize(local_path) - start_pos
            if progress_callback:
                progress_callback(os.path.getsize(local_path), file_size)
            return transferred

        return 0

    def stream_write_from_local(self, local_path: str, dst_path: str, file_size: int = 0,
                                 start_pos: int = 0, progress_callback=None) -> int:
        """上传本地文件"""
        full_path = self._full_path(dst_path)

        # 确保远程目录存在
        parent = '/'.join(full_path.split('/')[:-1])
        if parent:
            self._run_winscp([f'mkdir "{parent}"'])

        # WinSCP 上传命令（支持断点续传）
        resume_flag = "-resumesupport=on" if start_pos > 0 else ""
        commands = [
            f'put {resume_flag} "{local_path}" "{full_path}"'
        ]

        success, _ = self._run_winscp(commands)

        if success:
            if progress_callback:
                progress_callback(file_size, file_size)
            return file_size - start_pos

        return 0

