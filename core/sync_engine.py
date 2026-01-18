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
import time
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


def _safe_error_message(e: Exception) -> str:
    """
    安全地提取异常消息，确保返回有效的 UTF-8 字符串

    处理多种情况：
    1. 异常消息包含非 ASCII 字符（如中文错误）
    2. FTP 库返回的字节串
    3. 编码错误的字符串
    """
    try:
        msg = str(e)
        # 尝试编码为 UTF-8 验证
        msg.encode('utf-8')
        return msg
    except (UnicodeDecodeError, UnicodeEncodeError):
        # 如果有编码问题，尝试多种编码
        try:
            # 如果异常对象有 args，尝试从 args[0] 获取
            if hasattr(e, 'args') and e.args:
                raw_msg = e.args[0]

                # 如果是字节串，尝试多种编码解码
                if isinstance(raw_msg, bytes):
                    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                        try:
                            return raw_msg.decode(encoding)
                        except:
                            continue
                    # 如果所有编码都失败，使用 repr
                    return repr(raw_msg)

                # 如果是字符串，尝试重新编码
                if isinstance(raw_msg, str):
                    for encoding in ['utf-8', 'gbk', 'gb2312']:
                        try:
                            # 尝试先编码再解码
                            return raw_msg.encode('latin-1').decode(encoding)
                        except:
                            continue
        except:
            pass

        # 最后的兜底方案：使用 repr
        return repr(e)


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

    # 默认分块大小：256KB（更小的块可以更快响应取消请求）
    DEFAULT_CHUNK_SIZE = 256 * 1024

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._connected = False
        self._transfer_callback = None  # 传输进度回调

    def set_transfer_callback(self, callback):
        """设置传输进度回调: callback(bytes_transferred, total_bytes)"""
        self._transfer_callback = callback

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
        """读取文件内容（小文件用）"""
        pass

    @abstractmethod
    def write_file(self, path: str, data: bytes):
        """写入文件（小文件用）"""
        pass

    def copy_file(self, src_connector: 'FileConnector', src_path: str, dst_path: str,
                  file_size: int = 0, resume: bool = True) -> int:
        """
        从另一个连接器复制文件（支持大文件流式传输和断点续传）

        Args:
            src_connector: 源连接器
            src_path: 源文件路径
            dst_path: 目标文件路径
            file_size: 文件总大小（用于进度显示）
            resume: 是否支持断点续传

        Returns:
            实际传输的字节数
        """
        # 默认实现：使用 read_file/write_file（适用于小文件）
        data = src_connector.read_file(src_path)
        self.write_file(dst_path, data)
        return len(data)

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

    # 进度回调最小间隔（秒）- 降低 CPU 占用
    PROGRESS_INTERVAL = 0.5  # 500ms（降低UI刷新频率）

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.base_path = config.path
        self._cancel_flag = False
        self._last_progress_time = 0  # 上次进度回调时间

    def cancel(self):
        """取消当前传输"""
        self._cancel_flag = True

    def reset_cancel(self):
        """重置取消标志"""
        self._cancel_flag = False

    def _throttled_progress(self, current, total, force=False):
        """节流的进度回调，避免过于频繁的 UI 更新"""
        if self._transfer_callback is None:
            return

        import time
        now = time.time()

        # 强制更新（如传输完成）或超过间隔时间才回调
        if force or (now - self._last_progress_time) >= self.PROGRESS_INTERVAL:
            self._last_progress_time = now
            self._transfer_callback(current, total)
    
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
    
    def copy_file(self, src_connector: 'FileConnector', src_path: str, dst_path: str,
                  file_size: int = 0, resume: bool = True) -> int:
        """
        从源连接器复制文件到本地（支持大文件流式传输）
        """
        dst_full_path = self._full_path(dst_path)

        # 确保父目录存在
        parent_dir = os.path.dirname(dst_full_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # 检查是否可以断点续传
        start_pos = 0
        if resume and os.path.exists(dst_full_path):
            existing_size = os.path.getsize(dst_full_path)
            if existing_size < file_size:
                start_pos = existing_size

        # 如果源也是本地连接器，使用流式复制
        if isinstance(src_connector, LocalConnector):
            src_full_path = src_connector._full_path(src_path)
            return self._stream_copy_local(src_full_path, dst_full_path, file_size, start_pos)

        # 如果源是 SFTP，让 SFTP 连接器处理
        if hasattr(src_connector, 'stream_read_to_local'):
            return src_connector.stream_read_to_local(src_path, dst_full_path, file_size, start_pos, self._transfer_callback)

        # 回退到默认实现
        data = src_connector.read_file(src_path)
        with open(dst_full_path, 'wb') as f:
            f.write(data)
        return len(data)

    def _stream_copy_local(self, src_path: str, dst_path: str, file_size: int, start_pos: int = 0) -> int:
        """本地文件流式复制"""
        bytes_transferred = 0
        mode = 'ab' if start_pos > 0 else 'wb'

        # 重置进度时间
        self._last_progress_time = 0

        with open(src_path, 'rb') as src_f:
            if start_pos > 0:
                src_f.seek(start_pos)

            with open(dst_path, mode) as dst_f:
                while True:
                    # 检查取消标志
                    if self._cancel_flag:
                        raise InterruptedError("用户取消传输")

                    chunk = src_f.read(self.DEFAULT_CHUNK_SIZE)
                    if not chunk:
                        break
                    dst_f.write(chunk)
                    bytes_transferred += len(chunk)

                    # 使用节流回调，降低 CPU 占用
                    self._throttled_progress(start_pos + bytes_transferred, file_size)

        # 传输完成，强制更新一次进度
        self._throttled_progress(start_pos + bytes_transferred, file_size, force=True)
        return bytes_transferred


class FTPConnector(FileConnector):
    """FTP 连接器 - 支持 GBK/UTF-8 编码自动检测，优化传输性能"""

    # 优化的传输参数
    BLOCK_SIZE = 1024 * 1024  # 1MB 缓冲区（从 256KB 增加）
    SOCKET_TIMEOUT = 60  # 60 秒超时
    PROGRESS_INTERVAL = 0.1  # 进度回调最小间隔（秒）

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.ftp = None
        self.base_path = config.path or '/'
        self._encoding = 'utf-8'  # 默认编码，会自动检测
        self._cancel_flag = False  # 取消标志
        self._last_progress_time = 0  # 上次进度回调时间

    def _try_decode(self, data: bytes) -> str:
        """尝试用多种编码解码数据"""
        # 按优先级尝试不同编码
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']
        for enc in encodings:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        # 最后用 latin-1，它能解码任何字节
        return data.decode('latin-1', errors='replace')

    def _detect_encoding(self) -> str:
        """检测 FTP 服务器的编码"""
        try:
            # 尝试获取当前目录，用原始字节来检测编码
            # 先用 latin-1 获取原始字节
            self.ftp.encoding = 'latin-1'
            pwd = self.ftp.pwd()
            raw_bytes = pwd.encode('latin-1')

            # 尝试不同编码
            for enc in ['utf-8', 'gbk', 'gb2312']:
                try:
                    raw_bytes.decode(enc)
                    return enc
                except:
                    continue
            return 'utf-8'
        except:
            return 'utf-8'

    def connect(self) -> bool:
        try:
            from ftplib import FTP
            import socket

            self.ftp = FTP()
            # 先用 latin-1 连接，避免编码错误
            self.ftp.encoding = 'latin-1'
            self.ftp.connect(self.config.host, self.config.port, timeout=self.config.timeout)

            # 优化 TCP 参数（提升传输速度）
            sock = self.ftp.sock
            if sock:
                # 禁用 Nagle 算法（减少延迟）
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # 增大发送/接收缓冲区
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)  # 1MB
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)  # 1MB

            self.ftp.login(self.config.username, self.config.password)

            # 检测服务器编码
            self._encoding = self._detect_encoding()
            self.ftp.encoding = self._encoding

            # 设置为二进制传输模式（TYPE I）
            # 这样可以避免 ASCII 模式的问题，并且支持所有类型的文件
            try:
                self.ftp.voidcmd('TYPE I')
            except:
                pass  # 某些服务器可能不支持此命令

            if self.config.passive_mode:
                self.ftp.set_pasv(True)
            self._connected = True
            return True
        except Exception as e:
            print(f"FTP 连接失败: {e}")
            return False

    def _safe_ftp_command(self, cmd_func, *args, **kwargs):
        """安全执行 FTP 命令，自动处理编码问题"""
        encodings = [self._encoding, 'utf-8', 'gbk', 'gb2312', 'latin-1']
        last_error = None

        for enc in encodings:
            try:
                self.ftp.encoding = enc
                result = cmd_func(*args, **kwargs)
                self._encoding = enc  # 记住成功的编码
                return result
            except UnicodeDecodeError as e:
                last_error = e
                continue
            except UnicodeEncodeError as e:
                last_error = e
                continue

        # 所有编码都失败，抛出最后的错误
        raise last_error if last_error else Exception("编码错误")
    
    def cancel(self):
        """取消当前传输"""
        self._cancel_flag = True

    def reset_cancel(self):
        """重置取消标志"""
        self._cancel_flag = False

    def disconnect(self):
        # 先设置取消标志
        self._cancel_flag = True

        # 设置很短的超时，让正在进行的操作快速失败
        if self.ftp:
            try:
                self.ftp.sock.settimeout(0.1)  # 100ms 超时
            except:
                pass

        if self.ftp:
            try:
                self.ftp.quit()
            except:
                try:
                    self.ftp.close()
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
            use_list = False

            # 尝试 MLSD 命令
            def do_mlsd():
                self.ftp.cwd(full_path)
                self.ftp.retrlines('MLSD', lambda x: items.append(x))

            try:
                self._safe_ftp_command(do_mlsd)
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[FTP调试] 使用 MLSD 模式，获取到 {len(items)} 个项目")
                if items:
                    logger.info(f"[FTP调试] MLSD 示例数据: {items[0]}")
            except Exception as e:
                # MLSD 不支持，尝试 LIST
                err_str = str(e).lower()
                if 'mlsd' in err_str or '500' in str(e) or '502' in str(e) or '550' in str(e):
                    use_list = True
                    items = []
                    def do_list():
                        self.ftp.cwd(full_path)
                        self.ftp.retrlines('LIST', lambda x: items.append(x))
                    self._safe_ftp_command(do_list)
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"[FTP调试] 使用 LIST 模式，获取到 {len(items)} 个项目")
                    if items:
                        logger.info(f"[FTP调试] LIST 示例数据: {items[0]}")
                else:
                    raise

            if use_list:
                # 解析 LIST 输出
                import logging
                logger = logging.getLogger(__name__)

                for line in items:
                    parts = line.split()
                    if len(parts) < 9:
                        continue
                    name = ' '.join(parts[8:])
                    if name in ['.', '..']:
                        continue

                    # 调试：打印解析信息
                    logger.info(f"[FTP调试] 解析 LIST 行: {line}")
                    logger.info(f"[FTP调试] parts[5-7]: {parts[5] if len(parts) > 5 else 'N/A'}, {parts[6] if len(parts) > 6 else 'N/A'}, {parts[7] if len(parts) > 7 else 'N/A'}")

                    is_dir = line.startswith('d')
                    size = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0

                    # 尝试解析 LIST 时间 (格式: Mon DD HH:MM 或 Mon DD YYYY)
                    mtime = 0
                    try:
                        from datetime import datetime, timezone
                        month_str = parts[5]
                        day_str = parts[6]
                        time_or_year = parts[7]

                        months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                                  'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
                        month = months.get(month_str.lower(), 1)
                        day = int(day_str)

                        if ':' in time_or_year:
                            # 格式: HH:MM，年份为当前年
                            hour, minute = map(int, time_or_year.split(':'))
                            year = datetime.now().year
                            dt_utc = datetime(year, month, day, hour, minute)
                            # 如果日期在未来，说明是去年
                            if dt_utc > datetime.now():
                                dt_utc = datetime(year - 1, month, day, hour, minute)
                        else:
                            # 格式: YYYY
                            year = int(time_or_year)
                            dt_utc = datetime(year, month, day)

                        # 假设 FTP 返回的是 UTC 时间，转换为本地时间
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        dt_local = dt_utc.astimezone()
                        mtime = dt_local.timestamp()

                        logger.info(f"[FTP调试] 解析 UTC 时间: {dt_utc}")
                        logger.info(f"[FTP调试] 转换为本地时间: {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
                    except Exception as parse_err:
                        logger.info(f"[FTP调试] 时间解析失败: {parse_err}")
                        pass

                    rel_path = f"{path}/{name}" if path else name
                    file_info = FileInfo(
                        path=rel_path,
                        name=name,
                        size=size if not is_dir else 0,
                        mtime=mtime,
                        is_dir=is_dir
                    )
                    files.append(file_info)

                    if is_dir:
                        files.extend(self.list_files(rel_path))
            else:
                # 解析 MLSD 输出
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

                    # 解析修改时间 (MLSD 返回格式: modify=20240115123456)
                    mtime = 0
                    modify = facts.get('modify', '')
                    if modify:
                        try:
                            from datetime import datetime, timezone, timedelta
                            import logging
                            logger = logging.getLogger(__name__)

                            # 解析 FTP 时间（假设为 UTC）
                            dt_utc = datetime.strptime(modify[:14], "%Y%m%d%H%M%S")

                            # 方案 A: 假设 FTP 返回的是 UTC 时间，转换为本地时间
                            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                            dt_local = dt_utc.astimezone()  # 转换为本地时区
                            mtime = dt_local.timestamp()

                            # 调试：显示包含特定关键词的文件 + 前3个文件
                            should_debug = (len(files) < 3 or
                                          'DBFULL' in name.upper() or
                                          '202601' in name or
                                          '2026-01' in name)
                            if should_debug:
                                logger.info(f"[FTP时间调试] 文件: {name}")
                                logger.info(f"  - MLSD 原始时间: {modify[:14]}")
                                logger.info(f"  - 解析为 UTC: {dt_utc}")
                                logger.info(f"  - 转换为本地时间: {dt_local}")
                                logger.info(f"  - timestamp: {mtime}")
                                logger.info(f"  - 显示时间: {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(f"[FTP时间调试] 解析时间失败: {modify}, 错误: {e}")

                    file_info = FileInfo(
                        path=rel_path,
                        name=name,
                        size=size,
                        mtime=mtime,
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

    def stream_read_to_local(self, remote_path: str, local_path: str, file_size: int = 0,
                             start_pos: int = 0, progress_callback=None) -> int:
        """
        从 FTP 流式下载到本地文件（支持断点续传、可取消）
        """
        # 检查取消标志
        if self._cancel_flag:
            raise Exception("传输已取消")

        full_path = self._full_path(remote_path)
        bytes_transferred = 0
        mode = 'ab' if start_pos > 0 else 'wb'

        # 重置进度时间
        self._last_progress_time = 0

        # 确保使用二进制模式
        try:
            self.ftp.voidcmd('TYPE I')
        except:
            pass

        # 如果需要断点续传，发送 REST 命令
        if start_pos > 0:
            self.ftp.sendcmd(f'REST {start_pos}')

        with open(local_path, mode) as local_f:
            def callback(data):
                # 检查取消标志
                if self._cancel_flag:
                    raise Exception("传输已取消")

                nonlocal bytes_transferred
                local_f.write(data)
                chunk_size = len(data)
                bytes_transferred += chunk_size

                # 使用节流回调，降低 CPU 占用
                if progress_callback:
                    current_time = time.time()
                    if current_time - self._last_progress_time >= self.PROGRESS_INTERVAL or bytes_transferred >= file_size:
                        self._last_progress_time = current_time
                        progress_callback(start_pos + bytes_transferred, file_size)

            # RETR 命令会自动使用二进制模式，使用 1MB 缓冲区
            self.ftp.retrbinary(f'RETR {full_path}', callback, blocksize=self.BLOCK_SIZE)

        return bytes_transferred

    def stream_write_from_local(self, local_path: str, remote_path: str, file_size: int = 0,
                                 start_pos: int = 0, progress_callback=None) -> int:
        """
        从本地流式上传到 FTP（支持断点续传、可取消）
        """
        # 检查取消标志
        if self._cancel_flag:
            raise Exception("传输已取消")

        full_path = self._full_path(remote_path)
        bytes_transferred = 0

        # 确保父目录存在
        parent = '/'.join(full_path.split('/')[:-1])
        if parent:
            self._ensure_dir(parent)

        # 重置进度时间
        self._last_progress_time = 0

        # 确保使用二进制模式
        try:
            self.ftp.voidcmd('TYPE I')
        except:
            pass

        # 如果需要断点续传，使用 APPE 命令
        if start_pos > 0:
            cmd = f'APPE {full_path}'
        else:
            cmd = f'STOR {full_path}'

        with open(local_path, 'rb') as local_f:
            if start_pos > 0:
                local_f.seek(start_pos)

            # 包装读取函数以支持进度回调和取消检查
            parent_self = self

            class ProgressWrapper:
                def __init__(self, f, callback, file_size, start_pos):
                    self.f = f
                    self.callback = callback
                    self.file_size = file_size
                    self.bytes_read = start_pos
                    self.last_progress_time = 0

                def read(self, size):
                    # 检查取消标志
                    if parent_self._cancel_flag:
                        raise Exception("传输已取消")

                    data = self.f.read(size)
                    if data and self.callback:
                        self.bytes_read += len(data)
                        current_time = time.time()
                        if current_time - self.last_progress_time >= parent_self.PROGRESS_INTERVAL or self.bytes_read >= self.file_size:
                            self.last_progress_time = current_time
                            self.callback(self.bytes_read, self.file_size)
                    return data

            wrapper = ProgressWrapper(local_f, progress_callback, file_size, start_pos)
            self.ftp.storbinary(cmd, wrapper, blocksize=self.BLOCK_SIZE)  # 使用 1MB 缓冲区
            bytes_transferred = wrapper.bytes_read - start_pos

        return bytes_transferred

    def copy_file(self, src_connector: 'FileConnector', src_path: str, dst_path: str,
                  file_size: int = 0, resume: bool = True) -> int:
        """
        从源连接器复制文件到 FTP（支持大文件流式传输）
        """
        # 如果源是本地连接器，使用流式上传
        if isinstance(src_connector, LocalConnector):
            src_full_path = src_connector._full_path(src_path)

            # 检查是否可以断点续传
            start_pos = 0
            if resume:
                try:
                    full_path = self._full_path(dst_path)
                    # 获取远程文件大小（已经在连接时设置为二进制模式）
                    size = self.ftp.size(full_path)
                    if size and size < file_size:
                        start_pos = size
                except:
                    pass

            return self.stream_write_from_local(src_full_path, dst_path, file_size, start_pos, self._transfer_callback)

        # 如果源不是本地，需要通过内存中转（仅适用于小文件）
        # 对于大文件，建议使用本地中转
        data = src_connector.read_file(src_path)
        self.write_file(dst_path, data)
        return len(data)
    
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
    """SFTP 连接器 - 平衡性能与稳定性

    配置说明：
    - 高性能模式：适合稳定的内网环境
    - 平衡模式：适合大多数网络环境（默认）
    - 稳定模式：适合不稳定的外网环境
    """

    # ========== 性能配置 ==========
    #
    # 使用 paramiko 原生的 get()/put() 方法替代手动 read()/write()
    # 性能提升: ~25倍 (2 MB/s -> 50 MB/s)
    # 参考: GitHub paramiko issue #2235
    #
    # 仅保留传输层优化参数（在connect时使用）
    WINDOW_SIZE = 128 * 1024 * 1024  # 128MB 窗口大小
    MAX_PACKET_SIZE = 256 * 1024     # 256KB 最大包大小
    USE_COMPRESSION = False          # 关闭压缩，降低CPU占用

    # 其他参数
    PROGRESS_INTERVAL = 0.2  # 200ms（降低进度更新频率，减少CPU和UI刷新）
    CONNECT_TIMEOUT = 30     # 30秒连接超时
    AUTH_TIMEOUT = 30        # 30秒认证超时

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.sftp = None
        self.transport = None
        self.base_path = config.path or '/'
        self._cancel_flag = False  # 取消标志
        self._last_progress_time = 0  # 上次进度回调时间

    def cancel(self):
        """取消当前传输"""
        self._cancel_flag = True

    def reset_cancel(self):
        """重置取消标志"""
        self._cancel_flag = False

    def _throttled_progress(self, callback, current, total, force=False):
        """节流的进度回调，避免过于频繁的 UI 更新"""
        if callback is None:
            return

        import time
        now = time.time()

        # 强制更新（如传输完成）或超过间隔时间才回调
        if force or (now - self._last_progress_time) >= self.PROGRESS_INTERVAL:
            self._last_progress_time = now
            callback(current, total)
    
    def connect(self) -> bool:
        try:
            import paramiko

            # 创建 Transport 时设置优化的窗口大小和数据包大小
            self.transport = paramiko.Transport(
                (self.config.host, self.config.port),
                default_window_size=self.WINDOW_SIZE,
                default_max_packet_size=self.MAX_PACKET_SIZE
            )

            # 设置连接超时和认证超时（避免 Key-exchange timeout 错误）
            self.transport.banner_timeout = self.CONNECT_TIMEOUT
            self.transport.auth_timeout = self.AUTH_TIMEOUT

            # 设置 keepalive，防止长时间传输时连接断开
            self.transport.set_keepalive(30)

            # 压缩设置（根据 USE_COMPRESSION 配置）
            self.transport.use_compression(self.USE_COMPRESSION)

            # 加密算法设置（使用性能更好的 CTR 模式）
            try:
                self.transport.get_security_options().ciphers = (
                    'aes128-ctr',  # 性能最好
                    'aes256-ctr',
                    'aes128-cbc',
                    'aes192-ctr',
                    'aes256-ctr',
                    '3des-cbc'
                )
                # 使用更简单的密钥交换算法
                self.transport.get_security_options().key_types = (
                    'ssh-rsa',
                    'rsa-sha2-512',
                    'rsa-sha2-256',
                    'ssh-dss'
                )
            except:
                pass  # 如果设置失败，使用默认值

            if self.config.private_key_path:
                # 使用私钥认证
                key = paramiko.RSAKey.from_private_key_file(self.config.private_key_path)
                self.transport.connect(username=self.config.username, pkey=key)
            else:
                # 使用密码认证
                self.transport.connect(username=self.config.username, password=self.config.password)

            # 创建 SFTP 客户端，使用优化的窗口大小
            self.sftp = paramiko.SFTPClient.from_transport(
                self.transport,
                window_size=self.WINDOW_SIZE,
                max_packet_size=self.MAX_PACKET_SIZE
            )

            # 设置 SFTP 通道的超时时间
            channel = self.sftp.get_channel()
            if channel:
                channel.settimeout(3600)  # 1小时超时

            self._connected = True
            return True
        except ImportError:
            print("SFTP 需要安装 paramiko: pip install paramiko")
            return False
        except Exception as e:
            print(f"SFTP 连接失败: {e}")
            return False
    
    def disconnect(self):
        # 先设置取消标志
        self._cancel_flag = True

        # 设置很短的超时，让正在进行的操作快速失败
        try:
            if self.sftp:
                channel = self.sftp.get_channel()
                if channel:
                    channel.settimeout(0.1)  # 100ms 超时
        except:
            pass

        if self.sftp:
            try:
                self.sftp.close()
            except:
                pass
        if self.transport:
            try:
                self.transport.close()
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
    
    def _reconnect(self) -> bool:
        """尝试重新连接"""
        # 如果已取消，不要重连
        if self._cancel_flag:
            return False
        try:
            self.disconnect()
            return self.connect()
        except Exception as e:
            print(f"SFTP 重连失败: {e}")
            return False

    def _with_retry(self, operation, *args, max_retries=5, **kwargs):
        """带重试的操作包装器（增加重试次数和延迟）"""
        import time
        last_error = None
        for attempt in range(max_retries):
            # 如果已取消，不要重试
            if self._cancel_flag:
                raise InterruptedError("用户取消操作")
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                # 如果已取消，不要重试
                if self._cancel_flag:
                    raise InterruptedError("用户取消操作")
                error_str = str(e).lower()
                # 检查是否是连接断开的错误或网络错误
                is_network_error = any(x in error_str for x in [
                    'connection', 'socket', 'eof', 'channel', 'timeout',
                    'key-exchange', 'garbage', 'packet', 'ssh'
                ])
                if is_network_error and attempt < max_retries - 1:
                    wait_time = min(5 * (attempt + 1), 30)  # 递增等待，最多 30 秒
                    print(f"SFTP 网络错误，{wait_time}秒后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    if self._reconnect():
                        continue
                # 其他错误直接抛出
                raise
        raise last_error

    def read_file(self, path: str) -> bytes:
        full_path = self._full_path(path)

        def _read():
            with self.sftp.open(full_path, 'rb') as f:
                return f.read()

        return self._with_retry(_read)

    def write_file(self, path: str, data: bytes):
        full_path = self._full_path(path)
        # 确保父目录存在
        parent = '/'.join(full_path.split('/')[:-1])
        if parent:
            self._ensure_dir(parent)

        def _write():
            with self.sftp.open(full_path, 'wb') as f:
                f.write(data)

        self._with_retry(_write)
    
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

    def stream_read_to_local(self, src_path: str, local_path: str, file_size: int = 0,
                              start_pos: int = 0, progress_callback=None) -> int:
        """
        流式读取远程文件到本地（使用原生get方法,性能提升25倍）

        参考: GitHub paramiko issue #2235
        - 原生 sftp.get() 速度: ~50 MB/s
        - 手动 read() 循环速度: ~2 MB/s
        """
        import os
        full_path = self._full_path(src_path)
        bytes_transferred = 0
        max_retries = 3

        # 重置进度时间
        self._last_progress_time = 0

        # 确保本地目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        current_pos = start_pos

        # 创建进度回调包装器（支持节流和取消检测）
        def _progress_wrapper(transferred, total):
            nonlocal current_pos
            # 检查取消标志
            if self._cancel_flag:
                raise InterruptedError("用户取消传输")

            # 使用节流回调，降低 CPU 占用
            current_pos = start_pos + transferred
            self._throttled_progress(progress_callback, current_pos, total)

        for retry in range(max_retries):
            try:
                if start_pos > 0:
                    # 断点续传：先下载到临时文件，再追加
                    temp_path = local_path + '.sftp_resume'

                    # 使用原生 get 方法下载剩余部分
                    self.sftp.get(
                        remotepath=full_path,
                        localpath=temp_path,
                        callback=_progress_wrapper if progress_callback else None
                    )

                    # 追加到原文件
                    with open(local_path, 'ab') as dst_f:
                        with open(temp_path, 'rb') as src_f:
                            src_f.seek(start_pos)
                            data = src_f.read()
                            dst_f.write(data)
                            bytes_transferred = len(data)

                    # 删除临时文件
                    os.remove(temp_path)
                else:
                    # 全新下载：直接使用原生 get 方法
                    self.sftp.get(
                        remotepath=full_path,
                        localpath=local_path,
                        callback=_progress_wrapper if progress_callback else None
                    )

                    if file_size > 0:
                        bytes_transferred = file_size
                    elif os.path.exists(local_path):
                        bytes_transferred = os.path.getsize(local_path)

                # 传输完成，强制更新一次进度
                self._throttled_progress(progress_callback, current_pos, file_size, force=True)
                return bytes_transferred

            except InterruptedError:
                raise  # 用户取消，直接抛出
            except Exception as e:
                # 如果已取消，不要重试
                if self._cancel_flag:
                    raise InterruptedError("用户取消传输")

                error_str = str(e).lower()
                is_connection_error = any(x in error_str for x in ['connection', 'socket', 'eof', 'channel', 'timeout'])

                if is_connection_error and retry < max_retries - 1:
                    print(f"SFTP 传输中断，尝试断点续传 ({retry + 1}/{max_retries})...")
                    if os.path.exists(local_path):
                        current_pos = os.path.getsize(local_path)
                    if self._reconnect():
                        continue

                raise Exception(f"SFTP 传输失败: {e}")

        return bytes_transferred

    def stream_write_from_local(self, local_path: str, dst_path: str, file_size: int = 0,
                                 start_pos: int = 0, progress_callback=None) -> int:
        """
        流式写入本地文件到远程（使用原生put方法,性能提升25倍）

        参考: GitHub paramiko issue #2235
        - 原生 sftp.put() 速度: ~50 MB/s
        - 手动 write() 循环速度: ~2 MB/s
        """
        import os
        full_path = self._full_path(dst_path)
        bytes_transferred = 0
        max_retries = 3

        # 重置进度时间
        self._last_progress_time = 0

        # 确保远程目录存在
        parent = '/'.join(full_path.split('/')[:-1])
        if parent:
            self._ensure_dir(parent)

        current_pos = start_pos

        # 创建进度回调包装器（支持节流和取消检测）
        def _progress_wrapper(transferred, total):
            nonlocal current_pos
            # 检查取消标志
            if self._cancel_flag:
                raise InterruptedError("用户取消传输")

            # 使用节流回调，降低 CPU 占用
            current_pos = start_pos + transferred
            self._throttled_progress(progress_callback, current_pos, total)

        for retry in range(max_retries):
            try:
                if start_pos > 0:
                    # 断点续传：创建临时文件上传剩余部分
                    temp_path = local_path + '.sftp_resume'

                    # 只读取剩余部分到临时文件
                    with open(local_path, 'rb') as src_f:
                        src_f.seek(start_pos)
                        with open(temp_path, 'wb') as temp_f:
                            remaining_data = src_f.read()
                            temp_f.write(remaining_data)

                    # 使用原生 put 上传到临时远程文件
                    temp_remote = full_path + '.sftp_resume'
                    self.sftp.put(
                        localpath=temp_path,
                        remotepath=temp_remote,
                        callback=_progress_wrapper if progress_callback else None
                    )

                    # 追加到远程文件
                    with self.sftp.open(full_path, 'ab') as dst_f:
                        with self.sftp.open(temp_remote, 'rb') as src_f:
                            data = src_f.read()
                            dst_f.write(data)
                            bytes_transferred = len(data)

                    # 删除临时文件
                    os.remove(temp_path)
                    self.sftp.remove(temp_remote)
                else:
                    # 全新上传：直接使用原生 put 方法
                    self.sftp.put(
                        localpath=local_path,
                        remotepath=full_path,
                        callback=_progress_wrapper if progress_callback else None
                    )

                    if file_size > 0:
                        bytes_transferred = file_size
                    elif os.path.exists(local_path):
                        bytes_transferred = os.path.getsize(local_path)

                # 传输完成，强制更新一次进度
                self._throttled_progress(progress_callback, current_pos, file_size, force=True)
                return bytes_transferred

            except InterruptedError:
                raise
            except Exception as e:
                # 如果已取消，不要重试
                if self._cancel_flag:
                    raise InterruptedError("用户取消传输")

                error_str = str(e).lower()
                is_connection_error = any(x in error_str for x in ['connection', 'socket', 'eof', 'channel', 'timeout'])

                if is_connection_error and retry < max_retries - 1:
                    print(f"SFTP 上传中断，尝试断点续传 ({retry + 1}/{max_retries})...")
                    try:
                        attr = self.sftp.stat(full_path)
                        current_pos = attr.st_size or 0
                    except:
                        pass
                    if self._reconnect():
                        continue

                raise Exception(f"SFTP 上传失败: {e}")

        return bytes_transferred

    def copy_file(self, src_connector: 'FileConnector', src_path: str, dst_path: str,
                  file_size: int = 0, resume: bool = True) -> int:
        """
        从源连接器复制文件到 SFTP（支持大文件流式传输）
        """
        # 如果源是本地连接器，使用流式上传
        if isinstance(src_connector, LocalConnector):
            src_full_path = src_connector._full_path(src_path)

            # 检查是否可以断点续传
            start_pos = 0
            if resume:
                try:
                    full_path = self._full_path(dst_path)
                    attr = self.sftp.stat(full_path)
                    if attr.st_size and attr.st_size < file_size:
                        start_pos = attr.st_size
                except:
                    pass

            return self.stream_write_from_local(src_full_path, dst_path, file_size, start_pos, self._transfer_callback)

        # 如果源也是 SFTP，需要通过本地中转（或直接内存传输小文件）
        # 对于大文件，建议使用本地中转
        data = src_connector.read_file(src_path)
        self.write_file(dst_path, data)
        return len(data)


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
        import logging
        logger = logging.getLogger(__name__)

        sync_items = []

        # 建立目标文件索引
        target_map = {f.path: f for f in target_files if not f.is_dir}
        source_map = {f.path: f for f in source_files if not f.is_dir}

        # 调试：记录过滤统计
        total_files = 0
        filtered_out = 0

        # 处理源文件
        for src_file in source_files:
            if src_file.is_dir:
                continue

            total_files += 1

            # 应用过滤规则
            if not self._should_include(src_file):
                filtered_out += 1
                if filtered_out <= 5:  # 只记录前5个被过滤的文件
                    logger.debug(f"文件被过滤: {src_file.path}, name={src_file.name}")
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

        # 记录过滤统计
        logger.debug(f"过滤统计: 总文件数={total_files}, 被过滤={filtered_out}, 通过过滤={total_files - filtered_out}, 最终sync_items={len(sync_items)}")

        return sync_items
    
    def _should_include(self, file_info: FileInfo) -> bool:
        """检查文件是否应该包含在同步中"""
        import logging
        logger = logging.getLogger(__name__)

        filter_rule = self.config.filter_rule

        # 检查隐藏文件
        if not filter_rule.include_hidden and file_info.name.startswith('.'):
            logger.debug(f"文件被过滤(隐藏文件): {file_info.path}")
            return False

        # 检查排除目录
        for exclude_dir in filter_rule.exclude_dirs:
            if exclude_dir in file_info.path.split('/'):
                logger.debug(f"文件被过滤(排除目录 {exclude_dir}): {file_info.path}")
                return False

        # 检查排除模式
        for pattern in filter_rule.exclude_patterns:
            if fnmatch.fnmatch(file_info.name, pattern):
                logger.debug(f"文件被过滤(排除模式 {pattern}): {file_info.path}")
                return False

        # 检查包含模式（如果有的话）
        if filter_rule.include_patterns:
            # 特殊处理：如果包含模式只有 ['*']，表示包含所有文件
            if filter_rule.include_patterns == ['*']:
                pass  # 包含所有文件
            else:
                matched = False
                for pattern in filter_rule.include_patterns:
                    if fnmatch.fnmatch(file_info.name, pattern):
                        matched = True
                        break
                if not matched:
                    logger.debug(f"文件被过滤(不匹配包含模式): {file_info.path}")
                    return False

        # 检查文件大小
        if filter_rule.min_size > 0 and file_info.size < filter_rule.min_size:
            logger.debug(f"文件被过滤(小于最小大小 {filter_rule.min_size}): {file_info.path}, size={file_info.size}")
            return False
        if filter_rule.max_size > 0 and file_info.size > filter_rule.max_size:
            logger.debug(f"文件被过滤(大于最大大小 {filter_rule.max_size}): {file_info.path}, size={file_info.size}")
            return False

        # 检查时间过滤（仅对文件，不对目录）
        if not file_info.is_dir and file_info.mtime > 0:
            time_range = filter_rule.get_time_range()
            if time_range[0] is not None or time_range[1] is not None:
                start_dt, end_dt = time_range
                file_dt = datetime.fromtimestamp(file_info.mtime)

                if start_dt is not None and file_dt < start_dt:
                    logger.debug(f"文件被过滤(早于开始时间 {start_dt}): {file_info.path}, mtime={file_dt}")
                    return False
                if end_dt is not None and file_dt > end_dt:
                    logger.debug(f"文件被过滤(晚于结束时间 {end_dt}): {file_info.path}, mtime={file_dt}")
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
        self._transferred_bytes = 0  # 总传输字节数（所有线程累计）
        self._thread_bytes = {}  # 每个线程当前文件的传输字节数 {thread_id: bytes}

        # 连接池 - 为每个线程创建独立连接
        self._source_pool: List[FileConnector] = []
        self._target_pool: List[FileConnector] = []
        self._pool_lock = threading.Lock()

    def set_progress_callback(self, callback: Callable[[str, int, int], None]):
        """设置进度回调: callback(message, current, total)"""
        self._progress_callback = callback

    def set_file_completed_callback(self, callback: Callable[[str, str, bool, int], None]):
        """设置文件完成回调: callback(file_path, action, success, bytes_transferred)"""
        self._file_completed_callback = callback

    def get_total_transferred_bytes(self) -> int:
        """获取总传输字节数（包括已完成和正在传输的文件）"""
        with self._lock:
            # 已完成文件的字节数 + 所有正在传输文件的字节数
            return self._transferred_bytes + sum(self._thread_bytes.values())

    def _create_connector(self, config: ConnectionConfig) -> Optional[FileConnector]:
        """创建单个连接器"""
        try:
            connector = create_connector(config)
            if connector.connect():
                return connector
            else:
                return None
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"创建连接器失败: {e}", exc_info=True)
            return None

    def _init_connection_pool(self) -> bool:
        """初始化连接池 - 为每个线程创建独立连接"""
        import logging
        logger = logging.getLogger(__name__)

        with self._pool_lock:
            # 清空现有连接池
            self._cleanup_pool()

            # 为每个线程创建源端和目标端连接
            for i in range(self.thread_count):
                logger.info(f"创建连接池 [{i+1}/{self.thread_count}]...")

                # 创建源端连接
                source = self._create_connector(self.config.source)
                if not source:
                    logger.error(f"创建源端连接失败 (线程 {i+1})")
                    self._cleanup_pool()
                    return False
                self._source_pool.append(source)

                # 创建目标端连接
                target = self._create_connector(self.config.target)
                if not target:
                    logger.error(f"创建目标端连接失败 (线程 {i+1})")
                    self._cleanup_pool()
                    return False
                self._target_pool.append(target)

            logger.info(f"连接池初始化完成: {self.thread_count} 个连接")
            return True

    def _cleanup_pool(self):
        """清理连接池"""
        for connector in self._source_pool:
            try:
                connector.disconnect()
            except:
                pass
        for connector in self._target_pool:
            try:
                connector.disconnect()
            except:
                pass
        self._source_pool.clear()
        self._target_pool.clear()

    def _get_connectors(self, thread_id: int) -> tuple[Optional[FileConnector], Optional[FileConnector]]:
        """获取指定线程的连接器"""
        with self._pool_lock:
            if thread_id < len(self._source_pool) and thread_id < len(self._target_pool):
                return self._source_pool[thread_id], self._target_pool[thread_id]
            return None, None

    def cancel(self):
        """取消同步"""
        self._cancel_flag = True
        # 同时取消连接器的传输
        if self.source_connector and hasattr(self.source_connector, 'cancel'):
            self.source_connector.cancel()
        if self.target_connector and hasattr(self.target_connector, 'cancel'):
            self.target_connector.cancel()
    
    def connect(self) -> tuple[bool, str]:
        """建立连接 - 初始化连接池"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # 创建主连接（用于文件列表和比较）
            self.source_connector = create_connector(self.config.source)
            if not self.source_connector.connect():
                return False, "源端连接失败"

            self.target_connector = create_connector(self.config.target)
            if not self.target_connector.connect():
                self.source_connector.disconnect()
                return False, "目标端连接失败"

            # 如果线程数大于 1，初始化连接池
            if self.thread_count > 1:
                logger.info(f"初始化 {self.thread_count} 线程连接池...")
                if not self._init_connection_pool():
                    self.source_connector.disconnect()
                    self.target_connector.disconnect()
                    return False, "连接池初始化失败"

            return True, "连接成功"
        except Exception as e:
            return False, f"连接失败: {e}"

    def disconnect(self):
        """断开连接"""
        if self.source_connector:
            self.source_connector.disconnect()
        if self.target_connector:
            self.target_connector.disconnect()
        # 清理连接池
        self._cleanup_pool()
    
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
            logger.debug(f"过滤规则 - 时间过滤类型: {self.config.filter_rule.time_filter_type}")
            if self.config.filter_rule.time_filter_type != "none":
                time_range = self.config.filter_rule.get_time_range()
                logger.debug(f"过滤规则 - 时间范围: {time_range[0]} 到 {time_range[1]}")
            logger.debug(f"过滤规则 - 文件大小: {self.config.filter_rule.min_size} - {self.config.filter_rule.max_size}")

        logger.debug(f"源文件数量: {len(source_files)}, 目标文件数量: {len(target_files)}")

        # 使用比较器
        comparator = FileComparator(self.config)
        return comparator.compare(
            source_files, target_files,
            self.source_connector, self.target_connector
        )
    
    def _process_single_item(self, item: SyncItem, source_conn: FileConnector,
                            target_conn: FileConnector, result: SyncResult,
                            thread_id: int) -> tuple[str, str, bool, int]:
        """处理单个同步项（线程安全）"""
        import logging
        logger = logging.getLogger(__name__)

        action = item.action
        bytes_transferred = 0
        action_name = ""
        file_path = item.relative_path
        file_size = item.source_file.size if item.source_file else (item.target_file.size if item.target_file else 0)

        # 初始化当前线程的字节计数
        with self._lock:
            self._thread_bytes[thread_id] = 0

        # 设置传输进度回调 - 使用线程独立计数
        def transfer_progress(transferred, total):
            with self._lock:
                # 更新当前线程的传输字节数
                self._thread_bytes[thread_id] = transferred
                # 计算所有线程的总传输字节数
                total_transferred = self._transferred_bytes + sum(self._thread_bytes.values())

            if self._progress_callback:
                percent = int(transferred * 100 / total) if total > 0 else 0
                self._progress_callback(
                    f"传输: {file_path} ({percent}%)",
                    self._processed_count,
                    result.total_files
                )

        source_conn.set_transfer_callback(transfer_progress)
        target_conn.set_transfer_callback(transfer_progress)

        try:
            if action == FileAction.COPY_TO_TARGET:
                action_name = "复制"
                logger.debug(f"[线程{thread_id+1}] 复制到目标: {item.source_file.path}")
                bytes_transferred = target_conn.copy_file(
                    source_conn,
                    item.source_file.path,
                    item.source_file.path,
                    file_size=file_size,
                    resume=True
                )
                with self._lock:
                    # 累加到总字节数，清理线程计数
                    self._transferred_bytes += bytes_transferred
                    self._thread_bytes[thread_id] = 0
                    result.copied_files += 1
                logger.debug(f"[线程{thread_id+1}] 复制完成: {item.source_file.path}, {bytes_transferred} bytes")

            elif action == FileAction.COPY_TO_SOURCE:
                action_name = "复制"
                logger.debug(f"[线程{thread_id+1}] 复制到源: {item.target_file.path}")
                bytes_transferred = source_conn.copy_file(
                    target_conn,
                    item.target_file.path,
                    item.target_file.path,
                    file_size=file_size,
                    resume=True
                )
                with self._lock:
                    # 累加到总字节数，清理线程计数
                    self._transferred_bytes += bytes_transferred
                    self._thread_bytes[thread_id] = 0
                    result.copied_files += 1
                logger.debug(f"[线程{thread_id+1}] 复制完成: {item.target_file.path}, {bytes_transferred} bytes")

            elif action == FileAction.UPDATE_TARGET:
                action_name = "更新"
                logger.debug(f"[线程{thread_id+1}] 更新目标: {item.source_file.path}")
                bytes_transferred = target_conn.copy_file(
                    source_conn,
                    item.source_file.path,
                    item.source_file.path,
                    file_size=file_size,
                    resume=True
                )
                with self._lock:
                    # 累加到总字节数，清理线程计数
                    self._transferred_bytes += bytes_transferred
                    self._thread_bytes[thread_id] = 0
                    result.updated_files += 1
                logger.debug(f"[线程{thread_id+1}] 更新完成: {item.source_file.path}, {bytes_transferred} bytes")

            elif action == FileAction.UPDATE_SOURCE:
                action_name = "更新"
                logger.debug(f"[线程{thread_id+1}] 更新源: {item.target_file.path}")
                bytes_transferred = source_conn.copy_file(
                    target_conn,
                    item.target_file.path,
                    item.target_file.path,
                    file_size=file_size,
                    resume=True
                )
                with self._lock:
                    # 累加到总字节数，清理线程计数
                    self._transferred_bytes += bytes_transferred
                    self._thread_bytes[thread_id] = 0
                    result.updated_files += 1
                logger.debug(f"[线程{thread_id+1}] 更新完成: {item.target_file.path}, {bytes_transferred} bytes")

            elif action == FileAction.DELETE_TARGET:
                action_name = "删除"
                logger.debug(f"[线程{thread_id+1}] 删除目标: {item.target_file.path}")
                target_conn.delete_file(item.target_file.path)
                with self._lock:
                    self._thread_bytes[thread_id] = 0  # 清理线程计数
                    result.deleted_files += 1
                logger.debug(f"[线程{thread_id+1}] 删除完成: {item.target_file.path}")

            elif action == FileAction.DELETE_SOURCE:
                action_name = "删除"
                logger.debug(f"[线程{thread_id+1}] 删除源: {item.source_file.path}")
                source_conn.delete_file(item.source_file.path)
                with self._lock:
                    self._thread_bytes[thread_id] = 0  # 清理线程计数
                    result.deleted_files += 1
                logger.debug(f"[线程{thread_id+1}] 删除完成: {item.source_file.path}")

            # 成功完成，清理线程计数
            with self._lock:
                self._thread_bytes[thread_id] = 0

            return action_name, file_path, True, bytes_transferred

        except Exception as e:
            logger.error(f"[线程{thread_id+1}] 处理失败 {file_path}: {e}", exc_info=True)
            # 使用安全的错误消息提取函数
            error_msg = _safe_error_message(e)

            with self._lock:
                self._thread_bytes[thread_id] = 0  # 失败时也清理线程计数
                result.errors.append(f"{file_path}: {error_msg}")
            return action_name, file_path, False, 0

    def execute(self, sync_items: List[SyncItem] = None) -> SyncResult:
        """执行同步 - 支持多线程并发执行"""
        import logging
        from concurrent.futures import ThreadPoolExecutor, as_completed
        logger = logging.getLogger(__name__)

        result = SyncResult()
        self._cancel_flag = False
        self._processed_count = 0
        self._transferred_bytes = 0  # 重置总传输字节数
        self._thread_bytes = {}  # 重置线程字节计数

        # 重置连接器的取消标志
        if self.source_connector and hasattr(self.source_connector, 'reset_cancel'):
            self.source_connector.reset_cancel()
        if self.target_connector and hasattr(self.target_connector, 'reset_cancel'):
            self.target_connector.reset_cancel()

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

        # 根据线程数选择执行方式
        if self.thread_count == 1 or len(self._source_pool) == 0:
            # 单线程执行
            logger.info("使用单线程模式执行同步")
            self._execute_single_thread(items_to_process, result, logger)
        else:
            # 多线程执行
            logger.info(f"使用 {self.thread_count} 线程并发执行同步")
            self._execute_multi_thread(items_to_process, result, logger)

        result.end_time = datetime.now()
        result.success = len(result.errors) == 0
        return result

    def _execute_single_thread(self, items_to_process: List[SyncItem], result: SyncResult, logger):
        """单线程执行"""
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
                file_size = item.source_file.size if item.source_file else (item.target_file.size if item.target_file else 0)

                # 记录传输开始前的字节数
                bytes_before = self._transferred_bytes

                # 设置传输进度回调 - 实时更新传输字节数
                def transfer_progress(transferred, total):
                    # 实时更新已传输字节数
                    self._transferred_bytes = bytes_before + transferred
                    if self._progress_callback:
                        percent = int(transferred * 100 / total) if total > 0 else 0
                        self._progress_callback(
                            f"传输: {file_path} ({percent}%)",
                            self._processed_count,
                            result.total_files
                        )

                self.source_connector.set_transfer_callback(transfer_progress)
                self.target_connector.set_transfer_callback(transfer_progress)

                if action == FileAction.COPY_TO_TARGET:
                    action_name = "复制"
                    logger.debug(f"复制到目标: {item.source_file.path}")
                    # 使用流式传输
                    bytes_transferred = self.target_connector.copy_file(
                        self.source_connector,
                        item.source_file.path,
                        item.source_file.path,
                        file_size=file_size,
                        resume=True
                    )
                    self._transferred_bytes += bytes_transferred
                    result.copied_files += 1
                    logger.debug(f"复制完成: {item.source_file.path}, {bytes_transferred} bytes")

                elif action == FileAction.COPY_TO_SOURCE:
                    action_name = "复制(反向)"
                    logger.debug(f"复制到源: {item.target_file.path}")
                    bytes_transferred = self.source_connector.copy_file(
                        self.target_connector,
                        item.target_file.path,
                        item.target_file.path,
                        file_size=file_size,
                        resume=True
                    )
                    self._transferred_bytes += bytes_transferred
                    result.copied_files += 1

                elif action == FileAction.UPDATE_TARGET:
                    action_name = "更新"
                    logger.debug(f"更新目标: {item.source_file.path}")
                    bytes_transferred = self.target_connector.copy_file(
                        self.source_connector,
                        item.source_file.path,
                        item.source_file.path,
                        file_size=file_size,
                        resume=False  # 更新不使用断点续传
                    )
                    self._transferred_bytes += bytes_transferred
                    result.updated_files += 1

                elif action == FileAction.UPDATE_SOURCE:
                    action_name = "更新(反向)"
                    logger.debug(f"更新源: {item.target_file.path}")
                    bytes_transferred = self.source_connector.copy_file(
                        self.target_connector,
                        item.target_file.path,
                        item.target_file.path,
                        file_size=file_size,
                        resume=False
                    )
                    self._transferred_bytes += bytes_transferred
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

            except InterruptedError:
                # 用户取消传输
                logger.info(f"用户取消传输: {item.relative_path}")
                result.errors.append("用户取消")
                break
            except Exception as e:
                logger.error(f"处理文件失败 {item.relative_path}: {e}")
                # 使用安全的错误消息提取函数
                error_msg = _safe_error_message(e)
                result.errors.append(f"{item.relative_path}: {error_msg}")
                result.failed_files += 1
                # 记录失败操作
                result.details.append((action_name or "错误", item.relative_path, False, 0))

    def _execute_multi_thread(self, items_to_process: List[SyncItem], result: SyncResult, logger):
        """多线程并发执行"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from queue import Queue

        # 创建任务队列
        task_queue = Queue()
        for item in items_to_process:
            task_queue.put(item)

        # Worker 函数
        def worker(thread_id: int):
            # 获取该线程的连接
            source_conn, target_conn = self._get_connectors(thread_id)
            if not source_conn or not target_conn:
                logger.error(f"线程 {thread_id+1} 无法获取连接")
                return

            while not self._cancel_flag:
                try:
                    # 从队列获取任务（非阻塞）
                    if task_queue.empty():
                        break
                    item = task_queue.get_nowait()

                    # 更新处理计数
                    with self._lock:
                        self._processed_count += 1
                        current = self._processed_count

                    # 进度回调
                    if self._progress_callback:
                        self._progress_callback(
                            f"[线程{thread_id+1}] 处理: {item.relative_path}",
                            current,
                            result.total_files
                        )

                    # 处理文件
                    action_name, file_path, success, bytes_transferred = self._process_single_item(
                        item, source_conn, target_conn, result, thread_id
                    )

                    # 更新传输字节数
                    with self._lock:
                        result.transferred_bytes += bytes_transferred
                        result.details.append((action_name, file_path, success, bytes_transferred))

                    # 文件完成回调
                    if self._file_completed_callback:
                        self._file_completed_callback(file_path, action_name, success, bytes_transferred)

                    task_queue.task_done()

                except Exception as e:
                    logger.error(f"线程 {thread_id+1} 处理任务时出错: {e}", exc_info=True)
                    try:
                        task_queue.task_done()
                    except:
                        pass

        # 启动线程池
        with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            futures = [executor.submit(worker, i) for i in range(self.thread_count)]

            # 等待所有任务完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"线程执行出错: {e}", exc_info=True)
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
