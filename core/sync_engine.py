# -*- coding: utf-8 -*-
"""
文件同步引擎
支持本地文件系统、FTP、SFTP 的文件同步
参考 FreeFileSync 设计
"""
import os
import hashlib
import fnmatch
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Callable, Generator
from enum import Enum
from pathlib import Path

from .models import (
    ConnectionConfig, ConnectionType, SyncConfig, 
    SyncMode, CompareMethod, SyncFilterRule
)


class FileAction(Enum):
    """文件操作类型"""
    COPY_TO_TARGET = "copy_to_target"      # 复制到目标
    COPY_TO_SOURCE = "copy_to_source"      # 复制到源（双向同步）
    UPDATE_TARGET = "update_target"         # 更新目标
    UPDATE_SOURCE = "update_source"         # 更新源（双向同步）
    DELETE_TARGET = "delete_target"         # 删除目标多余文件
    DELETE_SOURCE = "delete_source"         # 删除源多余文件（双向同步）
    CONFLICT = "conflict"                   # 冲突
    SKIP = "skip"                           # 跳过
    EQUAL = "equal"                         # 相同，无需操作


@dataclass
class FileInfo:
    """文件信息"""
    path: str                    # 相对路径
    name: str                    # 文件名
    size: int = 0                # 文件大小（字节）
    mtime: float = 0             # 修改时间戳
    is_dir: bool = False         # 是否为目录
    hash: str = ""               # 文件哈希（按需计算）

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        if isinstance(other, FileInfo):
            return self.path == other.path
        return False


@dataclass
class SyncItem:
    """同步项"""
    source_file: Optional[FileInfo] = None
    target_file: Optional[FileInfo] = None
    action: FileAction = FileAction.SKIP
    reason: str = ""             # 操作原因说明

    @property
    def relative_path(self) -> str:
        if self.source_file:
            return self.source_file.path
        elif self.target_file:
            return self.target_file.path
        return ""

    @property
    def is_dir(self) -> bool:
        if self.source_file:
            return self.source_file.is_dir
        elif self.target_file:
            return self.target_file.is_dir
        return False


@dataclass
class SyncResult:
    """同步结果"""
    success: bool = True
    total_files: int = 0
    copied_files: int = 0
    updated_files: int = 0
    deleted_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    total_bytes: int = 0
    transferred_bytes: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    # 详细操作记录：[(操作类型, 文件路径, 是否成功, 字节数)]
    details: List[tuple] = field(default_factory=list)
    
    @property
    def duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0


class FileConnector(ABC):
    """文件连接器抽象基类"""
    
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._connected = False
    
    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        pass
    
    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass
    
    @abstractmethod
    def list_files(self, path: str = "") -> List[FileInfo]:
        """列出目录下的文件"""
        pass
    
    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """读取文件内容"""
        pass
    
    @abstractmethod
    def write_file(self, path: str, data: bytes):
        """写入文件"""
        pass
    
    @abstractmethod
    def delete_file(self, path: str):
        """删除文件"""
        pass
    
    @abstractmethod
    def delete_dir(self, path: str):
        """删除目录"""
        pass
    
    @abstractmethod
    def mkdir(self, path: str):
        """创建目录"""
        pass
    
    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        pass
    
    @abstractmethod
    def get_file_info(self, path: str) -> Optional[FileInfo]:
        """获取文件信息"""
        pass
    
    def calculate_hash(self, path: str) -> str:
        """计算文件 MD5 哈希"""
        data = self.read_file(path)
        return hashlib.md5(data).hexdigest()
    
    @property
    def is_connected(self) -> bool:
        return self._connected


