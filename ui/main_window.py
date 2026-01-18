# -*- coding: utf-8 -*-
"""
主窗口界面
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMenu, QAction, QSystemTrayIcon, QStyle,
    QLabel, QStatusBar, QToolBar, QAbstractItemView,
    QTabWidget, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QColor

from core.models import Task, TaskStatus, TaskStorage, AppSettings, SettingsStorage, WebhookConfig, WebhookStorage, OutputParser, ParserStorage
from core.scheduler import TaskScheduler
from .task_dialog import TaskDialog
from .message_box import MsgBox
from .webhook_dialog import WebhookConfigDialog
from .log_viewer_dialog import LogViewerDialog
from .parser_dialog import OutputParserDialog, ParserRuleDialog
from .settings_dialog import SettingsDialog
from .execution_dialog import ExecutionDialog, ExecutionThread


class BackgroundTaskManager:
    """后台任务管理器 - 管理静默执行的任务"""

    def __init__(self, task_logger=None, storage=None):
        self._running_tasks = {}  # task_id -> (thread, output_buffer, task, start_time)
        self._task_logger = task_logger
        self._storage = storage

    def set_logger(self, task_logger):
        """设置日志记录器"""
        self._task_logger = task_logger

    def set_storage(self, storage):
        """设置任务存储"""
        self._storage = storage

    def start_task(self, task: Task) -> bool:
        """启动后台任务"""
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"[BackgroundTaskManager] start_task 被调用，任务: {task.name} (ID: {task.id})")

        # 如果设置了 kill_previous，先终止上次的实例
        kill_previous = getattr(task, 'kill_previous', False)

        # 检查任务是否已在运行
        if task.id in self._running_tasks:
            thread, _, _, _ = self._running_tasks[task.id]
            if thread.isRunning():
                if not kill_previous:
                    logger.info(f"[BackgroundTaskManager] 任务 {task.name} 已在运行，跳过启动")
                    return False  # 任务已在运行且不允许终止
                else:
                    logger.info(f"[BackgroundTaskManager] 任务 {task.name} 已在运行，正在终止...")
                    self.stop_task(task.id)
            else:
                # 线程已结束，清理旧记录
                logger.info(f"[BackgroundTaskManager] 清理已完成的任务记录: {task.name}")
                del self._running_tasks[task.id]

        from datetime import datetime
        output_buffer = []
        start_time = datetime.now()

        # 创建新线程
        logger.info(f"[BackgroundTaskManager] 创建 ExecutionThread，任务类型: {task.task_type}")
        thread = ExecutionThread(task, kill_previous=kill_previous)

        # 使用闭包捕获正确的变量
        task_id = task.id
        task_name = task.name

        def on_output(text, t):
            output_buffer.append((text, t))
            logger.debug(f"[BackgroundTaskManager] 任务 {task_name} 输出: {text[:50]}...")

        def on_finished(code, dur):
            logger.info(f"[BackgroundTaskManager] 任务 {task_name} 完成，退出码: {code}, 耗时: {dur}秒")
            self._on_task_finished(task_id, code, dur)

        thread.output_received.connect(on_output)
        thread.execution_finished.connect(on_finished)

        logger.info(f"[BackgroundTaskManager] 启动线程: {task.name}")
        thread.start()

        # 检查线程是否真的启动了
        import time
        time.sleep(0.1)  # 等待一小段时间
        if thread.isRunning():
            logger.info(f"[BackgroundTaskManager] 线程已启动并正在运行: {task.name}")
        else:
            logger.warning(f"[BackgroundTaskManager] 线程可能没有正确启动: {task.name}")

        self._running_tasks[task.id] = (thread, output_buffer, task, start_time)
        logger.info(f"[BackgroundTaskManager] 任务已添加到运行列表，当前运行任务数: {len(self._running_tasks)}")
        return True

    def _on_task_finished(self, task_id: str, exit_code: int, duration: float):
        """任务完成回调"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[BackgroundTaskManager._on_task_finished] 任务完成: {task_id}, 退出码: {exit_code}")

        if task_id in self._running_tasks:
            _thread, buffer, task, start_time = self._running_tasks[task_id]
            # 添加完成信息到缓冲区
            if exit_code == 0:
                buffer.append((f"\n{'=' * 50}\n执行成功，退出代码: {exit_code}，耗时: {duration:.2f}秒\n", 'info'))
            else:
                buffer.append((f"\n{'=' * 50}\n执行失败，退出代码: {exit_code}，耗时: {duration:.2f}秒\n", 'stderr'))

            # 更新任务状态
            self._update_task_status(task, exit_code)

            # 记录日志
            if self._task_logger:
                self._save_log(task, buffer, exit_code, duration, start_time)

            # 发送 webhook 通知
            self._send_webhook_notification(task, buffer, exit_code, duration, start_time)

    def _update_task_status(self, task: Task, exit_code: int):
        """更新任务状态"""
        from datetime import datetime
        from core.models import TaskStatus

        task.status = TaskStatus.SUCCESS if exit_code == 0 else TaskStatus.FAILED
        task.last_run = datetime.now().isoformat()
        task.last_result = f"Exit code: {exit_code}"
        self._storage.update_task(task)

    def _send_webhook_notification(self, task: Task, buffer: list, exit_code: int, duration: float, start_time):
        """发送 webhook 通知"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[BackgroundTaskManager._send_webhook_notification] 开始处理webhook，任务: {task.name}")

        # 检查任务是否配置了 webhook
        if not task.webhook_ids:
            logger.info(f"[BackgroundTaskManager._send_webhook_notification] 任务没有配置webhook，跳过")
            buffer.append(("\n[Webhook] 任务没有配置 webhook，跳过推送\n", 'info'))
            return

        from datetime import datetime
        from core.executor import ExecutionResult
        from core.models import TaskType, WebhookStorage, TaskStorage, SettingsStorage

        buffer.append(("\n[Webhook] 开始处理 webhook 通知...\n", 'info'))

        # 从缓冲区提取 stdout 和 stderr
        stdout_lines = []
        stderr_lines = []
        for text, output_type in buffer:
            if output_type == 'stdout' or output_type == 'info':
                stdout_lines.append(text)
            elif output_type == 'stderr':
                stderr_lines.append(text)

        stdout_text = ''.join(stdout_lines)
        stderr_text = ''.join(stderr_lines)

        # 解析同步任务的文件列表（从 DONE: 行中提取）
        sync_details = []
        if task.task_type == TaskType.SYNC:
            import re
            for line in stdout_text.split('\n'):
                # 格式: DONE:SUCCESS/FAILED:操作:文件路径:字节数
                match = re.match(r'DONE:(SUCCESS|FAILED):(.+?):(.+?)(?::(\d+))?$', line)
                if match:
                    status = match.group(1)
                    action = match.group(2)
                    file_path = match.group(3)
                    bytes_count = int(match.group(4)) if match.group(4) else 0
                    success = (status == 'SUCCESS')
                    sync_details.append((action, file_path, success, bytes_count))

        # 创建 ExecutionResult 对象
        result = ExecutionResult(
            success=(exit_code == 0),
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            start_time=start_time,
            end_time=datetime.now(),
            duration=duration,
            extra_data={'sync_details': sync_details} if sync_details else {}
        )

        # 获取 webhook 配置
        webhook_storage = WebhookStorage()
        webhooks = task.get_webhooks(webhook_storage)

        logger.info(f"[BackgroundTaskManager._send_webhook_notification] 获取到 {len(webhooks)} 个webhook配置")
        buffer.append((f"[Webhook] 获取到 {len(webhooks)} 个 webhook 配置\n", 'info'))

        if not webhooks:
            logger.warning(f"[BackgroundTaskManager._send_webhook_notification] 无法找到webhook配置")
            buffer.append(("[Webhook] 警告: 无法找到 webhook 配置\n", 'stderr'))
            return

        # 从调度器获取 notifier
        from core.scheduler import TaskScheduler
        storage = TaskStorage()
        settings_storage = SettingsStorage()
        scheduler = TaskScheduler(storage, settings_storage, webhook_storage)

        # 根据任务类型构建通知参数
        if task.task_type == TaskType.SYNC:
            params = scheduler._build_sync_notification_params(task, result)
        else:
            params = result.to_notification_params(task.name)

        # 使用输出解析器提取变量并合并
        if task.output_parsers:
            from core.output_parser import OutputParserEngine
            full_output = result.stdout + "\n" + result.stderr
            parsed_vars = OutputParserEngine.parse_all(full_output, task.output_parsers)
            params.update(parsed_vars)

        logger.info(f"[BackgroundTaskManager._send_webhook_notification] 准备发送webhook，参数: {list(params.keys())}")
        buffer.append((f"[Webhook] 解析到 {len(sync_details)} 个文件操作记录\n", 'info'))

        # 异步发送 webhook
        try:
            scheduler.notifier.notify_async(webhooks, params)
            logger.info(f"[BackgroundTaskManager._send_webhook_notification] 已触发异步发送，共 {len(webhooks)} 个webhook")
            buffer.append((f"[Webhook] 已触发异步发送，共 {len(webhooks)} 个 webhook\n", 'info'))
        except Exception as e:
            logger.error(f"[BackgroundTaskManager._send_webhook_notification] 发送webhook失败: {e}", exc_info=True)
            buffer.append((f"[Webhook] 发送失败: {e}\n", 'stderr'))

    def _save_log(self, task: Task, buffer: list, exit_code: int, duration: float, start_time):
        """保存执行日志"""
        from datetime import datetime
        from core.executor import ExecutionResult
        from core.models import TaskType

        # 从缓冲区提取 stdout 和 stderr
        # info 类型的输出也归入 stdout（包含任务开始、进度等信息）
        stdout_lines = []
        stderr_lines = []
        for text, output_type in buffer:
            if output_type == 'stdout' or output_type == 'info':
                stdout_lines.append(text)
            elif output_type == 'stderr':
                stderr_lines.append(text)

        end_time = datetime.now()

        # 创建 ExecutionResult 对象
        result = ExecutionResult(
            success=(exit_code == 0),
            exit_code=exit_code,
            stdout=''.join(stdout_lines),
            stderr=''.join(stderr_lines),
            start_time=start_time,
            end_time=end_time,
            duration=duration
        )

        # 使用输出解析器解析控制台输出
        parsed_vars = {}
        if task.output_parsers:
            from core.output_parser import OutputParserEngine
            full_output = result.stdout + "\n" + result.stderr
            parsed_vars = OutputParserEngine.parse_all(full_output, task.output_parsers)

        # 根据任务类型记录日志
        try:
            if task.task_type == TaskType.SYNC:
                # 同步任务
                self._task_logger.log_sync_execution(
                    task_id=task.id,
                    task_name=task.name,
                    sync_config=task.sync_config,
                    result=result,
                    parsed_vars=parsed_vars
                )
            else:
                # 命令任务
                self._task_logger.log_execution(
                    task_id=task.id,
                    task_name=task.name,
                    command=task.command,
                    working_dir=task.working_dir,
                    result=result,
                    parsed_vars=parsed_vars
                )
        except Exception as e:
            print(f"保存日志失败: {e}")

    def is_running(self, task_id: str) -> bool:
        """检查任务是否在运行"""
        if task_id not in self._running_tasks:
            return False
        thread, _, _, _ = self._running_tasks[task_id]
        return thread.isRunning()

    def get_output(self, task_id: str) -> list:
        """获取任务输出"""
        if task_id in self._running_tasks:
            _, buffer, _, _ = self._running_tasks[task_id]
            return list(buffer)
        return []

    def stop_task(self, task_id: str) -> bool:
        """停止任务（非阻塞）"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[BackgroundTaskManager.stop_task] 收到停止请求，任务ID: {task_id}")

        if task_id in self._running_tasks:
            thread, buffer, task, start_time = self._running_tasks[task_id]
            if thread.isRunning():
                logger.info(f"[BackgroundTaskManager.stop_task] 线程正在运行，调用 thread.stop()")
                # 添加停止信息到缓冲区
                buffer.append(("\n正在停止任务...\n", 'info'))
                # 调用线程的 stop 方法（非阻塞）
                thread.stop()
                logger.info(f"[BackgroundTaskManager.stop_task] thread.stop() 已调用")
                return True
            else:
                logger.warning(f"[BackgroundTaskManager.stop_task] 线程已不在运行")
        else:
            logger.warning(f"[BackgroundTaskManager.stop_task] 任务ID不在运行列表中")
        return False

    def clear_task(self, task_id: str):
        """清理已完成的任务"""
        if task_id in self._running_tasks:
            thread, _, _, _ = self._running_tasks[task_id]
            if not thread.isRunning():
                del self._running_tasks[task_id]

    def get_running_task_ids(self) -> list:
        """获取所有运行中的任务ID"""
        return [tid for tid, (thread, _, _, _) in self._running_tasks.items() if thread.isRunning()]


