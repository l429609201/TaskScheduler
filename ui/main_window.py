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
        # 如果设置了 kill_previous，先终止上次的实例
        kill_previous = getattr(task, 'kill_previous', False)
        if not kill_previous and task.id in self._running_tasks:
            return False  # 任务已在运行且不允许终止

        from datetime import datetime
        output_buffer = []
        start_time = datetime.now()
        thread = ExecutionThread(task, kill_previous=kill_previous)
        thread.output_received.connect(lambda text, t: output_buffer.append((text, t)))
        thread.execution_finished.connect(lambda code, dur: self._on_task_finished(task.id, code, dur))
        thread.start()

        self._running_tasks[task.id] = (thread, output_buffer, task, start_time)
        return True

    def _on_task_finished(self, task_id: str, exit_code: int, duration: float):
        """任务完成回调"""
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

    def _update_task_status(self, task: Task, exit_code: int):
        """更新任务状态"""
        from datetime import datetime
        from core.models import TaskStatus

        task.status = TaskStatus.SUCCESS if exit_code == 0 else TaskStatus.FAILED
        task.last_run = datetime.now().isoformat()
        task.last_result = f"Exit code: {exit_code}"
        self._storage.update_task(task)

    def _save_log(self, task: Task, buffer: list, exit_code: int, duration: float, start_time):
        """保存执行日志"""
        from datetime import datetime
        from core.executor import ExecutionResult

        # 从缓冲区提取 stdout 和 stderr
        stdout_lines = []
        stderr_lines = []
        for text, output_type in buffer:
            if output_type == 'stdout':
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

        # 记录日志
        self._task_logger.log_execution(
            task_id=task.id,
            task_name=task.name,
            command=task.command,
            working_dir=task.working_dir,
            result=result,
            parsed_vars=parsed_vars
        )

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
        """停止任务"""
        if task_id in self._running_tasks:
            thread, _, _, _ = self._running_tasks[task_id]
            if thread.isRunning():
                thread.stop()
                return True
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
        self.scheduler = TaskScheduler(self.storage, self.settings_storage)

        # 后台任务管理器 - 共享调度器的日志记录器和存储
        self.bg_task_manager = BackgroundTaskManager()
        self.bg_task_manager.set_logger(self.scheduler.task_logger)
        self.bg_task_manager.set_storage(self.storage)

        # 当前页面索引
        self.current_page = 0  # 0: 任务, 1: Webhook, 2: 解析器

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

        # 定时刷新（间隔稍长，避免频繁刷新导致按钮点击失效）
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._safe_refresh)
        self.refresh_timer.start(10000)  # 10秒刷新一次
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

        service_action = QAction("安装服务", self)
        service_action.triggered.connect(self._install_service)
        self.toolbar.addAction(service_action)

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

        # 状态栏
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
    
    def _set_table_row(self, row: int, task: Task):
        """设置表格行"""
        # 名称
        name_item = QTableWidgetItem(task.name)
        name_item.setData(Qt.UserRole, task.id)
        self.table.setItem(row, 0, name_item)
        
        # 状态 - 汉化显示
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
        
        # Webhooks 数量
        webhook_count = len([w for w in task.webhooks if w.enabled])
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

        # 创建选择菜单
        menu = QMenu(self)
        cmd_action = menu.addAction("📋 命令任务")
        cmd_action.setToolTip("执行批处理命令或脚本")
        sync_action = menu.addAction("🔄 同步任务")
        sync_action.setToolTip("文件/文件夹同步")

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

    def _edit_task(self, task: Task):
        """编辑任务 - 根据任务类型选择对话框"""
        from core.models import TaskType
        from .sync_task_dialog import SyncTaskDialog

        if task.task_type == TaskType.SYNC:
            dialog = SyncTaskDialog(self, task)
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
        """有窗口执行任务（显示实时输出）"""
        from core.models import TaskType

        if task.task_type == TaskType.SYNC:
            # 同步任务：使用同步进度对话框
            self._run_sync_task_with_window(task)
        else:
            # 命令任务：使用原有的执行对话框
            dialog = ExecutionDialog(self, task, task_logger=self.scheduler.task_logger)
            dialog.exec_()
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

        # 比较文件
        sync_items = engine.compare()
        items_to_process = [
            item for item in sync_items
            if item.action.value not in ('equal', 'skip', 'conflict')
        ]

        total_files = len(items_to_process)
        if total_files == 0:
            engine.disconnect()
            MsgBox.information(self, "同步完成", "没有需要同步的文件")
            return

        # 估算总大小
        total_bytes = sum(
            (item.source_file.size if item.source_file else 0) or
            (item.target_file.size if item.target_file else 0)
            for item in items_to_process
        )

        # 创建进度对话框
        progress_dialog = SyncProgressDialog(engine, total_files, total_bytes, self)

        # 创建工作线程 - 保存为对话框属性防止被垃圾回收
        # 传递预先比较好的同步项，避免重复比较
        progress_dialog.sync_worker = SyncWorkerThread(engine, items_to_process, progress_dialog)

        # 连接信号
        def on_progress(msg, current, total, bytes_transferred):
            progress_dialog.update_progress(msg, current, total, bytes_transferred)

        def on_finished(result):
            engine.disconnect()

            # 在对话框中显示详细操作
            for detail in result.details:
                action_name, file_path, success, _ = detail
                progress_dialog.add_result_row(action_name, file_path, success)

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
            if task.webhooks:
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
                self.scheduler.notifier.notify_async(task.webhooks, params)

        progress_dialog.sync_worker.progress_updated.connect(on_progress)
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
        from core.models import TaskType

        if task.task_type == TaskType.SYNC:
            # 同步任务：使用调度器执行
            self.scheduler.run_task_now(task.id)
            self.statusBar().showMessage(f"同步任务 '{task.name}' 已在后台启动")
            self._load_tasks()
            return

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
        # 刷新任务列表以显示状态变化
        if self.current_page == 0:
            QTimer.singleShot(100, self._load_tasks)

    def _on_task_complete(self, task: Task, result):
        """任务完成回调"""
        status = "成功" if result.success else "失败"
        self.statusBar().showMessage(f"任务 '{task.name}' 执行{status}")
        # 刷新任务列表以显示状态变化
        if self.current_page == 0:
            QTimer.singleShot(100, self._load_tasks)

    def _open_settings(self):
        """打开设置对话框"""
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

    def _install_service(self):
        """安装 Windows 服务"""
        from service.installer import ServiceInstaller
        installer = ServiceInstaller()

        if MsgBox.question(self, "安装服务", "是否将任务调度器安装为 Windows 服务？\n安装后程序将在后台运行，不会被轻易关闭。"):
            success, msg = installer.install()
            if success:
                MsgBox.information(self, "成功", msg)
            else:
                MsgBox.warning(self, "失败", msg)

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