class LocalConnector(FileConnector):
    """本地文件系统连接器"""
    
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.base_path = config.path
    
    def connect(self) -> bool:
        if os.path.exists(self.base_path):
            self._connected = True
            return True
        # 尝试创建目录
        try:
            os.makedirs(self.base_path, exist_ok=True)
            self._connected = True
            return True
        except OSError:
            return False
    
    def disconnect(self):
        self._connected = False
    
    def _full_path(self, path: str) -> str:
        """获取完整路径"""
        if path:
            return os.path.join(self.base_path, path)
        return self.base_path
    
    def list_files(self, path: str = "") -> List[FileInfo]:
        """递归列出所有文件"""
        files = []
        full_path = self._full_path(path)
        
        if not os.path.exists(full_path):
            return files
        
        for entry in os.scandir(full_path):
            rel_path = os.path.join(path, entry.name) if path else entry.name
            rel_path = rel_path.replace('\\', '/')  # 统一使用正斜杠
            
            stat = entry.stat()
            file_info = FileInfo(
                path=rel_path,
                name=entry.name,
                size=stat.st_size if not entry.is_dir() else 0,
                mtime=stat.st_mtime,
                is_dir=entry.is_dir()
            )
            files.append(file_info)
            
            # 递归处理子目录
            if entry.is_dir():
                files.extend(self.list_files(rel_path))
        
        return files
    
    def read_file(self, path: str) -> bytes:
        full_path = self._full_path(path)
        with open(full_path, 'rb') as f:
            return f.read()
    
    def write_file(self, path: str, data: bytes):
        full_path = self._full_path(path)
        # 确保父目录存在
        parent_dir = os.path.dirname(full_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(data)
    
    def delete_file(self, path: str):
        full_path = self._full_path(path)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            os.remove(full_path)
    
    def delete_dir(self, path: str):
        full_path = self._full_path(path)
        if os.path.exists(full_path) and os.path.isdir(full_path):
            import shutil
            shutil.rmtree(full_path)
    
    def mkdir(self, path: str):
        full_path = self._full_path(path)
        os.makedirs(full_path, exist_ok=True)
    
    def exists(self, path: str) -> bool:
        return os.path.exists(self._full_path(path))
    
    def get_file_info(self, path: str) -> Optional[FileInfo]:
        full_path = self._full_path(path)
        if not os.path.exists(full_path):
            return None
        stat = os.stat(full_path)
        return FileInfo(
            path=path,
            name=os.path.basename(path),
            size=stat.st_size if os.path.isfile(full_path) else 0,
            mtime=stat.st_mtime,
            is_dir=os.path.isdir(full_path)
        )
    
    def copy_file(self, src_path: str, dst_connector: 'FileConnector', dst_path: str,
                  progress_callback: Callable[[int, int], None] = None):
        """复制文件到目标连接器"""
        data = self.read_file(src_path)
        dst_connector.write_file(dst_path, data)
        if progress_callback:
            progress_callback(len(data), len(data))


class FTPConnector(FileConnector):
    """FTP 连接器"""
    
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.ftp = None
        self.base_path = config.path or '/'
    
    def connect(self) -> bool:
        try:
            from ftplib import FTP
            self.ftp = FTP()
            self.ftp.connect(self.config.host, self.config.port, timeout=self.config.timeout)
            self.ftp.login(self.config.username, self.config.password)
            if self.config.passive_mode:
                self.ftp.set_pasv(True)
            self._connected = True
            return True
        except Exception as e:
            print(f"FTP 连接失败: {e}")
            return False
    
    def disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                pass
        self._connected = False
    
    def _full_path(self, path: str) -> str:
        if path:
            return f"{self.base_path.rstrip('/')}/{path}"
        return self.base_path
    
    def list_files(self, path: str = "") -> List[FileInfo]:
        files = []
        full_path = self._full_path(path)
        
        try:
            items = []
            self.ftp.cwd(full_path)
            self.ftp.retrlines('MLSD', lambda x: items.append(x))
            
            for item in items:
                parts = item.split(';')
                name = parts[-1].strip()
                if name in ['.', '..']:
                    continue
                
                facts = {}
                for part in parts[:-1]:
                    if '=' in part:
                        key, val = part.split('=', 1)
                        facts[key.lower()] = val
                
                rel_path = f"{path}/{name}" if path else name
                is_dir = facts.get('type', '').lower() == 'dir'
                size = int(facts.get('size', 0)) if not is_dir else 0
                
                file_info = FileInfo(
                    path=rel_path,
                    name=name,
                    size=size,
                    mtime=0,  # FTP 时间解析较复杂，简化处理
                    is_dir=is_dir
                )
                files.append(file_info)
                
                if is_dir:
                    files.extend(self.list_files(rel_path))
        except Exception as e:
            print(f"FTP 列目录失败: {e}")
        
        return files
    
    def read_file(self, path: str) -> bytes:
        from io import BytesIO
        full_path = self._full_path(path)
        buffer = BytesIO()
        self.ftp.retrbinary(f'RETR {full_path}', buffer.write)
        return buffer.getvalue()
    
    def write_file(self, path: str, data: bytes):
        from io import BytesIO
        full_path = self._full_path(path)
        # 确保父目录存在
        parent = '/'.join(full_path.split('/')[:-1])
        if parent:
            self._ensure_dir(parent)
        buffer = BytesIO(data)
        self.ftp.storbinary(f'STOR {full_path}', buffer)
    
    def _ensure_dir(self, path: str):
        """确保目录存在"""
        parts = path.split('/')
        current = ''
        for part in parts:
            if not part:
                continue
            current = f"{current}/{part}"
            try:
                self.ftp.mkd(current)
            except:
                pass  # 目录可能已存在
    
    def delete_file(self, path: str):
        full_path = self._full_path(path)
        self.ftp.delete(full_path)
    
    def delete_dir(self, path: str):
        full_path = self._full_path(path)
        self.ftp.rmd(full_path)
    
    def mkdir(self, path: str):
        full_path = self._full_path(path)
        self._ensure_dir(full_path)
    
    def exists(self, path: str) -> bool:
        full_path = self._full_path(path)
        try:
            self.ftp.size(full_path)
            return True
        except:
            try:
                self.ftp.cwd(full_path)
                return True
            except:
                return False
    
    def get_file_info(self, path: str) -> Optional[FileInfo]:
        full_path = self._full_path(path)
        try:
            size = self.ftp.size(full_path)
            return FileInfo(
                path=path,
                name=path.split('/')[-1],
                size=size or 0,
                mtime=0,
                is_dir=False
            )
        except:
            return None


class SFTPConnector(FileConnector):
    """SFTP 连接器"""
    
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.sftp = None
        self.transport = None
        self.base_path = config.path or '/'
    
    def connect(self) -> bool:
        try:
            import paramiko
            self.transport = paramiko.Transport((self.config.host, self.config.port))
            
            if self.config.private_key_path:
                # 使用私钥认证
                key = paramiko.RSAKey.from_private_key_file(self.config.private_key_path)
                self.transport.connect(username=self.config.username, pkey=key)
            else:
                # 使用密码认证
                self.transport.connect(username=self.config.username, password=self.config.password)
            
            self.sftp = paramiko.SFTPClient.from_transport(self.transport)
            self._connected = True
            return True
        except ImportError:
            print("SFTP 需要安装 paramiko: pip install paramiko")
            return False
        except Exception as e:
            print(f"SFTP 连接失败: {e}")
            return False
    
    def disconnect(self):
        if self.sftp:
            self.sftp.close()
        if self.transport:
            self.transport.close()
        self._connected = False
    
    def _full_path(self, path: str) -> str:
        if path:
            return f"{self.base_path.rstrip('/')}/{path}"
        return self.base_path
    
    def list_files(self, path: str = "") -> List[FileInfo]:
        files = []
        full_path = self._full_path(path)
        
        try:
            for attr in self.sftp.listdir_attr(full_path):
                if attr.filename in ['.', '..']:
                    continue
                
                rel_path = f"{path}/{attr.filename}" if path else attr.filename
                is_dir = attr.st_mode is not None and (attr.st_mode & 0o40000) != 0
                
                file_info = FileInfo(
                    path=rel_path,
                    name=attr.filename,
                    size=attr.st_size or 0,
                    mtime=attr.st_mtime or 0,
                    is_dir=is_dir
                )
                files.append(file_info)
                
                if is_dir:
                    files.extend(self.list_files(rel_path))
        except Exception as e:
            print(f"SFTP 列目录失败: {e}")
        
        return files
    
    def read_file(self, path: str) -> bytes:
        full_path = self._full_path(path)
        with self.sftp.open(full_path, 'rb') as f:
            return f.read()
    
    def write_file(self, path: str, data: bytes):
        full_path = self._full_path(path)
        # 确保父目录存在
        parent = '/'.join(full_path.split('/')[:-1])
        if parent:
            self._ensure_dir(parent)
        with self.sftp.open(full_path, 'wb') as f:
            f.write(data)
    
    def _ensure_dir(self, path: str):
        """确保目录存在"""
        parts = path.split('/')
        current = ''
        for part in parts:
            if not part:
                continue
            current = f"{current}/{part}"
            try:
                self.sftp.mkdir(current)
            except:
                pass  # 目录可能已存在
    
    def delete_file(self, path: str):
        full_path = self._full_path(path)
        self.sftp.remove(full_path)
    
    def delete_dir(self, path: str):
        full_path = self._full_path(path)
        self.sftp.rmdir(full_path)
    
    def mkdir(self, path: str):
        full_path = self._full_path(path)
        self._ensure_dir(full_path)
    
    def exists(self, path: str) -> bool:
        full_path = self._full_path(path)
        try:
            self.sftp.stat(full_path)
            return True
        except:
            return False
    
    def get_file_info(self, path: str) -> Optional[FileInfo]:
        full_path = self._full_path(path)
        try:
            attr = self.sftp.stat(full_path)
            is_dir = attr.st_mode is not None and (attr.st_mode & 0o40000) != 0
            return FileInfo(
                path=path,
                name=path.split('/')[-1],
                size=attr.st_size or 0,
                mtime=attr.st_mtime or 0,
                is_dir=is_dir
            )
        except:
            return None


def create_connector(config: ConnectionConfig) -> FileConnector:
    """根据配置创建连接器"""
    if config.type == ConnectionType.LOCAL:
        return LocalConnector(config)
    elif config.type == ConnectionType.FTP:
        return FTPConnector(config)
    elif config.type == ConnectionType.SFTP:
        return SFTPConnector(config)
    else:
        raise ValueError(f"不支持的连接类型: {config.type}")


class FileComparator:
    """文件比较器"""
    
    def __init__(self, config: SyncConfig):
        self.config = config
    
    def compare(self, source_files: List[FileInfo], target_files: List[FileInfo],
                source_connector: FileConnector, target_connector: FileConnector) -> List[SyncItem]:
        """比较源和目标文件列表，生成同步项"""
        sync_items = []
        
        # 建立目标文件索引
        target_map = {f.path: f for f in target_files if not f.is_dir}
        source_map = {f.path: f for f in source_files if not f.is_dir}
        
        # 处理源文件
        for src_file in source_files:
            if src_file.is_dir:
                continue
            
            # 应用过滤规则
            if not self._should_include(src_file):
                continue
            
            tgt_file = target_map.get(src_file.path)
            
            if tgt_file is None:
                # 目标不存在，需要复制
                sync_items.append(SyncItem(
                    source_file=src_file,
                    target_file=None,
                    action=FileAction.COPY_TO_TARGET,
                    reason="目标不存在"
                ))
            else:
                # 两边都存在，比较差异
                action, reason = self._compare_files(
                    src_file, tgt_file, source_connector, target_connector
                )
                sync_items.append(SyncItem(
                    source_file=src_file,
                    target_file=tgt_file,
                    action=action,
                    reason=reason
                ))
        
        # 处理目标端多余的文件
        if self.config.sync_mode == SyncMode.MIRROR and self.config.delete_extra:
            for tgt_path, tgt_file in target_map.items():
                if tgt_path not in source_map:
                    if self._should_include(tgt_file):
                        sync_items.append(SyncItem(
                            source_file=None,
                            target_file=tgt_file,
                            action=FileAction.DELETE_TARGET,
                            reason="源端不存在"
                        ))
        
        # 双向同步：处理目标端新增的文件
        if self.config.sync_mode == SyncMode.TWO_WAY:
            for tgt_path, tgt_file in target_map.items():
                if tgt_path not in source_map:
                    if self._should_include(tgt_file):
                        sync_items.append(SyncItem(
                            source_file=None,
                            target_file=tgt_file,
                            action=FileAction.COPY_TO_SOURCE,
                            reason="源端不存在（双向同步）"
                        ))
        
        return sync_items
    
    def _should_include(self, file_info: FileInfo) -> bool:
        """检查文件是否应该包含在同步中"""
        filter_rule = self.config.filter_rule

        # 检查隐藏文件
        if not filter_rule.include_hidden and file_info.name.startswith('.'):
            return False

        # 检查排除目录
        for exclude_dir in filter_rule.exclude_dirs:
            if exclude_dir in file_info.path.split('/'):
                return False

        # 检查排除模式
        for pattern in filter_rule.exclude_patterns:
            if fnmatch.fnmatch(file_info.name, pattern):
                return False

        # 检查包含模式（如果有的话）
        if filter_rule.include_patterns:
            matched = False
            for pattern in filter_rule.include_patterns:
                if fnmatch.fnmatch(file_info.name, pattern):
                    matched = True
                    break
            if not matched:
                return False

        # 检查文件大小
        if filter_rule.min_size > 0 and file_info.size < filter_rule.min_size:
            return False
        if filter_rule.max_size > 0 and file_info.size > filter_rule.max_size:
            return False

        # 检查时间过滤（仅对文件，不对目录）
        if not file_info.is_dir and file_info.mtime > 0:
            time_range = filter_rule.get_time_range()
            if time_range[0] is not None or time_range[1] is not None:
                start_dt, end_dt = time_range
                file_dt = datetime.fromtimestamp(file_info.mtime)

                if start_dt is not None and file_dt < start_dt:
                    return False
                if end_dt is not None and file_dt > end_dt:
                    return False

        return True
    
    def _compare_files(self, src: FileInfo, tgt: FileInfo,
                       src_conn: FileConnector, tgt_conn: FileConnector) -> tuple:
        """比较两个文件，返回 (action, reason)"""
        method = self.config.compare_method
        
        if method == CompareMethod.SIZE:
            if src.size != tgt.size:
                return self._resolve_difference(src, tgt, "大小不同")
            return FileAction.EQUAL, "大小相同"
        
        elif method == CompareMethod.TIME:
            # 允许 2 秒的时间误差
            if abs(src.mtime - tgt.mtime) > 2:
                return self._resolve_difference(src, tgt, "时间不同")
            return FileAction.EQUAL, "时间相同"
        
        elif method == CompareMethod.TIME_SIZE:
            if src.size != tgt.size:
                return self._resolve_difference(src, tgt, "大小不同")
            if abs(src.mtime - tgt.mtime) > 2:
                return self._resolve_difference(src, tgt, "时间不同")
            return FileAction.EQUAL, "时间和大小相同"
        
        elif method == CompareMethod.HASH:
            src_hash = src_conn.calculate_hash(src.path)
            tgt_hash = tgt_conn.calculate_hash(tgt.path)
            if src_hash != tgt_hash:
                return self._resolve_difference(src, tgt, "内容不同")
            return FileAction.EQUAL, "内容相同"
        
        return FileAction.SKIP, "未知比较方式"
    
    def _resolve_difference(self, src: FileInfo, tgt: FileInfo, reason: str) -> tuple:
        """解决文件差异"""
        mode = self.config.sync_mode
        
        if mode == SyncMode.MIRROR or mode == SyncMode.BACKUP:
            # 镜像/备份模式：源覆盖目标
            return FileAction.UPDATE_TARGET, reason
        
        elif mode == SyncMode.UPDATE:
            # 更新模式：只更新较新的
            if src.mtime > tgt.mtime:
                return FileAction.UPDATE_TARGET, f"{reason}，源较新"
            return FileAction.SKIP, f"{reason}，目标较新或相同"
        
        elif mode == SyncMode.TWO_WAY:
            # 双向同步：根据冲突策略处理
            resolution = self.config.conflict_resolution
            if resolution == "source":
                return FileAction.UPDATE_TARGET, f"{reason}，源优先"
            elif resolution == "target":
                return FileAction.UPDATE_SOURCE, f"{reason}，目标优先"
            elif resolution == "newer":
                if src.mtime > tgt.mtime:
                    return FileAction.UPDATE_TARGET, f"{reason}，源较新"
                elif tgt.mtime > src.mtime:
                    return FileAction.UPDATE_SOURCE, f"{reason}，目标较新"
                return FileAction.SKIP, f"{reason}，时间相同"
            else:  # skip
                return FileAction.CONFLICT, f"{reason}，冲突"
        
        return FileAction.SKIP, reason

def create_connector(config: ConnectionConfig) -> FileConnector:
    """根据配置创建对应的连接器"""
    if config.type == ConnectionType.LOCAL:
        return LocalConnector(config)
    elif config.type == ConnectionType.FTP:
        return FTPConnector(config)
    elif config.type == ConnectionType.SFTP:
        return SFTPConnector(config)
    else:
        raise ValueError(f"不支持的连接类型: {config.type}")


class SyncEngine:
    """文件同步引擎 - 支持多线程"""

    def __init__(self, config: SyncConfig, thread_count: int = 4):
        self.config = config
        self.thread_count = max(1, min(thread_count, 16))  # 限制 1-16 线程
        self.source_connector: Optional[FileConnector] = None
        self.target_connector: Optional[FileConnector] = None
        self._cancel_flag = False
        self._progress_callback: Optional[Callable[[str, int, int], None]] = None
        self._file_completed_callback: Optional[Callable[[str, str, bool, int], None]] = None
        self._lock = threading.Lock()
        self._current_file = ""
        self._processed_count = 0
        self._transferred_bytes = 0  # 追踪传输的字节数

    def set_progress_callback(self, callback: Callable[[str, int, int], None]):
        """设置进度回调: callback(message, current, total)"""
        self._progress_callback = callback

    def set_file_completed_callback(self, callback: Callable[[str, str, bool, int], None]):
        """设置文件完成回调: callback(file_path, action, success, bytes_transferred)"""
        self._file_completed_callback = callback

    def cancel(self):
        """取消同步"""
        self._cancel_flag = True
    
    def connect(self) -> tuple[bool, str]:
        """建立连接"""
        try:
            self.source_connector = create_connector(self.config.source)
            if not self.source_connector.connect():
                return False, "源端连接失败"
            
            self.target_connector = create_connector(self.config.target)
            if not self.target_connector.connect():
                self.source_connector.disconnect()
                return False, "目标端连接失败"
            
            return True, "连接成功"
        except Exception as e:
            return False, f"连接失败: {e}"
    
    def disconnect(self):
        """断开连接"""
        if self.source_connector:
            self.source_connector.disconnect()
        if self.target_connector:
            self.target_connector.disconnect()
    
    def _should_include(self, file_info: FileInfo) -> bool:
        """检查文件是否应该包含在同步中"""
        filter_rule = self.config.filter_rule

        # 检查是否为隐藏文件
        if not filter_rule.include_hidden and file_info.name.startswith('.'):
            return False

        # 检查排除目录
        if file_info.is_dir:
            if file_info.name in filter_rule.exclude_dirs:
                return False

        # 检查文件大小限制
        if not file_info.is_dir:
            if filter_rule.min_size > 0 and file_info.size < filter_rule.min_size:
                return False
            if filter_rule.max_size > 0 and file_info.size > filter_rule.max_size:
                return False

        # 检查包含模式
        if filter_rule.include_patterns and not file_info.is_dir:
            matched = any(fnmatch.fnmatch(file_info.name, p) for p in filter_rule.include_patterns)
            if not matched:
                return False

        # 检查排除模式
        if filter_rule.exclude_patterns:
            if any(fnmatch.fnmatch(file_info.name, p) for p in filter_rule.exclude_patterns):
                return False

        # 检查时间过滤（仅对文件，不对目录）
        if not file_info.is_dir and file_info.mtime > 0:
            time_range = filter_rule.get_time_range()
            if time_range[0] is not None or time_range[1] is not None:
                start_dt, end_dt = time_range
                file_dt = datetime.fromtimestamp(file_info.mtime)

                if start_dt is not None and file_dt < start_dt:
                    return False
                if end_dt is not None and file_dt > end_dt:
                    return False

        return True
    
    def _compare_files(self, source: FileInfo, target: FileInfo) -> bool:
        """比较两个文件是否相同，返回 True 表示相同"""
        method = self.config.compare_method
        
        if method == CompareMethod.SIZE:
            return source.size == target.size
        elif method == CompareMethod.TIME:
            # 允许 2 秒的时间差（不同文件系统精度不同）
            return abs(source.mtime - target.mtime) < 2
        elif method == CompareMethod.TIME_SIZE:
            return source.size == target.size and abs(source.mtime - target.mtime) < 2
        elif method == CompareMethod.HASH:
            src_hash = self.source_connector.calculate_hash(source.path)
            tgt_hash = self.target_connector.calculate_hash(target.path)
            return src_hash == tgt_hash
        
        return False

    
    def compare(self) -> List[SyncItem]:
        """比较源和目标，返回同步项列表"""
        import logging
        logger = logging.getLogger(__name__)

        if not self.source_connector or not self.target_connector:
            return []

        # 获取文件列表
        source_files = self.source_connector.list_files()
        target_files = self.target_connector.list_files()

        # 调试：打印过滤规则
        if self.config.filter_rule:
            logger.debug(f"过滤规则 - 包含模式: {self.config.filter_rule.include_patterns}")
            logger.debug(f"过滤规则 - 排除模式: {self.config.filter_rule.exclude_patterns}")
            logger.debug(f"过滤规则 - 排除目录: {self.config.filter_rule.exclude_dirs}")

        logger.debug(f"源文件数量: {len(source_files)}, 目标文件数量: {len(target_files)}")

        # 使用比较器
        comparator = FileComparator(self.config)
        return comparator.compare(
            source_files, target_files,
            self.source_connector, self.target_connector
        )
    
    def execute(self, sync_items: List[SyncItem] = None) -> SyncResult:
        """执行同步 - 单线程顺序执行（避免SFTP连接的线程安全问题）"""
        import logging
        logger = logging.getLogger(__name__)

        result = SyncResult()
        self._cancel_flag = False
        self._processed_count = 0
        self._transferred_bytes = 0  # 重置传输字节数

        if not self.source_connector or not self.target_connector:
            result.success = False
            result.errors.append("未建立连接")
            return result

        # 如果没有提供同步项，先进行比较
        if sync_items is None:
            sync_items = self.compare()

        logger.info(f"比较结果: 共 {len(sync_items)} 个文件项")
        for item in sync_items:
            logger.debug(f"  - {item.action.name}: {item.relative_path}")

        # 记录所有检查过的文件（包括相同的）
        for item in sync_items:
            if item.action == FileAction.EQUAL:
                result.details.append(('已同步', item.relative_path, True, 0))
                result.skipped_files += 1
            elif item.action == FileAction.SKIP:
                result.details.append(('跳过', item.relative_path, True, 0))
                result.skipped_files += 1
            elif item.action == FileAction.CONFLICT:
                result.details.append(('冲突', item.relative_path, False, 0))

        # 过滤掉不需要操作的项
        items_to_process = [
            item for item in sync_items
            if item.action not in (FileAction.EQUAL, FileAction.SKIP, FileAction.CONFLICT)
        ]

        result.total_files = len(items_to_process)
        logger.info(f"开始同步，共 {result.total_files} 个文件需要处理，{len(sync_items)} 个文件已检查")

        if result.total_files == 0:
            result.end_time = datetime.now()
            return result

        # 单线程顺序执行（SFTP连接不是线程安全的）
        for item in items_to_process:
            if self._cancel_flag:
                result.errors.append("用户取消")
                break

            self._processed_count += 1

            # 进度回调
            if self._progress_callback:
                self._progress_callback(
                    f"处理: {item.relative_path}",
                    self._processed_count,
                    result.total_files
                )

            try:
                action = item.action
                bytes_transferred = 0
                action_name = ""
                file_path = item.relative_path

                if action == FileAction.COPY_TO_TARGET:
                    action_name = "复制"
                    logger.debug(f"复制到目标: {item.source_file.path}")
                    data = self.source_connector.read_file(item.source_file.path)
                    self.target_connector.write_file(item.source_file.path, data)
                    bytes_transferred = len(data)
                    self._transferred_bytes += bytes_transferred  # 更新总传输字节数
                    result.copied_files += 1
                    logger.debug(f"复制完成: {item.source_file.path}, {bytes_transferred} bytes")

                elif action == FileAction.COPY_TO_SOURCE:
                    action_name = "复制(反向)"
                    logger.debug(f"复制到源: {item.target_file.path}")
                    data = self.target_connector.read_file(item.target_file.path)
                    self.source_connector.write_file(item.target_file.path, data)
                    bytes_transferred = len(data)
                    self._transferred_bytes += bytes_transferred  # 更新总传输字节数
                    result.copied_files += 1

                elif action == FileAction.UPDATE_TARGET:
                    action_name = "更新"
                    logger.debug(f"更新目标: {item.source_file.path}")
                    data = self.source_connector.read_file(item.source_file.path)
                    self.target_connector.write_file(item.source_file.path, data)
                    bytes_transferred = len(data)
                    self._transferred_bytes += bytes_transferred  # 更新总传输字节数
                    result.updated_files += 1

                elif action == FileAction.UPDATE_SOURCE:
                    action_name = "更新(反向)"
                    logger.debug(f"更新源: {item.target_file.path}")
                    data = self.target_connector.read_file(item.target_file.path)
                    self.source_connector.write_file(item.target_file.path, data)
                    bytes_transferred = len(data)
                    self._transferred_bytes += bytes_transferred  # 更新总传输字节数
                    result.updated_files += 1

                elif action == FileAction.DELETE_TARGET:
                    action_name = "删除"
                    logger.debug(f"删除目标: {item.target_file.path}")
                    if item.target_file.is_dir:
                        self.target_connector.delete_dir(item.target_file.path)
                    else:
                        self.target_connector.delete_file(item.target_file.path)
                    result.deleted_files += 1

                elif action == FileAction.DELETE_SOURCE:
                    action_name = "删除(反向)"
                    logger.debug(f"删除源: {item.source_file.path}")
                    if item.source_file.is_dir:
                        self.source_connector.delete_dir(item.source_file.path)
                    else:
                        self.source_connector.delete_file(item.source_file.path)
                    result.deleted_files += 1

                else:
                    action_name = "跳过"
                    result.skipped_files += 1

                result.transferred_bytes += bytes_transferred
                # 记录详细操作
                result.details.append((action_name, file_path, True, bytes_transferred))

                # 文件完成回调（实时更新UI）
                if self._file_completed_callback:
                    self._file_completed_callback(file_path, action_name, True, bytes_transferred)

            except Exception as e:
                logger.error(f"处理文件失败 {item.relative_path}: {e}")
                result.errors.append(f"{item.relative_path}: {e}")
                result.failed_files += 1
                # 记录失败操作
                result.details.append((action_name or "错误", item.relative_path, False, 0))

                # 文件完成回调（失败）
                if self._file_completed_callback:
                    self._file_completed_callback(item.relative_path, action_name or "错误", False, 0)

                if not self.config.continue_on_error:
                    break

        result.end_time = datetime.now()
        result.success = result.failed_files == 0
        logger.info(f"同步完成: 复制={result.copied_files}, 更新={result.updated_files}, 删除={result.deleted_files}, 失败={result.failed_files}")
        return result
    
    def _execute_item(self, item: SyncItem, result: SyncResult):
        """执行单个同步项"""
        action = item.action
        
        if action == FileAction.COPY_TO_TARGET:
            # 复制到目标
            data = self.source_connector.read_file(item.source_file.path)
            self.target_connector.write_file(item.source_file.path, data)
            result.copied_files += 1
            result.transferred_bytes += len(data)
        
        elif action == FileAction.COPY_TO_SOURCE:
            # 复制到源（双向同步）
            data = self.target_connector.read_file(item.target_file.path)
            self.source_connector.write_file(item.target_file.path, data)
            result.copied_files += 1
            result.transferred_bytes += len(data)
        
        elif action == FileAction.UPDATE_TARGET:
            # 更新目标
            data = self.source_connector.read_file(item.source_file.path)
            self.target_connector.write_file(item.source_file.path, data)
            result.updated_files += 1
            result.transferred_bytes += len(data)
        
        elif action == FileAction.UPDATE_SOURCE:
            # 更新源（双向同步）
            data = self.target_connector.read_file(item.target_file.path)
            self.source_connector.write_file(item.target_file.path, data)
            result.updated_files += 1
            result.transferred_bytes += len(data)
        
        elif action == FileAction.DELETE_TARGET:
            # 删除目标
            if item.target_file.is_dir:
                self.target_connector.delete_dir(item.target_file.path)
            else:
                self.target_connector.delete_file(item.target_file.path)
            result.deleted_files += 1
        
        elif action == FileAction.DELETE_SOURCE:
            # 删除源（双向同步）
            if item.source_file.is_dir:
                self.source_connector.delete_dir(item.source_file.path)
            else:
                self.source_connector.delete_file(item.source_file.path)
            result.deleted_files += 1
        
        else:
            result.skipped_files += 1

    def sync(self) -> SyncResult:
        """执行完整的同步流程"""
        result = SyncResult()

        # 连接
        success, msg = self.connect()
        if not success:
            result.success = False
            result.errors.append(msg)
            return result

        try:
            # 比较
            if self._progress_callback:
                self._progress_callback("正在比较文件...", 0, 0)

            sync_items = self.compare()

            # 执行
            result = self.execute(sync_items)
        finally:
            self.disconnect()

        return result
