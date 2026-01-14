# -*- coding: utf-8 -*-
"""
Windows 服务安装器
"""
import sys
import os
import subprocess
from typing import Tuple
import winreg


class StartupManager:
    """开机启动管理器"""

    APP_NAME = "TaskScheduler"
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @classmethod
    def get_exe_path(cls) -> str:
        """获取可执行文件路径"""
        if getattr(sys, 'frozen', False):
            return sys.executable
        else:
            # 开发环境，返回 python + main.py
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            return f'"{sys.executable}" "{os.path.join(base_dir, "main.py")}"'

    @classmethod
    def is_enabled(cls) -> bool:
        """检查是否已设置开机启动"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                cls.REG_PATH,
                0,
                winreg.KEY_READ
            )
            try:
                winreg.QueryValueEx(key, cls.APP_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    @classmethod
    def enable(cls) -> Tuple[bool, str]:
        """启用开机启动"""
        try:
            exe_path = cls.get_exe_path()
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                cls.REG_PATH,
                0,
                winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, cls.APP_NAME, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            return True, "已设置开机启动"
        except Exception as e:
            return False, f"设置失败: {e}"

    @classmethod
    def disable(cls) -> Tuple[bool, str]:
        """禁用开机启动"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                cls.REG_PATH,
                0,
                winreg.KEY_SET_VALUE
            )
            try:
                winreg.DeleteValue(key, cls.APP_NAME)
            except FileNotFoundError:
                pass  # 本来就没有
            winreg.CloseKey(key)
            return True, "已取消开机启动"
        except Exception as e:
            return False, f"取消失败: {e}"

    @classmethod
    def toggle(cls) -> Tuple[bool, str]:
        """切换开机启动状态"""
        if cls.is_enabled():
            return cls.disable()
        else:
            return cls.enable()


class ServiceInstaller:
    """Windows 服务安装器"""
    
    SERVICE_NAME = "TaskSchedulerService"
    DISPLAY_NAME = "任务调度器服务"
    
    def __init__(self):
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
            self.service_script = sys.executable
        else:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.service_script = os.path.join(self.base_dir, 'service', 'task_service.py')
    
    def _run_command(self, args: list) -> Tuple[bool, str]:
        """运行命令"""
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                return True, result.stdout or "操作成功"
            else:
                return False, result.stderr or result.stdout or "操作失败"
        except Exception as e:
            return False, str(e)
    
    def install(self) -> Tuple[bool, str]:
        """安装服务"""
        try:
            import win32serviceutil
            from service.task_service import WindowsTaskService
            
            # 使用 pywin32 安装服务
            try:
                win32serviceutil.InstallService(
                    WindowsTaskService._svc_reg_class_,
                    self.SERVICE_NAME,
                    self.DISPLAY_NAME,
                    startType=win32serviceutil.SERVICE_AUTO_START,
                    description=WindowsTaskService._svc_description_
                )
                return True, f"服务 '{self.DISPLAY_NAME}' 安装成功！\n请以管理员身份运行以启动服务。"
            except Exception as e:
                if "already exists" in str(e).lower() or "1073" in str(e):
                    return False, f"服务已存在，请先卸载后重新安装。"
                raise
                
        except ImportError:
            return False, "缺少 pywin32 模块，请运行: pip install pywin32"
        except Exception as e:
            # 尝试使用 sc 命令安装
            return self._install_with_sc()
    
    def _install_with_sc(self) -> Tuple[bool, str]:
        """使用 sc 命令安装服务"""
        python_exe = sys.executable
        script_path = self.service_script
        
        # 创建批处理启动脚本
        bat_path = os.path.join(self.base_dir, 'start_service.bat')
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(f'@echo off\n')
            f.write(f'"{python_exe}" "{script_path}"\n')
        
        # 使用 NSSM 或 sc 命令（需要管理员权限）
        cmd = [
            'sc', 'create', self.SERVICE_NAME,
            f'binPath= "{python_exe} {script_path}"',
            'start= auto',
            f'DisplayName= "{self.DISPLAY_NAME}"'
        ]
        
        success, msg = self._run_command(cmd)
        if success:
            return True, f"服务安装成功！\n请以管理员身份运行命令启动服务:\nsc start {self.SERVICE_NAME}"
        else:
            return False, f"安装失败（需要管理员权限）:\n{msg}\n\n建议使用 NSSM 工具安装服务。"
    
    def uninstall(self) -> Tuple[bool, str]:
        """卸载服务"""
        try:
            import win32serviceutil
            
            # 先停止服务
            try:
                win32serviceutil.StopService(self.SERVICE_NAME)
            except:
                pass
            
            # 卸载服务
            win32serviceutil.RemoveService(self.SERVICE_NAME)
            return True, f"服务 '{self.DISPLAY_NAME}' 已卸载"
            
        except ImportError:
            # 使用 sc 命令
            self._run_command(['sc', 'stop', self.SERVICE_NAME])
            success, msg = self._run_command(['sc', 'delete', self.SERVICE_NAME])
            if success:
                return True, f"服务已卸载"
            return False, f"卸载失败：{msg}"
        except Exception as e:
            return False, f"卸载失败：{str(e)}"
    
    def start(self) -> Tuple[bool, str]:
        """启动服务"""
        try:
            import win32serviceutil
            win32serviceutil.StartService(self.SERVICE_NAME)
            return True, "服务已启动"
        except ImportError:
            success, msg = self._run_command(['sc', 'start', self.SERVICE_NAME])
            return success, msg
        except Exception as e:
            return False, f"启动失败：{str(e)}"
    
    def stop(self) -> Tuple[bool, str]:
        """停止服务"""
        try:
            import win32serviceutil
            win32serviceutil.StopService(self.SERVICE_NAME)
            return True, "服务已停止"
        except ImportError:
            success, msg = self._run_command(['sc', 'stop', self.SERVICE_NAME])
            return success, msg
        except Exception as e:
            return False, f"停止失败：{str(e)}"
    
    def status(self) -> Tuple[bool, str]:
        """查询服务状态"""
        try:
            import win32serviceutil
            import win32service
            
            status = win32serviceutil.QueryServiceStatus(self.SERVICE_NAME)
            state = status[1]
            
            states = {
                win32service.SERVICE_STOPPED: "已停止",
                win32service.SERVICE_START_PENDING: "正在启动",
                win32service.SERVICE_STOP_PENDING: "正在停止",
                win32service.SERVICE_RUNNING: "运行中",
            }
            return True, states.get(state, f"未知状态: {state}")
        except ImportError:
            success, msg = self._run_command(['sc', 'query', self.SERVICE_NAME])
            return success, msg
        except Exception as e:
            return False, f"查询失败：{str(e)}"

