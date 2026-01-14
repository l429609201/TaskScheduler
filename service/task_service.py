# -*- coding: utf-8 -*-
"""
Windows 服务模块
"""
import sys
import os
import time
import logging

# 添加项目根目录到路径
if getattr(sys, 'frozen', False):
    # 打包后的路径
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from core.models import TaskStorage
from core.scheduler import TaskScheduler

# 配置日志
log_dir = os.path.join(BASE_DIR, 'logs')
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'service.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TaskSchedulerService:
    """任务调度器服务（非 Windows 服务模式）"""
    
    def __init__(self):
        self.storage = TaskStorage(os.path.join(BASE_DIR, 'config', 'tasks.json'))
        self.scheduler = TaskScheduler(self.storage)
        self._running = False
    
    def start(self):
        """启动服务"""
        logger.info("任务调度服务启动中...")
        self._running = True
        self.scheduler.load_all_tasks()
        self.scheduler.start()
        logger.info("任务调度服务已启动")
    
    def stop(self):
        """停止服务"""
        logger.info("任务调度服务停止中...")
        self._running = False
        self.scheduler.stop()
        logger.info("任务调度服务已停止")
    
    def run(self):
        """运行服务（阻塞）"""
        self.start()
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


if HAS_WIN32:
    class WindowsTaskService(win32serviceutil.ServiceFramework):
        """Windows 服务实现"""
        
        _svc_name_ = "TaskSchedulerService"
        _svc_display_name_ = "任务调度器服务"
        _svc_description_ = "自定义任务调度服务，支持定时执行批处理和 Webhook 通知"
        
        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.service = TaskSchedulerService()
        
        def SvcStop(self):
            """停止服务"""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            self.service.stop()
        
        def SvcDoRun(self):
            """运行服务"""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            self.service.start()
            
            # 等待停止信号
            while True:
                result = win32event.WaitForSingleObject(self.stop_event, 5000)
                if result == win32event.WAIT_OBJECT_0:
                    break
            
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, '')
            )


def main():
    """服务入口点"""
    if HAS_WIN32 and len(sys.argv) > 1:
        # Windows 服务模式
        win32serviceutil.HandleCommandLine(WindowsTaskService)
    else:
        # 普通模式运行
        service = TaskSchedulerService()
        service.run()


if __name__ == '__main__':
    main()

