# -*- coding: utf-8 -*-
"""
Windows 任务计划程序管理器
使用 Windows Task Scheduler 替代 Windows Service
参考: https://github.com/786raees/task-scheduler-python (2023年8月)
"""
import sys
import os
import win32com.client


class TaskSchedulerManager:
    """Windows 任务计划程序管理器"""
    
    TASK_NAME = "TaskScheduler_AutoStart"
    TASK_DESCRIPTION = "定时任务调度器 - 开机自动启动"
    
    def __init__(self):
        self.scheduler = win32com.client.Dispatch('Schedule.Service')
        self.scheduler.Connect()
        self.root_folder = self.scheduler.GetFolder('\\')
        
    def create_startup_task(self, executable_path: str = None, working_dir: str = None) -> tuple[bool, str]:
        """
        创建开机启动任务
        
        Args:
            executable_path: 程序路径（不提供则使用当前 Python 脚本）
            working_dir: 工作目录
            
        Returns:
            (成功, 消息)
        """
        try:
            # 确定要执行的程序
            if executable_path is None:
                if getattr(sys, 'frozen', False):
                    # 打包后：使用 exe 路径
                    executable_path = sys.executable
                else:
                    # 开发环境：使用 python + main.py
                    executable_path = sys.executable
                    
            # 确定工作目录
            if working_dir is None:
                if getattr(sys, 'frozen', False):
                    working_dir = os.path.dirname(sys.executable)
                else:
                    working_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # 创建任务定义
            task_def = self.scheduler.NewTask(0)
            
            # 设置描述
            task_def.RegistrationInfo.Description = self.TASK_DESCRIPTION
            task_def.RegistrationInfo.Author = "TaskScheduler"
            
            # 设置任务的基本属性
            task_def.Settings.Enabled = True
            task_def.Settings.StartWhenAvailable = True  # 如果错过了计划时间，尽快运行
            task_def.Settings.Hidden = False  # 在任务计划程序中可见
            task_def.Settings.DisallowStartIfOnBatteries = False  # 在电池供电时也运行
            task_def.Settings.StopIfGoingOnBatteries = False  # 切换到电池时不停止
            task_def.Settings.ExecutionTimeLimit = 'PT0S'  # 无时间限制
            
            # 设置触发器 - 开机时触发
            trigger = task_def.Triggers.Create(8)  # 8 = TASK_TRIGGER_BOOT（开机触发）
            trigger.Enabled = True
            trigger.Delay = 'PT30S'  # 延迟 30 秒启动，确保系统已完全启动
            
            # 设置操作 - 执行程序
            action = task_def.Actions.Create(0)  # 0 = TASK_ACTION_EXEC（执行程序）
            action.Path = executable_path
            
            if not getattr(sys, 'frozen', False):
                # 开发环境：传递 main.py 作为参数
                main_py = os.path.join(working_dir, 'main.py')
                action.Arguments = f'"{main_py}" --background'
            else:
                # 打包后：传递 --background 参数
                action.Arguments = '--background'
                
            action.WorkingDirectory = working_dir
            
            # 设置运行身份 - 使用当前用户（不需要密码）
            # TASK_LOGON_INTERACTIVE_TOKEN = 3
            # TASK_LOGON_GROUP = 4（以组方式登录，不需要密码）
            # TASK_CREATE_OR_UPDATE = 6
            
            # 注册任务
            self.root_folder.RegisterTaskDefinition(
                self.TASK_NAME,
                task_def,
                6,  # TASK_CREATE_OR_UPDATE
                None,  # 用户名（None 表示当前用户）
                None,  # 密码（None 表示不需要）
                3   # TASK_LOGON_INTERACTIVE_TOKEN（交互式令牌）
            )
            
            return True, f"开机启动任务创建成功\n\n任务名称: {self.TASK_NAME}\n程序路径: {executable_path}\n工作目录: {working_dir}"
            
        except Exception as e:
            return False, f"创建开机启动任务失败: {str(e)}"
    
    def delete_task(self) -> tuple[bool, str]:
        """删除开机启动任务"""
        try:
            self.root_folder.DeleteTask(self.TASK_NAME, 0)
            return True, "开机启动任务已删除"
        except Exception as e:
            error_msg = str(e)
            if "cannot find the file" in error_msg.lower() or "找不到" in error_msg:
                return True, "任务不存在（可能已被删除）"
            return False, f"删除任务失败: {error_msg}"
    
    def get_task_status(self) -> tuple[bool, str, dict]:
        """
        获取任务状态
        
        Returns:
            (成功, 消息, 详细信息)
        """
        try:
            task = self.root_folder.GetTask(self.TASK_NAME)
            
            # 获取任务状态
            # 0 = Unknown, 1 = Disabled, 2 = Queued, 3 = Ready, 4 = Running
            state_map = {
                0: "未知",
                1: "已禁用",
                2: "排队中",
                3: "就绪",
                4: "运行中"
            }
            
            state = task.State
            state_text = state_map.get(state, f"未知状态({state})")
            enabled = task.Enabled
            
            info = {
                'state': state,
                'state_text': state_text,
                'enabled': enabled,
                'name': task.Name,
                'path': task.Path
            }
            
            status = f"✓ 任务已创建\n状态: {state_text}\n启用: {'是' if enabled else '否'}"
            return True, status, info
            
        except Exception as e:
            error_msg = str(e)
            if "cannot find the file" in error_msg.lower() or "找不到" in error_msg:
                return False, "✗ 任务未创建", {}
            return False, f"查询失败: {error_msg}", {}
    
    def enable_task(self, enable: bool = True) -> tuple[bool, str]:
        """启用或禁用任务"""
        try:
            task = self.root_folder.GetTask(self.TASK_NAME)
            task.Enabled = enable
            return True, f"任务已{'启用' if enable else '禁用'}"
        except Exception as e:
            return False, f"操作失败: {str(e)}"
    
    def run_task_now(self) -> tuple[bool, str]:
        """立即运行任务（不等待开机）"""
        try:
            task = self.root_folder.GetTask(self.TASK_NAME)
            task.Run(None)
            return True, "任务已启动"
        except Exception as e:
            return False, f"启动失败: {str(e)}"

