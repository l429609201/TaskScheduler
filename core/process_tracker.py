# -*- coding: utf-8 -*-
"""
进程追踪器模块
用于追踪任务执行产生的所有进程（包括子进程），支持终止整个进程树
"""
import threading
import time
from typing import Dict, Set, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import psutil


@dataclass
class ProcessInfo:
    """进程信息"""
    pid: int
    name: str
    create_time: float
    cmdline: str = ""


@dataclass
class TaskProcesses:
    """任务的进程集合"""
    task_id: str
    main_pid: int
    start_time: datetime
    # 追踪到的所有进程 PID
    tracked_pids: Set[int] = field(default_factory=set)
    # 进程详细信息
    process_info: Dict[int, ProcessInfo] = field(default_factory=dict)


class ProcessTracker:
    """进程追踪器"""
    
    def __init__(self):
        self._tasks: Dict[str, TaskProcesses] = {}
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = False
    
    def register_task(self, task_id: str, main_pid: int):
        """注册任务的主进程"""
        with self._lock:
            task_processes = TaskProcesses(
                task_id=task_id,
                main_pid=main_pid,
                start_time=datetime.now()
            )
            task_processes.tracked_pids.add(main_pid)
            
            # 获取主进程信息
            try:
                proc = psutil.Process(main_pid)
                task_processes.process_info[main_pid] = ProcessInfo(
                    pid=main_pid,
                    name=proc.name(),
                    create_time=proc.create_time(),
                    cmdline=' '.join(proc.cmdline()[:3])  # 只取前3个参数
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            
            self._tasks[task_id] = task_processes
            
            # 立即扫描一次子进程
            self._scan_children(task_id)
    
    def unregister_task(self, task_id: str):
        """注销任务"""
        with self._lock:
            self._tasks.pop(task_id, None)
    
    def _scan_children(self, task_id: str):
        """扫描任务的子进程（需要在锁内调用）"""
        task_processes = self._tasks.get(task_id)
        if not task_processes:
            return
        
        try:
            main_proc = psutil.Process(task_processes.main_pid)
            children = main_proc.children(recursive=True)
            
            for child in children:
                try:
                    if child.pid not in task_processes.tracked_pids:
                        task_processes.tracked_pids.add(child.pid)
                        task_processes.process_info[child.pid] = ProcessInfo(
                            pid=child.pid,
                            name=child.name(),
                            create_time=child.create_time(),
                            cmdline=' '.join(child.cmdline()[:3])
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    def scan_all_children(self):
        """扫描所有任务的子进程"""
        with self._lock:
            for task_id in list(self._tasks.keys()):
                self._scan_children(task_id)
    
    def get_task_pids(self, task_id: str) -> Set[int]:
        """获取任务的所有进程 PID"""
        with self._lock:
            task_processes = self._tasks.get(task_id)
            if task_processes:
                # 先扫描一次
                self._scan_children(task_id)
                return task_processes.tracked_pids.copy()
            return set()
    
    def is_task_running(self, task_id: str) -> bool:
        """检查任务是否还有进程在运行"""
        pids = self.get_task_pids(task_id)
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
    
    def kill_task_processes(self, task_id: str, timeout: float = 5.0) -> bool:
        """终止任务的所有进程"""
        # 先扫描获取最新的子进程
        pids = self.get_task_pids(task_id)
        if not pids:
            return True
        
        killed_any = False
        procs_to_kill = []
        
        # 收集所有存活的进程
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                if proc.is_running():
                    procs_to_kill.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if not procs_to_kill:
            self.unregister_task(task_id)
            return True
        
        # 先尝试优雅终止 (SIGTERM)
        for proc in procs_to_kill:
            try:
                proc.terminate()
                killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # 等待进程退出
        gone, alive = psutil.wait_procs(procs_to_kill, timeout=timeout)
        
        # 强制杀死还存活的进程 (SIGKILL)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # 再等待一下
        if alive:
            psutil.wait_procs(alive, timeout=2.0)
        
        self.unregister_task(task_id)
        return killed_any
    
    def get_running_tasks(self) -> List[str]:
        """获取所有正在运行的任务 ID"""
        with self._lock:
            return list(self._tasks.keys())


# 全局进程追踪器实例
_tracker: Optional[ProcessTracker] = None


def get_process_tracker() -> ProcessTracker:
    """获取全局进程追踪器"""
    global _tracker
    if _tracker is None:
        _tracker = ProcessTracker()
    return _tracker

