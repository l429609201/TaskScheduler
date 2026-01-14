# -*- coding: utf-8 -*-
"""
任务调度器 - 主程序入口

功能特性:
- 定时执行批处理命令
- 支持 Cron 表达式配置
- 多 Webhook 通知支持
- 执行结果转换为自定义通知参数
- 可安装为 Windows 服务
"""
import sys
import os

# 确保项目根目录在路径中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def check_single_instance():
    """
    检查是否已有实例运行
    返回 (is_running, list_of_pids)

    注意：返回所有相关进程的 PID 列表
    使用互斥锁文件来检测，更可靠
    """
    import psutil
    import tempfile
    import hashlib

    current_pid = os.getpid()
    found_pids = []

    # 生成唯一的锁文件路径（基于 exe 路径的哈希）
    if getattr(sys, 'frozen', False):
        exe_path = os.path.abspath(sys.executable)
    else:
        exe_path = os.path.abspath(__file__)

    path_hash = hashlib.md5(exe_path.lower().encode()).hexdigest()[:16]
    lock_file = os.path.join(tempfile.gettempdir(), f"taskscheduler_{path_hash}.lock")

    # 检查锁文件
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                old_pid = int(f.read().strip())

            # 检查该 PID 是否还在运行
            if old_pid != current_pid:
                try:
                    proc = psutil.Process(old_pid)
                    # 验证是否是同一个程序
                    if proc.is_running():
                        proc_exe = proc.exe() if hasattr(proc, 'exe') else None
                        if getattr(sys, 'frozen', False):
                            # 打包模式：比较 exe 路径
                            if proc_exe and os.path.abspath(proc_exe).lower() == exe_path.lower():
                                found_pids.append(old_pid)
                        else:
                            # 开发模式：检查命令行
                            cmdline = proc.cmdline() if hasattr(proc, 'cmdline') else []
                            for arg in cmdline:
                                try:
                                    if arg and 'main.py' in arg.lower():
                                        # 排除服务模式
                                        cmdline_str = ' '.join(cmdline).lower()
                                        if '--service' not in cmdline_str and '-s' not in cmdline_str:
                                            found_pids.append(old_pid)
                                        break
                                except:
                                    pass
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # 进程不存在或无法访问，删除旧锁文件
                    try:
                        os.remove(lock_file)
                    except:
                        pass
        except (ValueError, IOError):
            # 锁文件损坏，删除它
            try:
                os.remove(lock_file)
            except:
                pass

    # 如果没有找到运行中的实例，写入当前 PID
    if not found_pids:
        try:
            with open(lock_file, 'w') as f:
                f.write(str(current_pid))
        except:
            pass

    if found_pids:
        return True, found_pids
    return False, []


def kill_process(pid):
    """杀死指定进程 - 使用系统命令强制终止"""
    import subprocess
    import time

    try:
        if sys.platform == 'win32':
            # Windows: 使用 taskkill 强制终止进程
            result = subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # taskkill 返回 0 表示成功，128 表示进程不存在
            if result.returncode in (0, 128):
                time.sleep(0.5)  # 等待进程完全退出
                return True
            else:
                print(f"taskkill 失败: {result.stderr}")
                return False
        else:
            # Linux/Mac: 使用 kill -9
            os.kill(pid, 9)
            time.sleep(0.5)
            return True
    except Exception as e:
        print(f"杀死进程失败: {e}")
        return False


def setup_exception_hook():
    """设置全局异常钩子，捕获未处理的异常"""
    import traceback
    import logging

    # 配置日志
    log_file = os.path.join(BASE_DIR, 'error.log')
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stderr)
        ]
    )

    def exception_hook(exc_type, exc_value, exc_tb):
        """全局异常处理"""
        error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error(f"未捕获的异常:\n{error_msg}")
        print(f"未捕获的异常:\n{error_msg}", file=sys.stderr)
        # 调用默认处理
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = exception_hook
    logging.info("程序启动，异常钩子已设置")
    return logging.getLogger()


def run_gui():
    """运行 GUI 界面"""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QIcon
    from ui.main_window import MainWindow
    from ui.message_box import MsgBox

    # 设置异常钩子
    logger = setup_exception_hook()
    logger.info("启动 GUI 模式")

    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("任务调度器")
    app.setOrganizationName("TaskScheduler")

    # 设置应用程序图标（任务栏图标）
    if getattr(sys, 'frozen', False):
        icon_path = os.path.join(sys._MEIPASS, 'logo.ico')
    else:
        icon_path = os.path.join(BASE_DIR, 'logo.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 检查是否已有实例运行（必须在 QApplication 创建后检查，这样才能显示对话框）
    is_running, pids = check_single_instance()
    if is_running:
        pid_info = f" (PID: {', '.join(map(str, pids))})" if pids else ""
        if MsgBox.question(
            None,
            "程序已在运行",
            f"检测到任务调度器已在运行{pid_info}\n\n是否关闭已运行的实例并启动新实例？",
            default_no=True
        ):
            # 杀死所有找到的进程
            import time
            import psutil

            all_killed = True
            for pid in pids:
                if not kill_process(pid):
                    all_killed = False

            if all_killed:
                # 等待所有进程完全退出
                for _ in range(30):  # 最多等待 3 秒
                    time.sleep(0.1)
                    still_running = False
                    for pid in pids:
                        try:
                            proc = psutil.Process(pid)
                            if proc.is_running():
                                still_running = True
                                break
                        except psutil.NoSuchProcess:
                            pass
                    if not still_running:
                        break
                # 继续启动
            else:
                MsgBox.critical(None, "错误", "无法关闭已运行的实例，请手动关闭后重试")
                sys.exit(1)
        else:
            sys.exit(0)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


def run_service():
    """运行服务模式（无界面）"""
    from service.task_service import TaskSchedulerService
    
    service = TaskSchedulerService()
    service.run()


def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='任务调度器')
    parser.add_argument('--service', '-s', action='store_true', 
                        help='以服务模式运行（无界面）')
    parser.add_argument('--install', action='store_true',
                        help='安装 Windows 服务')
    parser.add_argument('--uninstall', action='store_true',
                        help='卸载 Windows 服务')
    parser.add_argument('--start', action='store_true',
                        help='启动 Windows 服务')
    parser.add_argument('--stop', action='store_true',
                        help='停止 Windows 服务')
    parser.add_argument('--status', action='store_true',
                        help='查询服务状态')
    
    args = parser.parse_args()
    
    if args.install:
        from service.installer import ServiceInstaller
        installer = ServiceInstaller()
        success, msg = installer.install()
        print(msg)
        sys.exit(0 if success else 1)
    
    elif args.uninstall:
        from service.installer import ServiceInstaller
        installer = ServiceInstaller()
        success, msg = installer.uninstall()
        print(msg)
        sys.exit(0 if success else 1)
    
    elif args.start:
        from service.installer import ServiceInstaller
        installer = ServiceInstaller()
        success, msg = installer.start()
        print(msg)
        sys.exit(0 if success else 1)
    
    elif args.stop:
        from service.installer import ServiceInstaller
        installer = ServiceInstaller()
        success, msg = installer.stop()
        print(msg)
        sys.exit(0 if success else 1)
    
    elif args.status:
        from service.installer import ServiceInstaller
        installer = ServiceInstaller()
        success, msg = installer.status()
        print(msg)
        sys.exit(0 if success else 1)
    
    elif args.service:
        run_service()
    
    else:
        run_gui()


if __name__ == '__main__':
    main()