class MainWindow(QMainWindow):
    """主窗口"""

    task_updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.storage = TaskStorage()
        self.webhook_storage = WebhookStorage()
        self.parser_storage = ParserStorage()
        self.settings_storage = SettingsStorage()
        self.settings = self.settings_storage.load()
        self.scheduler = TaskScheduler(self.storage, self.settings_storage, self.webhook_storage)

        # 后台任务管理器 - 共享调度器的日志记录器和存储
        self.bg_task_manager = BackgroundTaskManager()
        self.bg_task_manager.set_logger(self.scheduler.task_logger)
        self.bg_task_manager.set_storage(self.storage)

        # 当前页面索引
        self.current_page = 0  # 0: 任务, 1: Webhook, 2: 解析器

        # 任务进度跟踪 - 用于在主窗口显示进度条
        self._task_progress = {}  # {task_id: {'percent': 0-100, 'text': 'status text'}}
        self._task_progress_widgets = {}  # {task_id: TaskProgressWidget}

        # 设置回调
        self.scheduler.set_callbacks(
            on_start=self._on_task_start,
            on_complete=self._on_task_complete
        )

        self._init_ui()
        self._init_tray()
        self._load_tasks()
        self._load_webhooks()
        self._load_parsers()

        # 启动调度器并加载所有任务
        self.scheduler.start()
        self.scheduler.load_all_tasks()  # 加载任务到调度器，这样才能计算下次执行时间

        # 定时刷新（间隔稍长，避免频繁刷新导致按钮点击失效和CPU占用）
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._safe_refresh)
        self.refresh_timer.start(30000)  # 30秒刷新一次（降低CPU占用）
        self._mouse_over_table = False  # 鼠标是否在表格上

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("任务调度器 - Task Scheduler")
        self.setMinimumSize(1100, 650)
        self.resize(1200, 700)

        # 设置窗口图标
        import os
        import sys
        if getattr(sys, 'frozen', False):
            # 打包后：资源在临时目录 _MEIPASS
            base_path = sys._MEIPASS
        else:
            # 开发环境路径
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        icon_path = os.path.join(base_path, 'logo.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            self._app_icon = QIcon(icon_path)  # 保存引用供托盘使用
        else:
            self._app_icon = None

        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 工具栏（固定不可移动）
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.addToolBar(self.toolbar)

        # 添加按钮（动态文本）
        self.add_action = QAction("添加任务", self)
        self.add_action.triggered.connect(self._add_item)
        self.toolbar.addAction(self.add_action)

        refresh_action = QAction("刷新", self)
        refresh_action.triggered.connect(self._refresh_current_page)
        self.toolbar.addAction(refresh_action)

        self.toolbar.addSeparator()

        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self._open_settings)
        self.toolbar.addAction(settings_action)

        # 分页标签
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # 任务页面
        task_page = QWidget()
        task_layout = QVBoxLayout(task_page)
        task_layout.setContentsMargins(0, 0, 0, 0)

        self.task_table = QTableWidget()
        # 兼容旧代码 - 提前设置
        self.table = self.task_table
        self.task_table.setColumnCount(7)
        self.task_table.setHorizontalHeaderLabels([
            "名称", "状态", "Cron表达式", "上次执行", "下次执行", "Webhooks", "操作"
        ])
        self.task_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.task_table.setColumnWidth(6, 320)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.task_table.customContextMenuRequested.connect(self._show_task_context_menu)
        task_layout.addWidget(self.task_table)

        self.tab_widget.addTab(task_page, "📋 任务管理")

        # Webhook 配置页面
        webhook_page = QWidget()
        webhook_layout = QVBoxLayout(webhook_page)
        webhook_layout.setContentsMargins(0, 0, 0, 0)

        self.webhook_table = QTableWidget()
        self.webhook_table.setColumnCount(5)
        self.webhook_table.setHorizontalHeaderLabels([
            "名称", "URL", "方法", "启用", "操作"
        ])
        self.webhook_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.webhook_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.webhook_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.webhook_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.webhook_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.webhook_table.setColumnWidth(4, 150)
        self.webhook_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.webhook_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.webhook_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.webhook_table.customContextMenuRequested.connect(self._show_webhook_context_menu)
        webhook_layout.addWidget(self.webhook_table)

        self.tab_widget.addTab(webhook_page, "🔗 Webhook 配置")

        # 解析器配置页面
        parser_page = QWidget()
        parser_layout = QVBoxLayout(parser_page)
        parser_layout.setContentsMargins(0, 0, 0, 0)

        self.parser_table = QTableWidget()
        self.parser_table.setColumnCount(5)
        self.parser_table.setHorizontalHeaderLabels([
            "名称", "变量名", "类型", "启用", "操作"
        ])
        self.parser_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.parser_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.parser_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.parser_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.parser_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.parser_table.setColumnWidth(4, 150)
        self.parser_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.parser_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.parser_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.parser_table.customContextMenuRequested.connect(self._show_parser_context_menu)
        parser_layout.addWidget(self.parser_table)

        self.tab_widget.addTab(parser_page, "🔧 解析器模板")

        # 连接标签切换事件（在所有表格创建后）
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # 状态栏（添加进度条）
        from PyQt5.QtWidgets import QProgressBar
        self.status_progress = QProgressBar()
        self.status_progress.setMaximumWidth(200)
        self.status_progress.setTextVisible(True)
        self.status_progress.setFormat("%p%")
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        self.status_progress.hide()  # 默认隐藏
        self.statusBar().addPermanentWidget(self.status_progress)
        self.statusBar().showMessage("就绪")

    def _on_tab_changed(self, index):
        """标签页切换"""
        self.current_page = index
        if index == 0:
            self.add_action.setText("添加任务")
            self._load_tasks()
        elif index == 1:
            self.add_action.setText("添加 Webhook")
            self._load_webhooks()
        else:
            self.add_action.setText("添加解析器")
            self._load_parsers()

    def _add_item(self):
        """添加项目（根据当前页面）"""
        if self.current_page == 0:
            self._add_task()
        elif self.current_page == 1:
            self._add_webhook()
        else:
            self._add_parser()

    def _safe_refresh(self):
        """安全刷新 - 检查鼠标是否在表格区域，避免刷新时按钮失效"""
        # 检查鼠标是否在当前表格区域内
        from PyQt5.QtGui import QCursor

        current_table = None
        if self.current_page == 0:
            current_table = self.table
        elif self.current_page == 1:
            current_table = self.webhook_table
        else:
            current_table = self.parser_table

        if current_table:
            # 获取表格的全局位置和大小
            table_rect = current_table.rect()
            global_pos = current_table.mapToGlobal(table_rect.topLeft())
            table_rect.moveTopLeft(global_pos)

            # 如果鼠标在表格区域内，跳过本次刷新
            if table_rect.contains(QCursor.pos()):
                return

        self._refresh_current_page()

    def _refresh_current_page(self):
        """刷新当前页面"""
        if self.current_page == 0:
            self._load_tasks()
        elif self.current_page == 1:
            self._load_webhooks()
        else:
            self._load_parsers()
    
    def _init_tray(self):
        """初始化系统托盘"""
        self.tray = QSystemTrayIcon(self)

        # 使用自定义图标（复用 _init_ui 中加载的图标）
        if hasattr(self, '_app_icon') and self._app_icon:
            self.tray.setIcon(self._app_icon)
        else:
            self.tray.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        self.tray.setToolTip("任务调度器")
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("显示主窗口")
        show_action.triggered.connect(self.show)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._quit_app)
        
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
    
    def _load_tasks(self):
        """加载任务列表"""
        # 暂停定时刷新，避免刷新过程中按钮被重建导致点击失效
        if hasattr(self, 'refresh_timer') and self.refresh_timer.isActive():
            self.refresh_timer.stop()
            timer_was_active = True
        else:
            timer_was_active = False

        try:
            tasks = self.storage.load_tasks()
            self.table.setRowCount(len(tasks))

            for row, task in enumerate(tasks):
                self._set_table_row(row, task)

            self.statusBar().showMessage(f"已加载 {len(tasks)} 个任务")
        finally:
            # 恢复定时刷新
            if timer_was_active:
                self.refresh_timer.start(10000)

    def update_task_progress(self, task_id: str, percent: int, text: str):
        """更新单个任务的进度（不重新加载整个表格）"""
        # 更新进度信息
        self._task_progress[task_id] = {
            'percent': percent,
            'text': text
        }

        # 查找任务在表格中的行号
        row = -1
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)  # 名称列
            if item and item.data(Qt.UserRole) == task_id:
                row = i
                break

        if row == -1:
            return  # 任务不在表格中

        # 检查是否已有进度 widget
        if task_id in self._task_progress_widgets:
            # 更新现有 widget
            self._task_progress_widgets[task_id].set_progress(percent, text)
        else:
            # 创建新的进度 widget
            from ui.progress_widget import TaskProgressWidget
            progress_widget = TaskProgressWidget()
            progress_widget.set_progress(percent, text)
            self._task_progress_widgets[task_id] = progress_widget
            self.table.setCellWidget(row, 1, progress_widget)
    
    def _set_table_row(self, row: int, task: Task):
        """设置表格行"""
        # 名称
        name_item = QTableWidgetItem(task.name)
        name_item.setData(Qt.UserRole, task.id)
        self.table.setItem(row, 0, name_item)

        # 状态 - 根据任务状态显示不同内容
        from ui.progress_widget import TaskProgressWidget

        # 检查是否有进度信息（同步任务）
        if hasattr(self, '_task_progress') and task.id in self._task_progress:
            # 显示进度条
            progress_info = self._task_progress[task.id]

            # 复用或创建 progress_widget
            if task.id in self._task_progress_widgets:
                progress_widget = self._task_progress_widgets[task.id]
            else:
                progress_widget = TaskProgressWidget()
                self._task_progress_widgets[task.id] = progress_widget
                self.table.setCellWidget(row, 1, progress_widget)

            progress_widget.set_progress(progress_info['percent'], progress_info['text'])
        else:
            # 清除进度 widget（如果有）
            if task.id in self._task_progress_widgets:
                del self._task_progress_widgets[task.id]

            # 显示状态文字
            status_text_map = {
                TaskStatus.PENDING: "等待中",
                TaskStatus.RUNNING: "执行中",
                TaskStatus.SUCCESS: "成功",
                TaskStatus.FAILED: "失败",
                TaskStatus.DISABLED: "已禁用"
            }
            status_item = QTableWidgetItem(status_text_map.get(task.status, task.status.value))
            status_colors = {
                TaskStatus.PENDING: QColor(100, 100, 100),
                TaskStatus.RUNNING: QColor(0, 120, 215),
                TaskStatus.SUCCESS: QColor(0, 150, 0),
                TaskStatus.FAILED: QColor(200, 0, 0),
                TaskStatus.DISABLED: QColor(150, 150, 150)
            }
            status_item.setForeground(status_colors.get(task.status, QColor(0, 0, 0)))
            self.table.setItem(row, 1, status_item)
        
        # Cron
        self.table.setItem(row, 2, QTableWidgetItem(task.cron_expression))
        
        # 上次执行 - 格式化显示（去掉T）
        if task.last_run:
            last_run = task.last_run[:19].replace("T", " ")
        else:
            last_run = "-"
        self.table.setItem(row, 3, QTableWidgetItem(last_run))
        
        # 下次执行
        next_run = self.scheduler.get_next_run_time(task.id)
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "-"
        self.table.setItem(row, 4, QTableWidgetItem(next_run_str))

        # Webhooks 数量 - 显示已启用的 webhook 数量
        import logging
        logger = logging.getLogger(__name__)

        webhooks = task.get_webhooks(self.webhook_storage)
        webhook_count = len([w for w in webhooks if w.enabled])

        logger.debug(f"任务 '{task.name}': webhook_ids={task.webhook_ids}, 获取到 {len(webhooks)} 个webhook配置, 启用的有 {webhook_count} 个")

        self.table.setItem(row, 5, QTableWidgetItem(str(webhook_count)))
        
        # 操作按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(2, 2, 2, 2)
        btn_layout.setSpacing(3)

        # 根据任务是否在后台运行显示不同按钮
        if self.bg_task_manager.is_running(task.id):
            # 后台运行中：显示查看输出和停止按钮
            view_btn = QPushButton("📺 查看")
            view_btn.setToolTip("查看后台任务输出")
            view_btn.clicked.connect(lambda _, t=task: self._show_background_output(t))
            btn_layout.addWidget(view_btn)

            stop_btn = QPushButton("⏹ 停止")
            stop_btn.setToolTip("停止后台任务")
            stop_btn.clicked.connect(lambda _, t=task: self._stop_background_task(t))
            btn_layout.addWidget(stop_btn)
        else:
            # 未运行：显示两种执行方式
            run_btn = QPushButton("▶ 执行")
            run_btn.setToolTip("有窗口执行（显示实时输出）")
            run_btn.clicked.connect(lambda _, t=task: self._run_task_with_window(t))
            btn_layout.addWidget(run_btn)

            bg_run_btn = QPushButton("🔇 后台")
            bg_run_btn.setToolTip("无窗口后台执行")
            bg_run_btn.clicked.connect(lambda _, t=task: self._run_task_background(t))
            btn_layout.addWidget(bg_run_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(lambda _, t=task: self._edit_task(t))
        btn_layout.addWidget(edit_btn)

        log_btn = QPushButton("日志")
        log_btn.setToolTip("查看任务执行日志")
        log_btn.clicked.connect(lambda _, t=task: self._view_task_logs(t))
        btn_layout.addWidget(log_btn)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda _, t=task: self._delete_task(t))
        btn_layout.addWidget(del_btn)

        self.table.setCellWidget(row, 6, btn_widget)
    
    def _refresh_table(self):
        """刷新表格"""
        self._load_tasks()

    def _add_task(self):
        """添加任务 - 弹出选择对话框"""
        from PyQt5.QtWidgets import QMenu
        from .sync_task_dialog import SyncTaskDialog
        from .cleanup_task_dialog import CleanupTaskDialog

        # 创建选择菜单
        menu = QMenu(self)
        cmd_action = menu.addAction("📋 命令任务")
        cmd_action.setToolTip("执行批处理命令或脚本")
        sync_action = menu.addAction("🔄 同步任务")
        sync_action.setToolTip("文件/文件夹同步")
        cleanup_action = menu.addAction("🧹 清理任务")
        cleanup_action.setToolTip("自动清理目录文件")

        # 在工具栏按钮位置显示菜单
        action = menu.exec_(self.toolbar.mapToGlobal(self.toolbar.actionGeometry(self.add_action).bottomLeft()))

        if action == cmd_action:
            # 命令任务
            dialog = TaskDialog(self)
            if dialog.exec_():
                task = dialog.get_task()
                self.storage.add_task(task)
                self.scheduler.add_task(task)
                self._load_tasks()
                self.statusBar().showMessage(f"任务 '{task.name}' 已添加")
        elif action == sync_action:
            # 同步任务
            dialog = SyncTaskDialog(self)
            if dialog.exec_():
                task = dialog.get_task()
                self.storage.add_task(task)
                self.scheduler.add_task(task)
                self._load_tasks()
                self.statusBar().showMessage(f"同步任务 '{task.name}' 已添加")
        elif action == cleanup_action:
            # 清理任务
            dialog = CleanupTaskDialog(task=None, parent=self)
            if dialog.exec_():
                task = dialog.get_task()
                self.storage.add_task(task)
                self.scheduler.add_task(task)
                self._load_tasks()
                self.statusBar().showMessage(f"清理任务 '{task.name}' 已添加")

    def _edit_task(self, task: Task):
        """编辑任务 - 根据任务类型选择对话框"""
        from core.models import TaskType
        from .sync_task_dialog import SyncTaskDialog
        from .cleanup_task_dialog import CleanupTaskDialog

        if task.task_type == TaskType.SYNC:
            dialog = SyncTaskDialog(self, task)
        elif task.task_type == TaskType.CLEANUP:
            dialog = CleanupTaskDialog(task=task, parent=self)
        else:
            dialog = TaskDialog(self, task)

        if dialog.exec_():
            updated_task = dialog.get_task()
            self.storage.update_task(updated_task)
            self.scheduler.update_task(updated_task)
            self._load_tasks()
            self.statusBar().showMessage(f"任务 '{updated_task.name}' 已更新")

    def _delete_task(self, task: Task):
        """删除任务"""
        if MsgBox.question(self, "确认删除", f"确定要删除任务 '{task.name}' 吗？"):
            self.storage.delete_task(task.id)
            self.scheduler.remove_task(task.id)
            self._load_tasks()
            self.statusBar().showMessage(f"任务 '{task.name}' 已删除")

    def _run_task_with_window(self, task: Task):
        """有窗口执行任务（显示实时输出）

        统一使用后台任务管理器执行，同时打开输出窗口显示进度
        """
        from core.models import TaskType

        # 检查任务是否已在运行
        if self.bg_task_manager.is_running(task.id):
            # 任务已在运行，直接打开输出窗口
            self._show_background_output(task)
            return

        # 启动后台任务
        self.bg_task_manager.start_task(task)
        self.statusBar().showMessage(f"任务 '{task.name}' 已启动")

        # 打开输出窗口
        self._show_background_output(task)
        self._load_tasks()

    def _run_sync_task_with_window(self, task: Task):
        """有窗口执行同步任务"""
        from core.sync_engine import SyncEngine
        from ui.sync_progress_dialog import SyncProgressDialog, SyncWorkerThread

        if not task.sync_config:
            MsgBox.warning(self, "错误", "同步配置为空")
            return

        # 创建同步引擎
        engine = SyncEngine(task.sync_config, thread_count=task.sync_config.max_concurrent or 4)

        # 连接
        success, msg = engine.connect()
        if not success:
            MsgBox.critical(self, "连接失败", msg)
            return

        # 比较文件 - 获取所有比较结果
        sync_items = engine.compare()

        # 过滤出需要处理的文件
        items_to_process = [
            item for item in sync_items
            if item.action.value not in ('equal', 'skip', 'conflict')
        ]

        total_files = len(items_to_process)

        # 即使没有需要同步的文件，也显示比较结果
        if total_files == 0:
            # 显示比较结果对话框
            from core.sync_engine import SyncResult
            from datetime import datetime

            # 创建一个空的同步结果
            result = SyncResult()
            result.start_time = datetime.now()
            result.end_time = datetime.now()
            result.success = True
            result.skipped_files = len(sync_items)

            # 记录所有比较过的文件
            for item in sync_items:
                result.details.append(('已是最新', item.relative_path, True, 0))

            engine.disconnect()

            # 显示结果
            MsgBox.information(self, "同步完成",
                f"所有文件已是最新，无需同步。\n\n"
                f"比较文件数: {len(sync_items)}")

            # 发送 webhook 通知（即使没有需要同步的文件）
            webhooks = task.get_webhooks(self.webhook_storage)
            if webhooks:
                from core.executor import ExecutionResult
                exec_result = ExecutionResult(
                    success=True,
                    exit_code=0,
                    stdout=f"所有文件已是最新，无需同步。比较文件数: {len(sync_items)}",
                    stderr="",
                    start_time=result.start_time,
                    end_time=result.end_time,
                    duration=0
                )
                params = self.scheduler._build_sync_notification_params(task, exec_result)
                self.scheduler.notifier.notify_async(webhooks, params)

            # 更新任务状态
            task.status = TaskStatus.SUCCESS
            task.last_run = datetime.now().isoformat()
            task.last_result = f"无需同步 (比较: {len(sync_items)} 个文件)"
            self.storage.update_task(task)
            self._load_tasks()
            return

        # 估算总大小
        total_bytes = sum(
            (item.source_file.size if item.source_file else 0) or
            (item.target_file.size if item.target_file else 0)
            for item in items_to_process
        )

        # 创建进度对话框 - 传递所有比较过的文件（包括已是最新的）
        progress_dialog = SyncProgressDialog(engine, total_files, total_bytes, sync_items, self)

        # 创建工作线程 - 保存为对话框属性防止被垃圾回收
        # 传递预先比较好的同步项，避免重复比较
        progress_dialog.sync_worker = SyncWorkerThread(engine, items_to_process, progress_dialog)

        # 连接信号
        def on_progress(msg, current, total, bytes_transferred):
            progress_dialog.update_progress(msg, current, total, bytes_transferred)

        def on_file_completed(file_path, action, success, bytes_transferred):
            progress_dialog.add_result_row(action, file_path, success, bytes_transferred)

        def on_finished(result):
            engine.disconnect()

            # 更新所有未完成的文件为失败状态
            for row in range(progress_dialog.result_table.rowCount()):
                status_item = progress_dialog.result_table.item(row, 0)
                if status_item and "进行中" in status_item.text():
                    status_item.setText("✗ 失败")
                    status_item.setForeground(Qt.red)

            progress_dialog.on_sync_finished(result)

            # 更新任务状态
            from core.models import TaskStatus
            from datetime import datetime
            task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
            # 确保 last_run 是 ISO 格式字符串
            if result.end_time:
                if isinstance(result.end_time, datetime):
                    task.last_run = result.end_time.isoformat()
                else:
                    task.last_run = str(result.end_time)
            task.last_result = f"复制: {result.copied_files}, 更新: {result.updated_files}, 删除: {result.deleted_files}"
            if result.errors:
                task.last_result += f" (错误: {len(result.errors)})"
            self.storage.update_task(task)

            # 记录日志
            if self.scheduler.task_logger:
                from core.executor import ExecutionResult
                duration = (result.end_time - result.start_time).total_seconds() if result.end_time and result.start_time else 0

                # 构建详细的同步日志
                detail_lines = []
                for detail in result.details:
                    action_name, file_path, success, bytes_count = detail
                    status = "✓" if success else "✗"
                    size_str = f" ({bytes_count} bytes)" if bytes_count > 0 else ""
                    detail_lines.append(f"{status} [{action_name}] {file_path}{size_str}")

                stdout_content = f"复制: {result.copied_files}, 更新: {result.updated_files}, 删除: {result.deleted_files}\n\n"
                if detail_lines:
                    stdout_content += "详细操作:\n" + "\n".join(detail_lines)

                exec_result = ExecutionResult(
                    success=result.success,
                    exit_code=0 if result.success else 1,
                    stdout=stdout_content,
                    stderr="\n".join(result.errors) if result.errors else "",
                    start_time=result.start_time,
                    end_time=result.end_time,
                    duration=duration
                )
                self.scheduler.task_logger.log_sync_execution(
                    task_id=task.id,
                    task_name=task.name,
                    sync_config=task.sync_config,
                    result=exec_result
                )

            # 发送 webhook 通知
            webhooks = task.get_webhooks(self.webhook_storage)
            if webhooks:
                from core.executor import ExecutionResult
                duration = (result.end_time - result.start_time).total_seconds() if result.end_time and result.start_time else 0
                exec_result = ExecutionResult(
                    success=result.success,
                    exit_code=0 if result.success else 1,
                    stdout=f"复制: {result.copied_files}, 更新: {result.updated_files}, 删除: {result.deleted_files}",
                    stderr="\n".join(result.errors) if result.errors else "",
                    start_time=result.start_time,
                    end_time=result.end_time,
                    duration=duration
                )
                params = self.scheduler._build_sync_notification_params(task, exec_result)
                self.scheduler.notifier.notify_async(webhooks, params)

        progress_dialog.sync_worker.progress_updated.connect(on_progress)
        progress_dialog.sync_worker.file_completed.connect(on_file_completed)
        progress_dialog.sync_worker.sync_finished.connect(on_finished)

        # 启动工作线程
        progress_dialog.sync_worker.start()

        # 显示进度对话框
        try:
            progress_dialog.exec_()
        except Exception as e:
            import traceback
            traceback.print_exc()
            MsgBox.critical(self, "错误", f"同步过程中发生错误: {str(e)}")

    def _run_task_background(self, task: Task):
        """无窗口后台执行任务"""
        # 统一使用后台任务管理器执行所有任务类型
        if self.bg_task_manager.is_running(task.id):
            # 任务已在运行，询问是否查看输出
            if MsgBox.question(self, "任务运行中",
                f"任务 '{task.name}' 正在后台运行中。\n\n是否打开输出窗口查看？"):
                self._show_background_output(task)
            return

        # 启动后台任务
        self.bg_task_manager.start_task(task)
        self.statusBar().showMessage(f"任务 '{task.name}' 已在后台启动")
        self._load_tasks()

    def _show_background_output(self, task: Task):
        """显示后台任务的输出窗口"""
        from core.models import TaskType

        # 同步任务使用专门的进度对话框
        if task.task_type == TaskType.SYNC:
            from .background_sync_dialog import BackgroundSyncProgressDialog
            dialog = BackgroundSyncProgressDialog(self, task, self.bg_task_manager)
        else:
            from .background_output_dialog import BackgroundOutputDialog
            dialog = BackgroundOutputDialog(self, task, self.bg_task_manager)

        dialog.exec_()
        self._load_tasks()

    def _stop_background_task(self, task: Task):
        """停止后台任务"""
        self.bg_task_manager.stop_task(task.id)
        self.statusBar().showMessage(f"任务 '{task.name}' 已停止")
        self._load_tasks()

    def _show_task_context_menu(self, pos):
        """显示任务右键菜单"""
        item = self.task_table.itemAt(pos)
        if not item:
            return

        row = item.row()
        task_id = self.task_table.item(row, 0).data(Qt.UserRole)
        task = self.storage.get_task(task_id)
        if not task:
            return

        menu = QMenu(self)

        # 根据任务是否在后台运行显示不同选项
        if self.bg_task_manager.is_running(task.id):
            view_output_action = menu.addAction("📺 查看输出")
            stop_action = menu.addAction("⏹ 停止执行")
            run_window_action = None
            run_bg_action = None
        else:
            run_window_action = menu.addAction("▶ 有窗口执行")
            run_bg_action = menu.addAction("🔇 后台执行")
            view_output_action = None
            stop_action = None

        edit_action = menu.addAction("编辑")
        log_action = menu.addAction("查看日志")
        menu.addSeparator()
        toggle_action = menu.addAction("禁用" if task.enabled else "启用")
        menu.addSeparator()
        delete_action = menu.addAction("删除")

        action = menu.exec_(self.task_table.viewport().mapToGlobal(pos))
        if action == run_window_action and run_window_action:
            self._run_task_with_window(task)
        elif action == run_bg_action and run_bg_action:
            self._run_task_background(task)
        elif action == view_output_action and view_output_action:
            self._show_background_output(task)
        elif action == stop_action and stop_action:
            self.bg_task_manager.stop_task(task.id)
            self.statusBar().showMessage(f"任务 '{task.name}' 已停止")
            self._load_tasks()
        elif action == edit_action:
            self._edit_task(task)
        elif action == log_action:
            self._view_task_logs(task)
        elif action == toggle_action:
            task.enabled = not task.enabled
            task.status = TaskStatus.PENDING if task.enabled else TaskStatus.DISABLED
            self.storage.update_task(task)
            self.scheduler.update_task(task)
            self._load_tasks()
        elif action == delete_action:
            self._delete_task(task)

    def _view_task_logs(self, task: Task):
        """查看任务执行日志"""
        dialog = LogViewerDialog(self, task.name, self.settings.log_dir)
        dialog.exec_()

    # ==================== Webhook 管理方法 ====================

    def _load_webhooks(self):
        """加载 Webhook 列表"""
        webhooks = self.webhook_storage.load_webhooks()
        self.webhook_table.setRowCount(len(webhooks))

        for row, webhook in enumerate(webhooks):
            self._set_webhook_row(row, webhook)

        self.statusBar().showMessage(f"已加载 {len(webhooks)} 个 Webhook 配置")

    def _set_webhook_row(self, row: int, webhook):
        """设置 Webhook 表格行"""
        # 名称
        name_item = QTableWidgetItem(webhook.name)
        name_item.setData(Qt.UserRole, webhook.id)
        self.webhook_table.setItem(row, 0, name_item)

        # URL
        url_display = webhook.url[:50] + "..." if len(webhook.url) > 50 else webhook.url
        self.webhook_table.setItem(row, 1, QTableWidgetItem(url_display))

        # 方法
        self.webhook_table.setItem(row, 2, QTableWidgetItem(webhook.method))

        # 启用状态
        enabled_item = QTableWidgetItem("✓ 启用" if webhook.enabled else "✗ 禁用")
        enabled_item.setForeground(QColor(0, 150, 0) if webhook.enabled else QColor(150, 150, 150))
        self.webhook_table.setItem(row, 3, enabled_item)

        # 操作按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(2, 2, 2, 2)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(lambda _, w=webhook: self._edit_webhook(w))
        btn_layout.addWidget(edit_btn)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda _, w=webhook: self._delete_webhook(w))
        btn_layout.addWidget(del_btn)

        self.webhook_table.setCellWidget(row, 4, btn_widget)

    def _add_webhook(self):
        """添加 Webhook 配置"""
        dialog = WebhookConfigDialog(self)
        if dialog.exec_():
            webhook = dialog.get_webhook()
            self.webhook_storage.add_webhook(webhook)
            self._load_webhooks()
            self.statusBar().showMessage(f"Webhook '{webhook.name}' 已添加")

    def _edit_webhook(self, webhook):
        """编辑 Webhook 配置"""
        dialog = WebhookConfigDialog(self, webhook)
        if dialog.exec_():
            updated_webhook = dialog.get_webhook()
            self.webhook_storage.update_webhook(updated_webhook)
            self._load_webhooks()
            self.statusBar().showMessage(f"Webhook '{updated_webhook.name}' 已更新")

    def _delete_webhook(self, webhook):
        """删除 Webhook 配置"""
        if MsgBox.question(self, "确认删除", f"确定要删除 Webhook '{webhook.name}' 吗？"):
            self.webhook_storage.delete_webhook(webhook.id)
            self._load_webhooks()
            self.statusBar().showMessage(f"Webhook '{webhook.name}' 已删除")

    def _show_webhook_context_menu(self, pos):
        """显示 Webhook 右键菜单"""
        item = self.webhook_table.itemAt(pos)
        if not item:
            return

        row = item.row()
        webhook_id = self.webhook_table.item(row, 0).data(Qt.UserRole)
        webhook = self.webhook_storage.get_webhook(webhook_id)
        if not webhook:
            return

        menu = QMenu(self)
        edit_action = menu.addAction("编辑")
        toggle_action = menu.addAction("禁用" if webhook.enabled else "启用")
        menu.addSeparator()
        delete_action = menu.addAction("删除")

        action = menu.exec_(self.webhook_table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self._edit_webhook(webhook)
        elif action == toggle_action:
            webhook.enabled = not webhook.enabled
            self.webhook_storage.update_webhook(webhook)
            self._load_webhooks()
        elif action == delete_action:
            self._delete_webhook(webhook)

    # ==================== 解析器管理方法 ====================

    def _load_parsers(self):
        """加载解析器列表"""
        parsers = self.parser_storage.load_parsers()
        self.parser_table.setRowCount(len(parsers))

        for row, parser in enumerate(parsers):
            self._set_parser_row(row, parser)

        self.statusBar().showMessage(f"已加载 {len(parsers)} 个解析器模板")

    def _set_parser_row(self, row: int, parser):
        """设置解析器表格行"""
        # 名称
        name_item = QTableWidgetItem(parser.name or f"规则{row+1}")
        name_item.setData(Qt.UserRole, parser.id)
        self.parser_table.setItem(row, 0, name_item)

        # 变量名
        self.parser_table.setItem(row, 1, QTableWidgetItem(f"{{var_{parser.var_name}}}"))

        # 类型
        type_names = {"regex": "正则", "jsonpath": "JSON", "xpath": "XML", "line": "行", "split": "分隔"}
        self.parser_table.setItem(row, 2, QTableWidgetItem(type_names.get(parser.parser_type, parser.parser_type)))

        # 启用状态
        enabled_item = QTableWidgetItem("✓ 启用" if parser.enabled else "✗ 禁用")
        enabled_item.setForeground(QColor(0, 150, 0) if parser.enabled else QColor(150, 150, 150))
        self.parser_table.setItem(row, 3, enabled_item)

        # 操作按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(2, 2, 2, 2)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(lambda _, p=parser: self._edit_parser(p))
        btn_layout.addWidget(edit_btn)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda _, p=parser: self._delete_parser(p))
        btn_layout.addWidget(del_btn)

        self.parser_table.setCellWidget(row, 4, btn_widget)

    def _add_parser(self):
        """添加解析器 - 使用智能向导"""
        from .smart_parser_wizard import SmartParserWizard
        dialog = SmartParserWizard(self)
        if dialog.exec_():
            parser = dialog.get_parser()
            if parser:
                self.parser_storage.add_parser(parser)
                self._load_parsers()
                self.statusBar().showMessage(f"解析器 '{{var_{parser.var_name}}}' 已添加")

    def _edit_parser(self, parser):
        """编辑解析器"""
        from .parser_dialog import ParserRuleDialog
        dialog = ParserRuleDialog(self, parser)
        if dialog.exec_():
            updated_parser = dialog.get_parser()
            self.parser_storage.update_parser(updated_parser)
            self._load_parsers()
            self.statusBar().showMessage(f"解析器 '{updated_parser.name or updated_parser.var_name}' 已更新")

    def _delete_parser(self, parser):
        """删除解析器"""
        if MsgBox.question(self, "确认删除", f"确定要删除解析器 '{parser.name or parser.var_name}' 吗？"):
            self.parser_storage.delete_parser(parser.id)
            self._load_parsers()
            self.statusBar().showMessage(f"解析器已删除")

    def _show_parser_context_menu(self, pos):
        """显示解析器右键菜单"""
        item = self.parser_table.itemAt(pos)
        if not item:
            return

        row = item.row()
        parser_id = self.parser_table.item(row, 0).data(Qt.UserRole)
        parser = self.parser_storage.get_parser(parser_id)
        if not parser:
            return

        menu = QMenu(self)
        edit_action = menu.addAction("编辑")
        toggle_action = menu.addAction("禁用" if parser.enabled else "启用")
        menu.addSeparator()
        delete_action = menu.addAction("删除")

        action = menu.exec_(self.parser_table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self._edit_parser(parser)
        elif action == toggle_action:
            parser.enabled = not parser.enabled
            self.parser_storage.update_parser(parser)
            self._load_parsers()
        elif action == delete_action:
            self._delete_parser(parser)

    def _on_task_start(self, task: Task):
        """任务开始回调"""
        self.statusBar().showMessage(f"任务 '{task.name}' 正在执行...")
        # 显示进度条（不确定模式）
        self.status_progress.setRange(0, 0)  # 不确定模式
        self.status_progress.show()
        # 刷新任务列表以显示状态变化
        if self.current_page == 0:
            QTimer.singleShot(100, self._load_tasks)

    def _on_task_complete(self, task: Task, result):
        """任务完成回调"""
        status = "成功" if result.success else "失败"
        self.statusBar().showMessage(f"任务 '{task.name}' 执行{status}")
        # 隐藏进度条
        self.status_progress.hide()
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        # 刷新任务列表以显示状态变化
        if self.current_page == 0:
            QTimer.singleShot(100, self._load_tasks)

    def _open_settings(self):
        """打开设置对话框"""
        try:
            dialog = SettingsDialog(self, self.settings)
            if dialog.exec_() and dialog.settings_changed:
                self.settings = dialog.get_settings()
                self.settings_storage.save(self.settings)
                # 更新调度器的日志设置
                self.scheduler.update_log_settings(
                    self.settings.log_enabled,
                    self.settings.log_dir
                )
                self.statusBar().showMessage("设置已保存")
        except Exception as e:
            import traceback
            error_msg = f"打开设置对话框失败:\n{str(e)}\n\n{traceback.format_exc()}"
            MsgBox.critical(self, "错误", error_msg)

    def _tray_activated(self, reason):
        """托盘图标激活"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()

    def _quit_app(self):
        """退出应用 - 确保完全退出所有进程"""
        self._force_quit = True

        # 停止调度器
        try:
            self.scheduler.stop()
        except:
            pass

        # 隐藏托盘图标
        try:
            self.tray.hide()
        except:
            pass

        # 退出 Qt 应用
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()

        # 强制退出 Python 进程（确保所有线程都终止）
        import os
        os._exit(0)

    def closeEvent(self, event):
        """关闭事件 - 根据设置决定行为"""
        # 如果是强制退出，直接接受
        if getattr(self, '_force_quit', False):
            event.accept()
            return

        if self.settings.close_action == "exit":
            # 直接退出 - 先接受事件，再强制退出
            event.accept()
            self._quit_app()
        else:
            # 最小化到托盘
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "任务调度器",
                "程序已最小化到系统托盘，双击图标可重新打开",
                QSystemTrayIcon.Information,
                2000
            )

