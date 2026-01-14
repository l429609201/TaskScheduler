# -*- coding: utf-8 -*-
"""
批处理执行器模块
"""
import subprocess
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
import threading
import queue


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    start_time: datetime
    end_time: datetime
    duration: float = 0  # 秒
    extra_data: Dict[str, Any] = field(default_factory=dict)  # 附加数据（如同步详情）
    
    def to_notification_params(self, task_name: str) -> Dict[str, Any]:
        """转换为通知参数"""
        # 基础参数
        params = {
            'task_name': task_name,
            'status': 'success' if self.success else 'failed',
            'status_cn': '成功' if self.success else '失败',
            'exit_code': self.exit_code,
            'output': self.stdout[:2000] if self.stdout else '',
            'output_full': self.stdout or '',
            'output_first_line': self.stdout.split('\n')[0].strip() if self.stdout else '',
            'output_last_line': self.stdout.strip().split('\n')[-1].strip() if self.stdout else '',
            'output_line_count': len(self.stdout.split('\n')) if self.stdout else 0,
            'error': self.stderr[:1000] if self.stderr else '',
            'error_full': self.stderr or '',
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'start_time_fmt': self.start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time_fmt': self.end_time.strftime('%Y-%m-%d %H:%M:%S'),
            'date': self.start_time.strftime('%Y-%m-%d'),
            'time': self.start_time.strftime('%H:%M:%S'),
            'duration': round(self.duration, 2),
            'duration_ms': int(self.duration * 1000),
            'duration_str': self._format_duration(),
            'hostname': self._get_hostname(),
            'username': self._get_username(),
        }

        # 解析输出中的 KEY=VALUE 格式，自动添加为参数
        if self.stdout:
            for line in self.stdout.split('\n'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        # 只添加合法的变量名
                        if key.isidentifier() and len(key) <= 50:
                            params[f'var_{key}'] = value

        return params

    def _get_hostname(self) -> str:
        """获取主机名"""
        import socket
        try:
            return socket.gethostname()
        except:
            return 'unknown'

    def _get_username(self) -> str:
        """获取当前用户名"""
        import getpass
        try:
            return getpass.getuser()
        except:
            return 'unknown'
    
    def _format_duration(self) -> str:
        """格式化执行时长"""
        if self.duration < 60:
            return f"{self.duration:.1f}秒"
        elif self.duration < 3600:
            minutes = int(self.duration // 60)
            seconds = int(self.duration % 60)
            return f"{minutes}分{seconds}秒"
        else:
            hours = int(self.duration // 3600)
            minutes = int((self.duration % 3600) // 60)
            return f"{hours}小时{minutes}分"


class BatchExecutor:
    """批处理执行器"""

    def __init__(self):
        self._running_processes: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        # 延迟导入进程追踪器
        self._tracker = None

    def _get_tracker(self):
        """获取进程追踪器"""
        if self._tracker is None:
            from core.process_tracker import get_process_tracker
            self._tracker = get_process_tracker()
        return self._tracker

    def execute(self, command: str, working_dir: str = None,
                timeout: int = None, task_id: str = None,
                kill_previous: bool = False) -> ExecutionResult:
        """
        执行批处理命令

        Args:
            command: 要执行的命令
            working_dir: 工作目录
            timeout: 超时时间（秒）
            task_id: 任务ID（用于跟踪）
            kill_previous: 是否终止上次运行的实例

        Returns:
            ExecutionResult: 执行结果
        """
        start_time = datetime.now()
        tracker = self._get_tracker()

        # 如果需要，先终止上次的实例
        if kill_previous and task_id:
            if tracker.is_task_running(task_id):
                tracker.kill_task_processes(task_id)

        # 设置工作目录
        if working_dir and not os.path.isabs(working_dir):
            working_dir = os.path.abspath(working_dir)

        if not working_dir or not os.path.exists(working_dir):
            working_dir = os.getcwd()

        try:
            # 设置环境变量，强制使用 UTF-8 编码
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            # 根据系统选择 shell
            if sys.platform == 'win32':
                # Windows: 使用 cmd 并设置 UTF-8 代码页
                # chcp 65001 切换到 UTF-8 代码页
                utf8_command = f'chcp 65001 >nul && {command}'
                process = subprocess.Popen(
                    utf8_command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_dir,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Linux/Mac 使用 bash
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_dir,
                    env=env
                )

            # 记录运行中的进程
            if task_id:
                with self._lock:
                    self._running_processes[task_id] = process
                # 注册到进程追踪器
                tracker.register_task(task_id, process.pid)
            
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                exit_code = -1
                stderr = b"Execution timeout"
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # 解码输出 - 统一使用 UTF-8（已通过 chcp 65001 设置）
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')
            
            return ExecutionResult(
                success=(exit_code == 0),
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
            
        except Exception as e:
            end_time = datetime.now()
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                start_time=start_time,
                end_time=end_time,
                duration=(end_time - start_time).total_seconds()
            )
        finally:
            # 清理运行记录
            if task_id:
                with self._lock:
                    self._running_processes.pop(task_id, None)
                # 从进程追踪器注销
                tracker.unregister_task(task_id)

    def stop_task(self, task_id: str) -> bool:
        """停止正在运行的任务"""
        tracker = self._get_tracker()
        # 使用进程追踪器终止所有相关进程
        if tracker.kill_task_processes(task_id):
            with self._lock:
                self._running_processes.pop(task_id, None)
            return True
        # 回退到旧方法
        with self._lock:
            process = self._running_processes.get(task_id)
            if process:
                process.terminate()
                return True
        return False

    def is_running(self, task_id: str) -> bool:
        """检查任务是否正在运行"""
        # 优先使用进程追踪器
        tracker = self._get_tracker()
        if tracker.is_task_running(task_id):
            return True
        with self._lock:
            return task_id in self._running_processes

