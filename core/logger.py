# -*- coding: utf-8 -*-
"""
任务执行日志记录模块
"""
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import threading


@dataclass
class TaskLogEntry:
    """任务日志条目"""
    task_id: str
    task_name: str
    start_time: str
    end_time: str
    duration: float
    success: bool
    exit_code: int
    command: str
    working_dir: str
    stdout: str
    stderr: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskLogger:
    """任务日志记录器"""
    
    def __init__(self, log_dir: str = "logs", enabled: bool = True):
        """
        初始化日志记录器
        
        Args:
            log_dir: 日志目录路径
            enabled: 是否启用日志记录
        """
        self._log_dir = log_dir
        self._enabled = enabled
        self._lock = threading.Lock()
        
        if self._enabled:
            self._ensure_log_dir()
    
    @property
    def log_dir(self) -> str:
        return self._log_dir
    
    @log_dir.setter
    def log_dir(self, value: str):
        self._log_dir = value
        if self._enabled:
            self._ensure_log_dir()
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        if value:
            self._ensure_log_dir()
    
    def _ensure_log_dir(self):
        """确保日志目录存在"""
        if self._log_dir and not os.path.exists(self._log_dir):
            try:
                os.makedirs(self._log_dir)
            except OSError:
                pass
    
    def _get_log_filename(self, task_name: str, timestamp: datetime) -> str:
        """生成日志文件名"""
        # 清理任务名中的非法字符
        safe_name = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in task_name)
        safe_name = safe_name.strip().replace(' ', '_')
        date_str = timestamp.strftime('%Y%m%d')
        time_str = timestamp.strftime('%H%M%S')
        return f"{safe_name}_{date_str}_{time_str}.log"
    
    def log_execution(self, task_id: str, task_name: str, command: str,
                      working_dir: str, result, parsed_vars: Dict[str, str] = None) -> Optional[str]:
        """
        记录任务执行结果

        Args:
            task_id: 任务ID
            task_name: 任务名称
            command: 执行的命令
            working_dir: 工作目录
            result: ExecutionResult 对象
            parsed_vars: 解析器提取的变量字典

        Returns:
            日志文件路径，如果未启用则返回 None
        """
        if not self._enabled:
            return None

        try:
            self._ensure_log_dir()

            # 生成日志文件名
            filename = self._get_log_filename(task_name, result.start_time)
            filepath = os.path.join(self._log_dir, filename)

            # 构建日志内容
            log_content = self._format_log(task_id, task_name, command, working_dir, result, parsed_vars)

            # 写入文件
            with self._lock:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_content)

            return filepath

        except Exception as e:
            print(f"写入日志失败: {e}")
            return None
    
    def _format_log(self, task_id: str, task_name: str, command: str,
                    working_dir: str, result, parsed_vars: Dict[str, str] = None) -> str:
        """格式化日志内容"""
        separator = "=" * 60

        lines = [
            separator,
            f"任务执行日志",
            separator,
            f"",
            f"任务名称: {task_name}",
            f"任务ID: {task_id}",
            f"执行命令: {command}",
            f"工作目录: {working_dir or '(默认)'}",
            f"",
            f"开始时间: {result.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"结束时间: {result.end_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"执行时长: {result.duration:.2f} 秒",
            f"",
            f"执行状态: {'成功' if result.success else '失败'}",
            f"退出代码: {result.exit_code}",
            f"",
        ]

        # 添加解析器提取的变量
        if parsed_vars:
            lines.extend([
                separator,
                f"解析器提取的变量",
                separator,
            ])
            for var_name, value in parsed_vars.items():
                lines.append(f"  {var_name} = {value}")
            lines.append(f"")

        lines.extend([
            separator,
            f"标准输出 (STDOUT)",
            separator,
            result.stdout if result.stdout else "(无输出)",
            f"",
        ])

        if result.stderr:
            lines.extend([
                separator,
                f"错误输出 (STDERR)",
                separator,
                result.stderr,
                f"",
            ])

        lines.extend([
            separator,
            f"日志生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            separator,
        ])

        return "\n".join(lines)

    def append_log(self, task_id: str, content: str) -> bool:
        """
        追加内容到最近的日志文件

        Args:
            task_id: 任务ID
            content: 要追加的内容

        Returns:
            是否成功
        """
        if not self._enabled:
            return False

        try:
            # 查找最近的日志文件
            if not os.path.exists(self._log_dir):
                return False

            # 获取最近修改的日志文件
            files = []
            for f in os.listdir(self._log_dir):
                if f.endswith('.log'):
                    filepath = os.path.join(self._log_dir, f)
                    files.append((filepath, os.path.getmtime(filepath)))

            if not files:
                return False

            # 按修改时间排序，取最新的
            files.sort(key=lambda x: x[1], reverse=True)
            latest_file = files[0][0]

            # 追加内容
            with self._lock:
                with open(latest_file, 'a', encoding='utf-8') as f:
                    f.write("\n" + content)

            return True

        except Exception as e:
            print(f"追加日志失败: {e}")
            return False

    def get_log_files(self, task_name: str = None, limit: int = 100) -> list:
        """获取日志文件列表"""
        if not os.path.exists(self._log_dir):
            return []
        
        files = []
        for f in os.listdir(self._log_dir):
            if f.endswith('.log'):
                if task_name is None or f.startswith(task_name.replace(' ', '_')):
                    filepath = os.path.join(self._log_dir, f)
                    files.append({
                        'filename': f,
                        'filepath': filepath,
                        'size': os.path.getsize(filepath),
                        'mtime': os.path.getmtime(filepath)
                    })
        
        # 按修改时间倒序排列
        files.sort(key=lambda x: x['mtime'], reverse=True)
        return files[:limit]
    
    def clear_old_logs(self, days: int = 30):
        """清理旧日志"""
        if not os.path.exists(self._log_dir):
            return

        import time
        now = time.time()
        cutoff = now - (days * 86400)

        for f in os.listdir(self._log_dir):
            if f.endswith('.log'):
                filepath = os.path.join(self._log_dir, f)
                if os.path.getmtime(filepath) < cutoff:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

    def log_sync_execution(self, task_id: str, task_name: str,
                           sync_config, result, parsed_vars: Dict[str, str] = None) -> Optional[str]:
        """
        记录同步任务执行结果

        Args:
            task_id: 任务ID
            task_name: 任务名称
            sync_config: SyncConfig 对象
            result: ExecutionResult 对象
            parsed_vars: 解析器提取的变量字典

        Returns:
            日志文件路径，如果未启用则返回 None
        """
        if not self._enabled:
            return None

        try:
            self._ensure_log_dir()

            # 生成日志文件名
            filename = self._get_log_filename(task_name, result.start_time)
            filepath = os.path.join(self._log_dir, filename)

            # 构建日志内容
            log_content = self._format_sync_log(task_id, task_name, sync_config, result, parsed_vars)

            # 写入文件
            with self._lock:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_content)

            return filepath

        except Exception as e:
            print(f"写入同步日志失败: {e}")
            return None

    def _format_sync_log(self, task_id: str, task_name: str,
                         sync_config, result, parsed_vars: Dict[str, str] = None) -> str:
        """格式化同步任务日志内容"""
        separator = "=" * 60

        # 获取同步配置信息
        source_path = sync_config.source.path if sync_config else "未知"
        target_path = sync_config.target.path if sync_config else "未知"
        sync_mode = sync_config.sync_mode.value if sync_config else "未知"

        lines = [
            separator,
            "同步任务执行日志",
            separator,
            "",
            f"任务名称: {task_name}",
            f"任务ID: {task_id}",
            f"任务类型: 文件同步",
            "",
            f"源端路径: {source_path}",
            f"目标路径: {target_path}",
            f"同步模式: {sync_mode}",
            "",
            f"开始时间: {result.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"结束时间: {result.end_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"执行时长: {result.duration:.2f} 秒",
            "",
            f"执行状态: {'成功' if result.success else '失败'}",
            f"退出代码: {result.exit_code}",
            "",
        ]

        # 添加解析器提取的变量
        if parsed_vars:
            lines.extend([
                separator,
                "解析器提取的变量",
                separator,
            ])
            for var_name, value in parsed_vars.items():
                lines.append(f"  {var_name} = {value}")
            lines.append("")

        # 添加同步详情
        if result.stdout:
            lines.extend([
                separator,
                "同步详情",
                separator,
                result.stdout,
                "",
            ])

        # 添加错误信息
        if result.stderr:
            lines.extend([
                separator,
                "错误信息",
                separator,
                result.stderr,
                "",
            ])

        lines.extend([
            separator,
            f"日志生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            separator,
        ])

        return "\n".join(lines)

