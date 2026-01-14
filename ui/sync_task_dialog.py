# -*- coding: utf-8 -*-
"""
同步任务编辑对话框 - FreeFileSync 风格界面
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QTextEdit, QCheckBox, QPushButton,
    QTabWidget, QWidget, QComboBox, QGroupBox,
    QLabel, QSpinBox, QFileDialog, QFrame, QSplitter,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSizePolicy,
    QProgressBar, QTableWidget, QTableWidgetItem, QAbstractItemView
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QColor, QFont

from core.models import (
    Task, TaskType, TaskStatus, ConnectionType, SyncMode, CompareMethod,
    ConnectionConfig, SyncConfig, SyncFilterRule, WebhookConfig, OutputParser,
    WebhookStorage, ParserStorage
)
from .message_box import MsgBox


class SyncTaskDialog(QDialog):
    """同步任务编辑对话框 - FreeFileSync 风格"""

    def __init__(self, parent=None, task: Task = None):
        super().__init__(parent)
        self.task = task or Task(task_type=TaskType.SYNC)
        self.is_edit = task is not None
        self.preview_items = []  # 预览结果

        # 确保有同步配置
        if not self.task.sync_config:
            self.task.sync_config = SyncConfig()

        # Webhook 和解析器列表
        self.webhooks = list(self.task.webhooks) if self.task.webhooks else []
        self.output_parsers = list(self.task.output_parsers) if self.task.output_parsers else []
        self.webhook_storage = WebhookStorage()

        self._init_ui()
        self._load_task_data()

    def _init_ui(self):
        """初始化界面 - FreeFileSync 风格"""
        self.setWindowTitle("编辑同步任务" if self.is_edit else "添加同步任务")
        self.setMinimumSize(900, 650)
        self.resize(950, 700)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ===== 顶部：任务名称和定时设置 =====
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("任务名称:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入同步任务名称")
        top_layout.addWidget(self.name_edit, 2)

        top_layout.addWidget(QLabel("Cron:"))
        self.cron_edit = QLineEdit()
        self.cron_edit.setPlaceholderText("0 0 * * * *")
        self.cron_edit.setText("0 0 * * * *")
        self.cron_edit.setMaximumWidth(150)
        top_layout.addWidget(self.cron_edit)

        # Cron 配置按钮
        cron_config_btn = QPushButton("⚙")
        cron_config_btn.setFixedWidth(30)
        cron_config_btn.setToolTip("配置定时规则")
        cron_config_btn.clicked.connect(self._show_cron_config)
        top_layout.addWidget(cron_config_btn)

        self.enabled_check = QCheckBox("启用")
        self.enabled_check.setChecked(True)
        top_layout.addWidget(self.enabled_check)

        layout.addLayout(top_layout)

        # ===== 中间：左右两栏 + 中间操作按钮 =====
        main_layout = QHBoxLayout()

        # 左侧：源端
        left_group = QGroupBox("📁 源端 (Source)")
        left_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        left_layout = QVBoxLayout(left_group)
        self._create_side_panel(left_layout, "source")
        main_layout.addWidget(left_group, 1)

        # 中间：操作按钮
        center_widget = QWidget()
        center_widget.setFixedWidth(100)
        center_layout = QVBoxLayout(center_widget)
        center_layout.setAlignment(Qt.AlignCenter)

        # 同步模式选择
        self.sync_mode_combo = QComboBox()
        self.sync_mode_combo.addItem("⟹ 镜像", SyncMode.MIRROR.value)
        self.sync_mode_combo.addItem("→ 更新", SyncMode.UPDATE.value)
        self.sync_mode_combo.addItem("⟺ 双向", SyncMode.TWO_WAY.value)
        self.sync_mode_combo.addItem("⊕ 备份", SyncMode.BACKUP.value)
        self.sync_mode_combo.setToolTip("选择同步模式")
        center_layout.addWidget(self.sync_mode_combo)

        center_layout.addSpacing(10)

        # 比较按钮
        self.compare_btn = QPushButton("🔍 比较")
        self.compare_btn.setMinimumHeight(40)
        self.compare_btn.setToolTip("比较源端和目标端的差异")
        self.compare_btn.clicked.connect(self._do_compare)
        self.compare_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        center_layout.addWidget(self.compare_btn)

        center_layout.addSpacing(5)

        # 同步按钮（预览后启用）
        self.sync_btn = QPushButton("▶ 同步")
        self.sync_btn.setMinimumHeight(40)
        self.sync_btn.setToolTip("执行同步操作")
        self.sync_btn.setEnabled(False)
        self.sync_btn.clicked.connect(self._do_sync)
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        center_layout.addWidget(self.sync_btn)

        center_layout.addStretch()

        # 比较方式
        center_layout.addWidget(QLabel("比较方式:"))
        self.compare_combo = QComboBox()
        self.compare_combo.addItem("时间+大小", CompareMethod.TIME_SIZE.value)
        self.compare_combo.addItem("仅时间", CompareMethod.TIME.value)
        self.compare_combo.addItem("仅大小", CompareMethod.SIZE.value)
        self.compare_combo.addItem("MD5", CompareMethod.HASH.value)
        center_layout.addWidget(self.compare_combo)

        # 同步线程数
        center_layout.addWidget(QLabel("同步线程:"))
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 16)
        self.thread_spin.setValue(4)
        self.thread_spin.setToolTip("并发同步线程数 (1-16)")
        center_layout.addWidget(self.thread_spin)

        main_layout.addWidget(center_widget)

        # 右侧：目标端
        right_group = QGroupBox("📁 目标端 (Target)")
        right_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        right_layout = QVBoxLayout(right_group)
        self._create_side_panel(right_layout, "target")
        main_layout.addWidget(right_group, 1)

        layout.addLayout(main_layout)

        # ===== 底部：过滤规则 + 预览结果 =====
        bottom_tabs = QTabWidget()

        # 过滤规则选项卡 - FreeFileSync 风格
        filter_tab = QWidget()
        filter_main_layout = QHBoxLayout(filter_tab)

        # 左侧：包含规则列表
        include_group = QGroupBox("✅ 包含 (Include)")
        include_group.setStyleSheet("QGroupBox { font-weight: bold; color: #2e7d32; padding-top: 15px; }")
        include_group.setMinimumHeight(120)
        include_layout = QVBoxLayout(include_group)

        self.include_list = QTextEdit()
        self.include_list.setPlaceholderText("每行一个规则，例如：\n*\n*.txt\n*.doc\n\\重要文件夹\\")
        self.include_list.setStyleSheet("QTextEdit { font-family: Consolas, monospace; }")
        self.include_list.setText("*")  # 默认包含所有
        include_layout.addWidget(self.include_list)

        include_hint = QLabel("提示: * 匹配所有, ? 匹配单字符, \\ 开头表示根目录")
        include_hint.setStyleSheet("color: #666; font-size: 11px;")
        include_layout.addWidget(include_hint)

        filter_main_layout.addWidget(include_group)

        # 右侧：排除规则列表
        exclude_group = QGroupBox("❌ 排除 (Exclude)")
        exclude_group.setStyleSheet("QGroupBox { font-weight: bold; color: #c62828; padding-top: 15px; }")
        exclude_group.setMinimumHeight(120)
        exclude_layout = QVBoxLayout(exclude_group)

        self.exclude_list = QTextEdit()
        self.exclude_list.setPlaceholderText("每行一个规则，例如：\n*.tmp\n*.bak\n~*\n\\.git\\\n\\node_modules\\")
        self.exclude_list.setStyleSheet("QTextEdit { font-family: Consolas, monospace; }")
        # 默认排除规则
        self.exclude_list.setText("*.tmp\n*.bak\n~*\n\\.git\\\n\\__pycache__\\\n\\node_modules\\")
        exclude_layout.addWidget(self.exclude_list)

        exclude_hint = QLabel("提示: 文件夹以 \\ 结尾, *\\name 匹配任意位置")
        exclude_hint.setStyleSheet("color: #666; font-size: 11px;")
        exclude_layout.addWidget(exclude_hint)

        filter_main_layout.addWidget(exclude_group)

        # 最右侧：其他选项
        options_widget = QWidget()
        options_widget.setFixedWidth(200)
        options_layout = QVBoxLayout(options_widget)

        # 时间过滤
        time_group = QGroupBox("⏰ 时间过滤")
        time_group.setStyleSheet("QGroupBox { padding-top: 15px; }")
        time_layout = QVBoxLayout(time_group)

        self.time_filter_combo = QComboBox()
        self.time_filter_combo.addItem("不限制", "none")
        self.time_filter_combo.addItem("今天", "today")
        self.time_filter_combo.addItem("昨天", "yesterday")
        self.time_filter_combo.addItem("最近3天", "days_3")
        self.time_filter_combo.addItem("最近7天", "days_7")
        self.time_filter_combo.addItem("最近30天", "days_30")
        self.time_filter_combo.addItem("自定义...", "custom")
        self.time_filter_combo.currentIndexChanged.connect(self._on_time_filter_changed)
        time_layout.addWidget(self.time_filter_combo)

        # 自定义时间范围
        from PyQt5.QtWidgets import QDateTimeEdit
        from PyQt5.QtCore import QDateTime

        self.time_start_edit = QDateTimeEdit()
        self.time_start_edit.setCalendarPopup(True)
        self.time_start_edit.setDateTime(QDateTime.currentDateTime().addDays(-7))
        self.time_start_edit.setDisplayFormat("MM-dd HH:mm")
        self.time_start_edit.setVisible(False)
        time_layout.addWidget(self.time_start_edit)

        self.time_end_edit = QDateTimeEdit()
        self.time_end_edit.setCalendarPopup(True)
        self.time_end_edit.setDateTime(QDateTime.currentDateTime())
        self.time_end_edit.setDisplayFormat("MM-dd HH:mm")
        self.time_end_edit.setVisible(False)
        time_layout.addWidget(self.time_end_edit)

        options_layout.addWidget(time_group)

        # 其他选项
        other_group = QGroupBox("🔧 其他选项")
        other_group.setStyleSheet("QGroupBox { padding-top: 15px; }")
        other_layout = QVBoxLayout(other_group)

        self.include_hidden_check = QCheckBox("包含隐藏文件")
        other_layout.addWidget(self.include_hidden_check)

        self.delete_extra_check = QCheckBox("删除多余文件")
        other_layout.addWidget(self.delete_extra_check)

        options_layout.addWidget(other_group)
        options_layout.addStretch()

        filter_main_layout.addWidget(options_widget)

        # 兼容性：保留旧字段（隐藏）
        self.include_patterns_edit = QLineEdit()
        self.include_patterns_edit.setVisible(False)
        self.exclude_patterns_edit = QLineEdit()
        self.exclude_patterns_edit.setVisible(False)
        self.exclude_dirs_edit = QLineEdit()
        self.exclude_dirs_edit.setVisible(False)
        self.time_range_widget = QWidget()
        self.time_range_widget.setVisible(False)

        bottom_tabs.addTab(filter_tab, "🔧 过滤规则")

        # 预览结果选项卡
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)

        # 统计信息
        self.stats_label = QLabel("点击「比较」按钮查看差异")
        self.stats_label.setStyleSheet("color: #666; font-style: italic;")
        preview_layout.addWidget(self.stats_label)

        # 预览表格
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(4)
        self.preview_table.setHorizontalHeaderLabels(["操作", "文件路径", "源端", "目标端"])
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setAlternatingRowColors(True)
        preview_layout.addWidget(self.preview_table)

        bottom_tabs.addTab(preview_tab, "📋 预览结果 (0)")
        self.preview_tab_index = 1

        # Webhook 选项卡
        webhook_tab = QWidget()
        webhook_layout = QVBoxLayout(webhook_tab)

        hint_label = QLabel("从全局配置中选择要使用的 Webhook，或为此任务单独添加")
        hint_label.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 5px;")
        webhook_layout.addWidget(hint_label)

        # 从全局配置选择
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("从全局配置添加:"))

        self.global_webhook_combo = QComboBox()
        self._refresh_global_webhooks()
        select_layout.addWidget(self.global_webhook_combo, 1)

        add_from_global_btn = QPushButton("添加选中")
        add_from_global_btn.clicked.connect(self._add_from_global)
        select_layout.addWidget(add_from_global_btn)

        webhook_layout.addLayout(select_layout)

        # Webhook 表格
        self.webhook_table = QTableWidget()
        self.webhook_table.setColumnCount(4)
        self.webhook_table.setHorizontalHeaderLabels(["名称", "URL", "方法", "启用"])
        self.webhook_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.webhook_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        webhook_layout.addWidget(self.webhook_table)

        # Webhook 按钮
        webhook_btn_layout = QHBoxLayout()
        add_webhook_btn = QPushButton("手动添加")
        add_webhook_btn.clicked.connect(self._add_webhook)
        webhook_btn_layout.addWidget(add_webhook_btn)

        edit_webhook_btn = QPushButton("编辑")
        edit_webhook_btn.clicked.connect(self._edit_webhook)
        webhook_btn_layout.addWidget(edit_webhook_btn)

        del_webhook_btn = QPushButton("移除")
        del_webhook_btn.clicked.connect(self._delete_webhook)
        webhook_btn_layout.addWidget(del_webhook_btn)

        webhook_btn_layout.addStretch()
        webhook_layout.addLayout(webhook_btn_layout)

        bottom_tabs.addTab(webhook_tab, f"🔔 Webhooks ({len(self.webhooks)})")
        self.webhook_tab_index = 2

        # 输出解析选项卡
        parser_tab = QWidget()
        parser_layout = QVBoxLayout(parser_tab)

        parser_hint = QLabel("配置输出解析规则，提取的变量可在 Webhook 模板中使用")
        parser_hint.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 5px;")
        parser_layout.addWidget(parser_hint)

        # 解析器表格
        self.parser_table = QTableWidget()
        self.parser_table.setColumnCount(4)
        self.parser_table.setHorizontalHeaderLabels(["变量名", "类型", "表达式", "启用"])
        self.parser_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.parser_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        parser_layout.addWidget(self.parser_table)

        # 解析器按钮
        parser_btn_layout = QHBoxLayout()
        import_parser_btn = QPushButton("从全局模板导入")
        import_parser_btn.clicked.connect(self._import_parsers)
        parser_btn_layout.addWidget(import_parser_btn)

        add_parser_btn = QPushButton("手动添加")
        add_parser_btn.clicked.connect(self._add_parser)
        parser_btn_layout.addWidget(add_parser_btn)

        edit_parser_btn = QPushButton("编辑")
        edit_parser_btn.clicked.connect(self._edit_parser)
        parser_btn_layout.addWidget(edit_parser_btn)

        del_parser_btn = QPushButton("移除")
        del_parser_btn.clicked.connect(self._delete_parser)
        parser_btn_layout.addWidget(del_parser_btn)

        parser_btn_layout.addStretch()
        parser_layout.addLayout(parser_btn_layout)

        bottom_tabs.addTab(parser_tab, f"📊 输出解析 ({len(self.output_parsers)})")
        self.parser_tab_index = 3

        self.bottom_tabs = bottom_tabs
        layout.addWidget(bottom_tabs)

        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()

        self.continue_on_error_check = QCheckBox("出错继续")
        self.continue_on_error_check.setChecked(True)
        btn_layout.addWidget(self.continue_on_error_check)

        btn_layout.addStretch()

        save_btn = QPushButton("💾 保存任务")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # 隐藏的描述字段（保持兼容性）
        self.desc_edit = QLineEdit()
        self.desc_edit.setVisible(False)

    def _create_side_panel(self, layout: QVBoxLayout, prefix: str):
        """创建左/右侧面板 - FreeFileSync 风格"""
        # 连接类型选择行
        type_layout = QHBoxLayout()

        type_combo = QComboBox()
        type_combo.addItem("📁 本地", ConnectionType.LOCAL.value)
        type_combo.addItem("🌐 FTP", ConnectionType.FTP.value)
        type_combo.addItem("🔒 SFTP", ConnectionType.SFTP.value)
        type_combo.currentIndexChanged.connect(lambda: self._on_type_changed(prefix))
        setattr(self, f"{prefix}_type_combo", type_combo)
        type_layout.addWidget(type_combo)

        # 配置按钮（齿轮图标）- 用于FTP/SFTP配置
        config_btn = QPushButton("⚙")
        config_btn.setFixedWidth(30)
        config_btn.setToolTip("配置连接参数")
        config_btn.clicked.connect(lambda: self._show_connection_config(prefix))
        config_btn.setVisible(False)
        setattr(self, f"{prefix}_config_btn", config_btn)
        type_layout.addWidget(config_btn)

        # 连接状态指示
        status_label = QLabel("●")
        status_label.setFixedWidth(20)
        status_label.setStyleSheet("color: gray;")
        status_label.setToolTip("未连接")
        setattr(self, f"{prefix}_status_label", status_label)
        type_layout.addWidget(status_label)

        type_layout.addStretch()
        layout.addLayout(type_layout)

        # 路径输入行 - FreeFileSync 风格
        path_layout = QHBoxLayout()
        path_layout.setSpacing(2)

        # 返回上级按钮
        up_btn = QPushButton("⬆")
        up_btn.setFixedWidth(28)
        up_btn.setToolTip("返回上级目录")
        up_btn.clicked.connect(lambda: self._go_up_directory(prefix))
        setattr(self, f"{prefix}_up_btn", up_btn)
        path_layout.addWidget(up_btn)

        # 路径输入框
        path_edit = QLineEdit()
        path_edit.setPlaceholderText("输入路径或浏览选择...")
        path_edit.returnPressed.connect(lambda: self._load_path(prefix))
        setattr(self, f"{prefix}_path_edit", path_edit)
        path_layout.addWidget(path_edit)

        # 浏览按钮
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(28)
        browse_btn.setToolTip("浏览文件夹")
        browse_btn.clicked.connect(lambda: self._browse_path(prefix))
        setattr(self, f"{prefix}_browse_btn", browse_btn)
        path_layout.addWidget(browse_btn)

        # 刷新按钮
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("刷新")
        refresh_btn.clicked.connect(lambda: self._load_path(prefix))
        setattr(self, f"{prefix}_refresh_btn", refresh_btn)
        path_layout.addWidget(refresh_btn)

        layout.addLayout(path_layout)

        # 隐藏的远程配置字段（存储配置数据）
        host_edit = QLineEdit()
        setattr(self, f"{prefix}_host_edit", host_edit)
        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(21)
        setattr(self, f"{prefix}_port_spin", port_spin)
        user_edit = QLineEdit()
        setattr(self, f"{prefix}_user_edit", user_edit)
        pass_edit = QLineEdit()
        pass_edit.setEchoMode(QLineEdit.Password)
        setattr(self, f"{prefix}_pass_edit", pass_edit)

        # 兼容性：保留 remote_widget
        remote_widget = QWidget()
        remote_widget.setVisible(False)
        setattr(self, f"{prefix}_remote_widget", remote_widget)

        # 文件树 - FreeFileSync 风格
        tree = QTreeWidget()
        tree.setHeaderLabels(["名称", "大小", "修改时间"])
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(False)  # 不显示展开箭头
        tree.setMinimumHeight(200)
        tree.setSortingEnabled(True)  # 启用排序
        tree.sortByColumn(0, Qt.AscendingOrder)  # 默认按名称升序
        tree.itemDoubleClicked.connect(lambda item: self._on_tree_double_click(prefix, item))
        setattr(self, f"{prefix}_tree", tree)
        layout.addWidget(tree)

        # 初始化显示状态
        self._on_type_changed(prefix)

    def _on_type_changed(self, prefix: str):
        """连接类型改变时更新界面"""
        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()

        is_local = conn_type == ConnectionType.LOCAL.value

        # 显示/隐藏配置按钮
        config_btn = getattr(self, f"{prefix}_config_btn", None)
        if config_btn:
            config_btn.setVisible(not is_local)

        # 重置连接状态
        status_label = getattr(self, f"{prefix}_status_label", None)
        if status_label:
            status_label.setStyleSheet("color: gray;")
            status_label.setToolTip("未连接")

        # 更新端口默认值
        if conn_type == ConnectionType.FTP.value:
            getattr(self, f"{prefix}_port_spin").setValue(21)
        elif conn_type == ConnectionType.SFTP.value:
            getattr(self, f"{prefix}_port_spin").setValue(22)

        # 清空文件树
        tree = getattr(self, f"{prefix}_tree", None)
        if tree:
            tree.clear()

    def _show_connection_config(self, prefix: str):
        """显示连接配置对话框"""
        from PyQt5.QtWidgets import QDialog, QDialogButtonBox

        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()

        dialog = QDialog(self)
        dialog.setWindowTitle("FTP 配置" if conn_type == ConnectionType.FTP.value else "SFTP 配置")
        dialog.setMinimumWidth(350)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        # 主机
        host_edit = QLineEdit()
        host_edit.setText(getattr(self, f"{prefix}_host_edit").text())
        host_edit.setPlaceholderText("例如: ftp.example.com")
        form.addRow("主机地址:", host_edit)

        # 端口
        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(getattr(self, f"{prefix}_port_spin").value())
        form.addRow("端口:", port_spin)

        # 用户名
        user_edit = QLineEdit()
        user_edit.setText(getattr(self, f"{prefix}_user_edit").text())
        user_edit.setPlaceholderText("用户名")
        form.addRow("用户名:", user_edit)

        # 密码
        pass_edit = QLineEdit()
        pass_edit.setEchoMode(QLineEdit.Password)
        pass_edit.setText(getattr(self, f"{prefix}_pass_edit").text())
        pass_edit.setPlaceholderText("密码")
        form.addRow("密码:", pass_edit)

        layout.addLayout(form)

        # 测试连接按钮
        test_btn = QPushButton("🔗 测试连接")
        test_btn.clicked.connect(lambda: self._test_connection(
            prefix, conn_type, host_edit.text(), port_spin.value(),
            user_edit.text(), pass_edit.text(), dialog
        ))
        layout.addWidget(test_btn)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec_() == QDialog.Accepted:
            # 保存配置
            getattr(self, f"{prefix}_host_edit").setText(host_edit.text())
            getattr(self, f"{prefix}_port_spin").setValue(port_spin.value())
            getattr(self, f"{prefix}_user_edit").setText(user_edit.text())
            getattr(self, f"{prefix}_pass_edit").setText(pass_edit.text())

    def _test_connection(self, prefix: str, conn_type, host: str, port: int,
                         username: str, password: str, parent_dialog):
        """测试FTP/SFTP连接"""
        if not host:
            MsgBox.warning(parent_dialog, "提示", "请输入主机地址")
            return

        # 调试信息
        print(f"测试连接: conn_type={conn_type}, host={host}, port={port}, user={username}")
        print(f"FTP.value={ConnectionType.FTP.value}, SFTP.value={ConnectionType.SFTP.value}")

        # 直接测试连接，不通过 sync_engine
        try:
            if conn_type == ConnectionType.FTP.value or conn_type == "ftp":
                # 测试 FTP
                print("正在测试 FTP 连接...")
                from ftplib import FTP
                ftp = FTP()
                ftp.connect(host, port, timeout=10)
                ftp.login(username or "anonymous", password or "")
                ftp.set_pasv(True)
                welcome = ftp.getwelcome()
                ftp.quit()
                MsgBox.information(parent_dialog, "成功", f"FTP 连接成功！")

            elif conn_type == ConnectionType.SFTP.value or conn_type == "sftp":
                # 测试 SFTP
                print("正在测试 SFTP 连接...")
                try:
                    import paramiko
                except ImportError:
                    MsgBox.warning(parent_dialog, "错误", "SFTP 需要安装 paramiko 库\n请运行: pip install paramiko")
                    return

                transport = paramiko.Transport((host, port))
                transport.connect(username=username, password=password)
                sftp = paramiko.SFTPClient.from_transport(transport)
                # 尝试列出根目录验证连接
                sftp.listdir("/")
                sftp.close()
                transport.close()
                MsgBox.information(parent_dialog, "成功", "SFTP 连接成功！")
            else:
                MsgBox.warning(parent_dialog, "错误", f"未知的连接类型: {conn_type}")
                return

            # 更新状态指示
            status_label = getattr(self, f"{prefix}_status_label", None)
            if status_label:
                status_label.setStyleSheet("color: #4CAF50;")
                status_label.setToolTip("已连接")

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"连接错误详情:\n{error_detail}")
            MsgBox.warning(parent_dialog, "连接失败", f"错误: {type(e).__name__}\n{str(e)}")

    def _browse_path(self, prefix: str):
        """浏览选择路径（本地或远程）"""
        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()

        if conn_type == ConnectionType.LOCAL.value:
            # 本地文件夹选择
            current_path = getattr(self, f"{prefix}_path_edit").text()
            path = QFileDialog.getExistingDirectory(self, "选择文件夹", current_path)
            if path:
                getattr(self, f"{prefix}_path_edit").setText(path)
                self._load_path(prefix)
        else:
            # 远程：检查是否已配置
            host = getattr(self, f"{prefix}_host_edit").text()
            if not host:
                MsgBox.warning(self, "提示", "请先点击⚙配置连接参数")
                return
            self._show_remote_browser(prefix)

    def _go_up_directory(self, prefix: str):
        """返回上级目录"""
        import os
        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()
        path_edit = getattr(self, f"{prefix}_path_edit")
        current_path = path_edit.text()

        if not current_path:
            return

        if conn_type == ConnectionType.LOCAL.value:
            # 本地路径
            parent = os.path.dirname(current_path.rstrip(os.sep))
            if parent and parent != current_path:
                path_edit.setText(parent)
                self._load_path(prefix)
        else:
            # 远程路径
            if current_path != "/":
                parent = "/".join(current_path.rstrip("/").split("/")[:-1]) or "/"
                path_edit.setText(parent)
                self._load_path(prefix)

    def _load_path(self, prefix: str):
        """加载指定路径的内容到文件树"""
        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()
        path = getattr(self, f"{prefix}_path_edit").text()

        if not path:
            return

        if conn_type == ConnectionType.LOCAL.value:
            self._scan_local_folder(path, prefix)
        else:
            # 远程路径加载
            host = getattr(self, f"{prefix}_host_edit").text()
            if not host:
                MsgBox.warning(self, "提示", "请先点击⚙配置连接参数")
                return
            self._load_remote_path(prefix, path)

    def _show_remote_browser(self, prefix: str):
        """显示远程文件浏览对话框 - FreeFileSync 风格树形结构"""
        from PyQt5.QtWidgets import QDialog
        from PyQt5.QtGui import QIcon
        from PyQt5.QtCore import Qt

        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()

        host = getattr(self, f"{prefix}_host_edit").text()
        if not host:
            MsgBox.warning(self, "提示", "请先点击⚙配置连接参数")
            return

        port = getattr(self, f"{prefix}_port_spin").value()
        username = getattr(self, f"{prefix}_user_edit").text()
        password = getattr(self, f"{prefix}_pass_edit").text()

        dialog = QDialog(self)
        dialog.setWindowTitle("选择一个文件夹")
        dialog.setMinimumSize(400, 500)

        layout = QVBoxLayout(dialog)

        # 文件夹树 - FreeFileSync 风格
        folder_tree = QTreeWidget()
        folder_tree.setHeaderHidden(True)  # 隐藏表头
        folder_tree.setRootIsDecorated(True)  # 显示展开箭头
        folder_tree.setAnimated(True)
        layout.addWidget(folder_tree)

        # 状态标签
        status_label = QLabel("正在连接...")
        layout.addWidget(status_label)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        select_btn = QPushButton("选择文件夹")
        select_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(select_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # 存储连接对象（避免重复连接）
        connection = {'ftp': None, 'sftp': None, 'transport': None}

        def connect_remote():
            """建立远程连接"""
            try:
                if conn_type == ConnectionType.FTP.value or conn_type == "ftp":
                    from ftplib import FTP
                    ftp = FTP()
                    ftp.encoding = 'gbk'
                    ftp.connect(host, port, timeout=10)
                    ftp.login(username or "anonymous", password or "")
                    ftp.set_pasv(True)
                    connection['ftp'] = ftp
                    return True
                elif conn_type == ConnectionType.SFTP.value or conn_type == "sftp":
                    import paramiko
                    transport = paramiko.Transport((host, port))
                    transport.connect(username=username, password=password)
                    sftp = paramiko.SFTPClient.from_transport(transport)
                    connection['sftp'] = sftp
                    connection['transport'] = transport
                    return True
            except Exception as e:
                status_label.setText(f"连接失败: {str(e)}")
                return False
            return False

        def disconnect_remote():
            """断开远程连接"""
            if connection['ftp']:
                try:
                    connection['ftp'].quit()
                except:
                    pass
            if connection['sftp']:
                try:
                    connection['sftp'].close()
                except:
                    pass
            if connection['transport']:
                try:
                    connection['transport'].close()
                except:
                    pass

        def list_remote_dirs(path: str):
            """列出远程目录下的子文件夹"""
            dirs = []
            try:
                if connection['ftp']:
                    ftp = connection['ftp']
                    try:
                        ftp.cwd(path)
                    except:
                        ftp.encoding = 'utf-8'
                        ftp.cwd(path)

                    # 尝试 MLSD
                    try:
                        items = []
                        ftp.retrlines('MLSD', lambda x: items.append(x))
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
                            if facts.get('type', '').lower() == 'dir':
                                dirs.append(name)
                    except:
                        # LIST 回退
                        lines = []
                        ftp.retrlines('LIST', lambda x: lines.append(x))
                        for line in lines:
                            if line.startswith('d'):
                                parts = line.split()
                                if len(parts) >= 9:
                                    name = ' '.join(parts[8:])
                                    if name not in ['.', '..']:
                                        dirs.append(name)

                elif connection['sftp']:
                    sftp = connection['sftp']
                    for attr in sftp.listdir_attr(path):
                        if attr.filename in ['.', '..']:
                            continue
                        if attr.st_mode is not None and (attr.st_mode & 0o40000) != 0:
                            dirs.append(attr.filename)
            except Exception as e:
                print(f"列出目录错误 {path}: {e}")

            return sorted(dirs)

        def load_children(parent_item, path: str):
            """加载子文件夹"""
            dirs = list_remote_dirs(path)
            for dir_name in dirs:
                child = QTreeWidgetItem(parent_item)
                child.setText(0, dir_name)
                child.setIcon(0, folder_tree.style().standardIcon(folder_tree.style().SP_DirIcon))
                child.setData(0, Qt.UserRole, path.rstrip("/") + "/" + dir_name)
                # 添加占位符，使其可展开
                placeholder = QTreeWidgetItem(child)
                placeholder.setText(0, "加载中...")

        def on_item_expanded(item):
            """展开节点时加载子目录"""
            # 检查是否有占位符
            if item.childCount() == 1 and item.child(0).text(0) == "加载中...":
                # 移除占位符
                item.removeChild(item.child(0))
                # 加载真实子目录
                path = item.data(0, Qt.UserRole)
                load_children(item, path)
                status_label.setText(f"已加载: {path}")

        folder_tree.itemExpanded.connect(on_item_expanded)

        # 建立连接并加载根目录
        if connect_remote():
            status_label.setText("已连接，正在加载...")

            # 创建根节点
            root_item = QTreeWidgetItem(folder_tree)
            root_item.setText(0, "\\")
            root_item.setIcon(0, folder_tree.style().standardIcon(folder_tree.style().SP_DriveNetIcon))
            root_item.setData(0, Qt.UserRole, "/")

            # 加载根目录下的文件夹
            load_children(root_item, "/")
            root_item.setExpanded(True)

            status_label.setText("就绪")

        # 执行对话框
        result = dialog.exec_()

        # 获取选中的路径
        selected_path = "/"
        if result == QDialog.Accepted:
            selected = folder_tree.currentItem()
            if selected:
                selected_path = selected.data(0, Qt.UserRole) or "/"

        # 断开连接
        disconnect_remote()

        if result == QDialog.Accepted:
            getattr(self, f"{prefix}_path_edit").setText(selected_path)
            # 加载选中的路径到主界面文件树
            self._load_path(prefix)

    def _load_remote_path(self, prefix: str, path: str):
        """加载远程路径到文件树（直接在主界面显示）"""
        from PyQt5.QtCore import Qt

        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()
        tree = getattr(self, f"{prefix}_tree")
        tree.clear()

        host = getattr(self, f"{prefix}_host_edit").text()
        port = getattr(self, f"{prefix}_port_spin").value()
        username = getattr(self, f"{prefix}_user_edit").text()
        password = getattr(self, f"{prefix}_pass_edit").text()

        # 获取时间过滤范围
        time_range = self._get_time_filter_range()

        try:
            if conn_type == ConnectionType.FTP.value or conn_type == "ftp":
                from ftplib import FTP
                from datetime import datetime

                ftp = FTP()
                ftp.encoding = 'gbk'
                ftp.connect(host, port, timeout=10)
                ftp.login(username or "anonymous", password or "")
                ftp.set_pasv(True)

                try:
                    ftp.cwd(path)
                except:
                    ftp.encoding = 'utf-8'
                    ftp.cwd(path)

                # 尝试 MLSD
                try:
                    items = []
                    ftp.retrlines('MLSD', lambda x: items.append(x))

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

                        is_dir = facts.get('type', '').lower() == 'dir'
                        size_str = facts.get('size', '')
                        modify = facts.get('modify', '')

                        # 解析修改时间
                        mtime = 0
                        if modify:
                            try:
                                dt = datetime.strptime(modify[:14], "%Y%m%d%H%M%S")
                                mtime = dt.timestamp()
                            except:
                                pass

                        # 应用时间过滤（仅对文件）
                        if not is_dir and time_range and mtime > 0:
                            start_ts, end_ts = time_range
                            if mtime < start_ts or mtime > end_ts:
                                continue

                        tree_item = QTreeWidgetItem()
                        tree_item.setText(0, ("📁 " if is_dir else "📄 ") + name)
                        tree_item.setData(0, Qt.UserRole, (0 if is_dir else 1, name.lower()))

                        size_val = int(size_str) if size_str else 0
                        if size_str and not is_dir:
                            tree_item.setText(1, self._format_size(size_val))
                        tree_item.setData(1, Qt.UserRole, -1 if is_dir else size_val)

                        if mtime > 0:
                            tree_item.setText(2, datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"))
                        tree_item.setData(2, Qt.UserRole, mtime)

                        tree.addTopLevelItem(tree_item)
                except:
                    # LIST 回退
                    lines = []
                    ftp.retrlines('LIST', lambda x: lines.append(x))

                    for line in lines:
                        parts = line.split()
                        if len(parts) < 9:
                            continue
                        name = ' '.join(parts[8:])
                        if name in ['.', '..']:
                            continue
                        is_dir = line.startswith('d')
                        size_str = parts[4] if len(parts) > 4 else ""

                        tree_item = QTreeWidgetItem()
                        tree_item.setText(0, ("📁 " if is_dir else "📄 ") + name)
                        tree_item.setData(0, Qt.UserRole, (0 if is_dir else 1, name.lower()))

                        size_val = int(size_str) if size_str else 0
                        if size_str and not is_dir:
                            tree_item.setText(1, self._format_size(size_val))
                        tree_item.setData(1, Qt.UserRole, -1 if is_dir else size_val)
                        tree_item.setData(2, Qt.UserRole, 0)

                        tree.addTopLevelItem(tree_item)

                ftp.quit()

            elif conn_type == ConnectionType.SFTP.value or conn_type == "sftp":
                import paramiko
                from datetime import datetime

                transport = paramiko.Transport((host, port))
                transport.connect(username=username, password=password)
                sftp = paramiko.SFTPClient.from_transport(transport)

                for attr in sftp.listdir_attr(path):
                    if attr.filename in ['.', '..']:
                        continue

                    is_dir = attr.st_mode is not None and (attr.st_mode & 0o40000) != 0
                    mtime = attr.st_mtime or 0

                    # 应用时间过滤（仅对文件）
                    if not is_dir and time_range and mtime > 0:
                        start_ts, end_ts = time_range
                        if mtime < start_ts or mtime > end_ts:
                            continue

                    tree_item = QTreeWidgetItem()
                    tree_item.setText(0, ("📁 " if is_dir else "📄 ") + attr.filename)
                    tree_item.setData(0, Qt.UserRole, (0 if is_dir else 1, attr.filename.lower()))

                    if not is_dir:
                        tree_item.setText(1, self._format_size(attr.st_size))
                    tree_item.setData(1, Qt.UserRole, -1 if is_dir else attr.st_size)

                    if mtime:
                        tree_item.setText(2, datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"))
                    tree_item.setData(2, Qt.UserRole, mtime)

                    tree.addTopLevelItem(tree_item)

                sftp.close()
                transport.close()

        except Exception as e:
            import traceback
            print(f"加载远程路径错误:\n{traceback.format_exc()}")
            error_item = QTreeWidgetItem([f"加载失败: {str(e)}", "", ""])
            tree.addTopLevelItem(error_item)

    def _load_remote_dir(self, connector, path: str, tree: QTreeWidget):
        """加载远程目录到树"""
        tree.clear()

        # 添加返回上级
        if path != "/":
            up_item = QTreeWidgetItem(["..", "", "返回上级"])
            tree.addTopLevelItem(up_item)

        try:
            # 使用连接器的底层方法列出目录
            if hasattr(connector, 'ftp'):
                # FTP
                items = []
                connector.ftp.cwd(path)
                connector.ftp.retrlines('MLSD', lambda x: items.append(x))

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

                    is_dir = facts.get('type', '').lower() == 'dir'
                    size = facts.get('size', '')

                    tree_item = QTreeWidgetItem([
                        name,
                        self._format_size(int(size)) if size and not is_dir else "",
                        "文件夹" if is_dir else "文件"
                    ])
                    tree.addTopLevelItem(tree_item)

            elif hasattr(connector, 'sftp'):
                # SFTP
                for attr in connector.sftp.listdir_attr(path):
                    if attr.filename in ['.', '..']:
                        continue

                    is_dir = attr.st_mode is not None and (attr.st_mode & 0o40000) != 0

                    tree_item = QTreeWidgetItem([
                        attr.filename,
                        self._format_size(attr.st_size) if not is_dir else "",
                        "文件夹" if is_dir else "文件"
                    ])
                    tree.addTopLevelItem(tree_item)
        except Exception as e:
            error_item = QTreeWidgetItem([f"加载失败: {str(e)}", "", ""])
            tree.addTopLevelItem(error_item)

    def _on_tree_double_click(self, prefix: str, item):
        """双击文件树项目 - 进入子目录"""
        import os
        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = type_combo.currentData()
        path_edit = getattr(self, f"{prefix}_path_edit")
        current_path = path_edit.text()

        # 获取文件名（去掉图标）
        name = item.text(0).replace("📁 ", "").replace("📄 ", "")

        # 检查是否是文件夹
        if not item.text(0).startswith("📁"):
            return  # 不是文件夹，不处理

        if conn_type == ConnectionType.LOCAL.value:
            # 本地路径
            if current_path:
                new_path = os.path.join(current_path, name)
                if os.path.isdir(new_path):
                    path_edit.setText(new_path)
                    self._load_path(prefix)
        else:
            # 远程路径
            if current_path:
                new_path = current_path.rstrip("/") + "/" + name
                path_edit.setText(new_path)
                self._load_path(prefix)

    def _do_compare(self):
        """执行比较操作 - 预览同步差异"""
        import os
        from datetime import datetime

        source_config = self._get_connection_config("source")
        target_config = self._get_connection_config("target")

        # 验证配置
        if not source_config.path:
            MsgBox.warning(self, "提示", "请先配置源端路径")
            return
        if not target_config.path:
            MsgBox.warning(self, "提示", "请先配置目标端路径")
            return

        # 清空预览表格
        self.preview_table.setRowCount(0)
        self.preview_items = []

        # 获取比较方式
        compare_method = self.compare_combo.currentData()

        # 获取时间过滤范围
        time_range = self._get_time_filter_range()

        # 扫描源端和目标端文件
        source_files = {}  # {relative_path: (size, mtime)}
        target_files = {}  # {relative_path: (size, mtime)}

        # 扫描源端
        source_files, source_error = self._scan_endpoint_for_compare(source_config, time_range)
        if source_error:
            MsgBox.warning(self, "源端扫描失败", source_error)
            return

        # 扫描目标端
        target_files, target_error = self._scan_endpoint_for_compare(target_config, time_range)
        if target_error:
            MsgBox.warning(self, "目标端扫描失败", target_error)
            return

        # 刷新文件树显示
        if source_config.type == ConnectionType.LOCAL and os.path.isdir(source_config.path):
            self._scan_local_folder(source_config.path, "source")
        else:
            # 远程端：显示扫描到的文件列表
            self._display_remote_files(source_files, "source")

        if target_config.type == ConnectionType.LOCAL and os.path.isdir(target_config.path):
            self._scan_local_folder(target_config.path, "target")
        else:
            # 远程端：显示扫描到的文件列表
            self._display_remote_files(target_files, "target")

        # 比较文件
        new_count = 0
        update_count = 0
        delete_count = 0

        # 检查源端文件
        for rel_path, (src_size, src_mtime) in source_files.items():
            if rel_path not in target_files:
                # 新文件
                self._add_preview_row("➕ 新增", rel_path,
                                      f"{self._format_size(src_size)} | {datetime.fromtimestamp(src_mtime).strftime('%m-%d %H:%M')}",
                                      "—")
                new_count += 1
            else:
                # 文件存在，检查是否需要更新
                tgt_size, tgt_mtime = target_files[rel_path]
                need_update = False

                if compare_method == CompareMethod.TIME_SIZE.value:
                    need_update = (src_size != tgt_size) or (abs(src_mtime - tgt_mtime) > 2)
                elif compare_method == CompareMethod.TIME.value:
                    need_update = abs(src_mtime - tgt_mtime) > 2
                elif compare_method == CompareMethod.SIZE.value:
                    need_update = src_size != tgt_size
                elif compare_method == CompareMethod.HASH.value:
                    # MD5 比较（简化：先用大小+时间判断）
                    need_update = (src_size != tgt_size) or (abs(src_mtime - tgt_mtime) > 2)

                if need_update:
                    self._add_preview_row("🔄 更新", rel_path,
                                          f"{self._format_size(src_size)} | {datetime.fromtimestamp(src_mtime).strftime('%m-%d %H:%M')}",
                                          f"{self._format_size(tgt_size)} | {datetime.fromtimestamp(tgt_mtime).strftime('%m-%d %H:%M')}")
                    update_count += 1

        # 检查目标端多余文件
        if self.delete_extra_check.isChecked():
            for rel_path, (tgt_size, tgt_mtime) in target_files.items():
                if rel_path not in source_files:
                    self._add_preview_row("❌ 删除", rel_path, "—",
                                          f"{self._format_size(tgt_size)} | {datetime.fromtimestamp(tgt_mtime).strftime('%m-%d %H:%M')}")
                    delete_count += 1

        # 更新统计
        total = new_count + update_count + delete_count
        self.stats_label.setText(f"发现 {total} 个差异项 (新增: {new_count}, 更新: {update_count}, 删除: {delete_count})")
        self.bottom_tabs.setTabText(self.preview_tab_index, f"📋 预览结果 ({total})")

        # 启用同步按钮
        self.sync_btn.setEnabled(total > 0)

    def _get_current_filter_rule(self) -> SyncFilterRule:
        """获取当前设置的过滤规则"""
        include_text = self.include_list.toPlainText()
        include_patterns = [line.strip() for line in include_text.split("\n") if line.strip()]

        exclude_text = self.exclude_list.toPlainText()
        exclude_patterns = []
        exclude_dirs = []
        for line in exclude_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 以 \ 或 / 结尾的是目录
            if line.endswith("\\") or line.endswith("/"):
                dir_name = line.strip("\\/")
                if dir_name:
                    exclude_dirs.append(dir_name)
            else:
                exclude_patterns.append(line)

        return SyncFilterRule(
            include_patterns=include_patterns if include_patterns else ["*"],
            exclude_patterns=exclude_patterns,
            exclude_dirs=exclude_dirs,
            include_hidden=self.include_hidden_check.isChecked()
        )

    def _should_include_file(self, filename: str, is_dir: bool = False) -> bool:
        """检查文件是否应该包含（根据当前过滤规则）"""
        import fnmatch
        filter_rule = self._get_current_filter_rule()

        # 检查隐藏文件
        if not filter_rule.include_hidden and filename.startswith('.'):
            return False

        # 检查排除目录
        if is_dir and filename in filter_rule.exclude_dirs:
            return False

        # 检查排除模式
        for pattern in filter_rule.exclude_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return False

        # 检查包含模式（仅对文件）
        if not is_dir and filter_rule.include_patterns:
            matched = any(fnmatch.fnmatch(filename, p) for p in filter_rule.include_patterns)
            if not matched:
                return False

        return True

    def _scan_endpoint_for_compare(self, config, time_range=None) -> tuple:
        """
        扫描端点（本地/FTP/SFTP）用于比较
        返回 (files_dict, error_message)
        files_dict: {relative_path: (size, mtime)}
        error_message: 错误信息，成功时为 None
        """
        import os
        from core.sync_engine import create_connector

        result = {}

        if config.type == ConnectionType.LOCAL:
            # 本地文件系统
            if not os.path.isdir(config.path):
                return {}, f"目录不存在: {config.path}"

            try:
                for item in os.listdir(config.path):
                    item_path = os.path.join(config.path, item)
                    is_dir = os.path.isdir(item_path)

                    # 应用过滤规则
                    if not self._should_include_file(item, is_dir):
                        continue

                    if os.path.isfile(item_path):
                        size = os.path.getsize(item_path)
                        mtime = os.path.getmtime(item_path)

                        # 应用时间过滤
                        if time_range:
                            start_ts, end_ts = time_range
                            if mtime < start_ts or mtime > end_ts:
                                continue

                        result[item] = (size, mtime)
                return result, None
            except Exception as e:
                return {}, f"扫描失败: {str(e)}"
        else:
            # 远程连接 (FTP/SFTP)
            try:
                connector = create_connector(config)
                if not connector.connect():
                    return {}, f"连接失败: {config.host}:{config.port}"

                try:
                    files = connector.list_files()
                    for file_info in files:
                        # 应用过滤规则
                        if not self._should_include_file(file_info.name, file_info.is_dir):
                            continue

                        if not file_info.is_dir:
                            # 应用时间过滤
                            if time_range and file_info.mtime:
                                start_ts, end_ts = time_range
                                if file_info.mtime < start_ts or file_info.mtime > end_ts:
                                    continue
                            result[file_info.path] = (file_info.size, file_info.mtime)
                    return result, None
                finally:
                    connector.disconnect()
            except Exception as e:
                return {}, f"远程扫描失败: {str(e)}"

    def _scan_folder_for_compare(self, path: str, time_range=None) -> dict:
        """扫描本地文件夹用于比较，返回 {relative_path: (size, mtime)}"""
        import os
        result = {}

        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    mtime = os.path.getmtime(item_path)

                    # 应用时间过滤
                    if time_range:
                        start_ts, end_ts = time_range
                        if mtime < start_ts or mtime > end_ts:
                            continue

                    result[item] = (size, mtime)
        except Exception:
            pass

        return result

    def _add_preview_row(self, action: str, file_path: str, source_info: str, target_info: str):
        """添加预览行"""
        row = self.preview_table.rowCount()
        self.preview_table.insertRow(row)
        self.preview_table.setItem(row, 0, QTableWidgetItem(action))
        self.preview_table.setItem(row, 1, QTableWidgetItem(file_path))
        self.preview_table.setItem(row, 2, QTableWidgetItem(source_info))
        self.preview_table.setItem(row, 3, QTableWidgetItem(target_info))
        self.preview_items.append((action, file_path))

    def _do_sync(self):
        """执行同步操作"""
        from core.sync_engine import SyncEngine
        from ui.sync_progress_dialog import SyncProgressDialog, SyncWorkerThread

        source_config = self._get_connection_config("source")
        target_config = self._get_connection_config("target")

        # 验证配置
        if source_config.type == ConnectionType.LOCAL and not source_config.path:
            MsgBox.warning(self, "提示", "请先选择源端路径")
            return
        if target_config.type == ConnectionType.LOCAL and not target_config.path:
            MsgBox.warning(self, "提示", "请先选择目标端路径")
            return

        # 确认同步
        count = len(self.preview_items)
        if count == 0:
            MsgBox.information(self, "提示", "没有需要同步的文件")
            return

        # 计算预估总大小
        total_bytes = self._estimate_total_bytes()

        reply = MsgBox.question(
            self, "确认同步",
            f"即将同步 {count} 个文件，是否继续？\n\n"
            f"源端: {source_config.path}\n"
            f"目标端: {target_config.path}\n"
            f"线程数: {self.thread_spin.value()}\n"
            f"预估大小: {self._format_size(total_bytes)}"
        )
        if reply != MsgBox.Yes:
            return

        # 构建同步配置
        sync_config = self._build_sync_config()
        if not sync_config:
            return

        # 创建同步引擎
        thread_count = self.thread_spin.value()
        engine = SyncEngine(sync_config, thread_count)

        # 连接
        success, msg = engine.connect()
        if not success:
            MsgBox.critical(self, "连接失败", msg)
            return

        # 创建进度对话框
        progress_dialog = SyncProgressDialog(engine, count, total_bytes, self)

        # 创建工作线程
        self._sync_worker = SyncWorkerThread(engine, self)

        # 连接信号
        def on_progress(msg, current, total, bytes_transferred):
            progress_dialog.update_progress(msg, current, total, bytes_transferred)

        def on_finished(result):
            engine.disconnect()
            progress_dialog.on_sync_finished(result)

            # 显示结果摘要
            if result.success:
                MsgBox.information(
                    self, "同步完成",
                    f"同步完成！\n\n"
                    f"复制: {result.copied_files} 个文件\n"
                    f"更新: {result.updated_files} 个文件\n"
                    f"删除: {result.deleted_files} 个文件\n"
                    f"跳过: {result.skipped_files} 个文件\n"
                    f"传输: {self._format_size(result.transferred_bytes)}\n"
                    f"耗时: {result.duration:.1f} 秒"
                )
            elif result.errors:
                error_msg = "\n".join(result.errors[:10])
                if len(result.errors) > 10:
                    error_msg += f"\n... 还有 {len(result.errors) - 10} 个错误"
                MsgBox.warning(
                    self, "同步完成（有错误）",
                    f"同步完成，但有 {result.failed_files} 个文件失败\n\n{error_msg}"
                )

            # 刷新文件列表
            self._load_path("source")
            self._load_path("target")

            # 清空预览
            self.preview_table.setRowCount(0)
            self.preview_items = []
            self.sync_btn.setEnabled(False)
            self.stats_label.setText("同步完成，点击「比较」查看新差异")
            self.bottom_tabs.setTabText(self.preview_tab_index, "📋 预览结果 (0)")

        self._sync_worker.progress_updated.connect(on_progress)
        self._sync_worker.sync_finished.connect(on_finished)

        # 启动工作线程
        self._sync_worker.start()

        # 显示进度对话框（使用 try-except 防止闪退）
        try:
            progress_dialog.exec_()
        except Exception as e:
            import traceback
            traceback.print_exc()
            MsgBox.critical(self, "错误", f"同步过程中发生错误: {str(e)}")

    def _estimate_total_bytes(self) -> int:
        """估算需要传输的总字节数"""
        import os
        total = 0
        source_path = self.source_path_edit.text()

        for action, file_path in self.preview_items:
            if action in ["→ 新增", "→ 更新", "← 新增", "← 更新"]:
                try:
                    if action.startswith("→"):
                        full_path = os.path.join(source_path, file_path)
                    else:
                        full_path = os.path.join(self.target_path_edit.text(), file_path)
                    if os.path.isfile(full_path):
                        total += os.path.getsize(full_path)
                except:
                    pass
        return total

    def _build_sync_config(self):
        """构建同步配置"""
        from core.models import SyncConfig, SyncMode, CompareMethod, SyncFilterRule

        source_config = self._get_connection_config("source")
        target_config = self._get_connection_config("target")

        # 解析过滤规则
        include_patterns = []
        exclude_patterns = []
        exclude_dirs = []

        for line in self.include_list.toPlainText().strip().split('\n'):
            line = line.strip()
            if line:
                include_patterns.append(line)

        for line in self.exclude_list.toPlainText().strip().split('\n'):
            line = line.strip()
            if line:
                if line.startswith('\\') and line.endswith('\\'):
                    exclude_dirs.append(line.strip('\\'))
                else:
                    exclude_patterns.append(line)

        time_filter_type = self.time_filter_combo.currentData()
        time_start = None
        time_end = None
        if time_filter_type == "custom":
            time_start = self.time_start_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
            time_end = self.time_end_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss")

        filter_rule = SyncFilterRule(
            include_patterns=include_patterns if include_patterns else ["*"],
            exclude_patterns=exclude_patterns,
            exclude_dirs=exclude_dirs,
            include_hidden=self.include_hidden_check.isChecked(),
            time_filter_type=time_filter_type,
            time_filter_start=time_start,
            time_filter_end=time_end
        )

        return SyncConfig(
            source=source_config,
            target=target_config,
            sync_mode=SyncMode(self.sync_mode_combo.currentData()),
            compare_method=CompareMethod(self.compare_combo.currentData()),
            delete_extra=self.delete_extra_check.isChecked(),
            continue_on_error=self.continue_on_error_check.isChecked(),
            filter_rule=filter_rule
        )

    def _scan_local_folder(self, path: str, side: str):
        """扫描本地文件夹并填充树"""
        import os
        from datetime import datetime
        from PyQt5.QtCore import Qt

        tree = getattr(self, f"{side}_tree")
        tree.clear()

        # 获取时间过滤范围
        time_range = self._get_time_filter_range()

        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                is_dir = os.path.isdir(item_path)
                mtime = os.path.getmtime(item_path)

                # 应用过滤规则
                if not self._should_include_file(item, is_dir):
                    continue

                # 应用时间过滤（仅对文件）
                if not is_dir and time_range:
                    start_ts, end_ts = time_range
                    if mtime < start_ts or mtime > end_ts:
                        continue

                tree_item = QTreeWidgetItem()
                # 存储原始名称用于排序
                display_name = ("📁 " if is_dir else "📄 ") + item
                tree_item.setText(0, display_name)
                tree_item.setData(0, Qt.UserRole, (0 if is_dir else 1, item.lower()))  # 文件夹优先，然后按名称

                if not is_dir:
                    size = os.path.getsize(item_path)
                    tree_item.setText(1, self._format_size(size))
                    tree_item.setData(1, Qt.UserRole, size)  # 存储原始大小用于排序
                else:
                    tree_item.setData(1, Qt.UserRole, -1)  # 文件夹排在前面

                tree_item.setText(2, datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"))
                tree_item.setData(2, Qt.UserRole, mtime)  # 存储时间戳用于排序

                tree.addTopLevelItem(tree_item)
        except Exception:
            pass

    def _display_remote_files(self, files_dict: dict, side: str):
        """显示远程文件列表到树形控件"""
        from datetime import datetime
        from PyQt5.QtCore import Qt

        tree = getattr(self, f"{side}_tree")
        tree.clear()

        for rel_path, (size, mtime) in files_dict.items():
            tree_item = QTreeWidgetItem()
            display_name = "📄 " + rel_path
            tree_item.setText(0, display_name)
            tree_item.setData(0, Qt.UserRole, (1, rel_path.lower()))  # 文件排序

            tree_item.setText(1, self._format_size(size))
            tree_item.setData(1, Qt.UserRole, size)

            if mtime:
                tree_item.setText(2, datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"))
                tree_item.setData(2, Qt.UserRole, mtime)
            else:
                tree_item.setText(2, "--")
                tree_item.setData(2, Qt.UserRole, 0)

            tree.addTopLevelItem(tree_item)

    def _get_time_filter_range(self):
        """获取时间过滤范围，返回 (start_timestamp, end_timestamp) 或 None"""
        from datetime import datetime, timedelta

        filter_type = self.time_filter_combo.currentData()
        if filter_type == "none":
            return None

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if filter_type == "today":
            return (today_start.timestamp(), now.timestamp())
        elif filter_type == "yesterday":
            yesterday = today_start - timedelta(days=1)
            return (yesterday.timestamp(), today_start.timestamp())
        elif filter_type == "days_3":
            start = today_start - timedelta(days=3)
            return (start.timestamp(), now.timestamp())
        elif filter_type == "days_7":
            start = today_start - timedelta(days=7)
            return (start.timestamp(), now.timestamp())
        elif filter_type == "days_30":
            start = today_start - timedelta(days=30)
            return (start.timestamp(), now.timestamp())
        elif filter_type == "custom":
            start = self.time_start_edit.dateTime().toSecsSinceEpoch()
            end = self.time_end_edit.dateTime().toSecsSinceEpoch()
            return (start, end)

        return None

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _on_time_filter_changed(self):
        """时间过滤选项变化"""
        filter_type = self.time_filter_combo.currentData()
        # 只有选择"自定义"时才显示时间范围选择器
        is_custom = filter_type == "custom"
        self.time_start_edit.setVisible(is_custom)
        self.time_end_edit.setVisible(is_custom)

    def _show_cron_config(self):
        """显示 Cron 配置对话框 - 类似批处理任务的小时选择"""
        from PyQt5.QtWidgets import QDialog, QGridLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("定时规则配置")
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        # 小时选择卡片
        hours_group = QGroupBox("选择执行小时")
        hours_group.setStyleSheet("QGroupBox { padding-top: 15px; }")
        hours_layout = QVBoxLayout(hours_group)

        # 小时复选框 - 4行6列
        self._hour_checkboxes = []
        hours_grid = QGridLayout()
        hours_grid.setHorizontalSpacing(8)
        hours_grid.setVerticalSpacing(6)
        for i in range(24):
            cb = QCheckBox(f"{i:02d}:00")
            self._hour_checkboxes.append(cb)
            hours_grid.addWidget(cb, i // 6, i % 6)
        hours_layout.addLayout(hours_grid)

        # 快捷按钮
        quick_btn_layout = QHBoxLayout()
        for text, hours in [
            ("全选", list(range(24))),
            ("清空", []),
            ("工作时间", list(range(9, 18))),
            ("白天", list(range(6, 22))),
            ("夜间", list(range(22, 24)) + list(range(0, 6))),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda _, h=hours: self._select_cron_hours(h))
            quick_btn_layout.addWidget(btn)
        quick_btn_layout.addStretch()
        hours_layout.addLayout(quick_btn_layout)

        # 分钟设置
        minute_layout = QHBoxLayout()
        minute_layout.addWidget(QLabel("在选中小时的第"))
        self._hours_minute_spin = QSpinBox()
        self._hours_minute_spin.setRange(0, 59)
        self._hours_minute_spin.setValue(0)
        self._hours_minute_spin.setFixedWidth(50)
        minute_layout.addWidget(self._hours_minute_spin)
        minute_layout.addWidget(QLabel("分钟执行"))
        minute_layout.addStretch()
        hours_layout.addLayout(minute_layout)

        layout.addWidget(hours_group)

        # Cron 表达式输入
        cron_group = QGroupBox("Cron 表达式")
        cron_group.setStyleSheet("QGroupBox { padding-top: 15px; }")
        cron_layout = QVBoxLayout(cron_group)

        self._cron_preview_edit = QLineEdit()
        self._cron_preview_edit.setText(self.cron_edit.text())
        self._cron_preview_edit.setPlaceholderText("秒 分 时 日 月 周")
        cron_layout.addWidget(self._cron_preview_edit)

        # 快捷按钮
        quick_cron_layout = QHBoxLayout()
        for label, cron in [
            ("每小时", "0 0 * * * *"),
            ("每天0点", "0 0 0 * * *"),
            ("每周一", "0 0 0 * * 1"),
            ("每月1号", "0 0 0 1 * *"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=cron: self._cron_preview_edit.setText(c))
            quick_cron_layout.addWidget(btn)
        quick_cron_layout.addStretch()
        cron_layout.addLayout(quick_cron_layout)

        layout.addWidget(cron_group)

        # 连接信号：小时选择变化时更新 Cron
        for cb in self._hour_checkboxes:
            cb.stateChanged.connect(lambda: self._update_cron_preview())
        self._hours_minute_spin.valueChanged.connect(self._update_cron_preview)

        # 解析当前 Cron 到小时选择
        self._parse_cron_to_hours_dialog()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(lambda: [
            self.cron_edit.setText(self._cron_preview_edit.text()),
            dialog.accept()
        ])
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        dialog.exec_()

    def _select_cron_hours(self, hours):
        """选择指定的小时"""
        hours_set = set(hours)
        for i, cb in enumerate(self._hour_checkboxes):
            cb.setChecked(i in hours_set)
        self._update_cron_preview()

    def _update_cron_preview(self):
        """从小时选择生成 Cron 表达式"""
        selected_hours = [i for i, cb in enumerate(self._hour_checkboxes) if cb.isChecked()]
        minute = self._hours_minute_spin.value()
        if selected_hours:
            hours_str = ','.join(str(h) for h in selected_hours)
            cron = f"0 {minute} {hours_str} * * *"
            self._cron_preview_edit.setText(cron)

    def _parse_cron_to_hours_dialog(self):
        """解析 Cron 表达式到小时选择"""
        cron = self.cron_edit.text().strip()
        if not cron:
            return

        parts = cron.split()
        if len(parts) != 6:  # 秒 分 时 日 月 周
            return

        try:
            sec, minute, hour, day, month, weekday = parts

            # 指定小时: 0 M H1,H2,H3 * * *
            if day == '*' and month == '*' and weekday == '*' and minute.isdigit():
                self._hours_minute_spin.setValue(int(minute))

                if ',' in hour:
                    hours = [int(h) for h in hour.split(',')]
                    hours_set = set(hours)
                    for i, cb in enumerate(self._hour_checkboxes):
                        cb.blockSignals(True)
                        cb.setChecked(i in hours_set)
                        cb.blockSignals(False)
                elif hour.isdigit():
                    h = int(hour)
                    for i, cb in enumerate(self._hour_checkboxes):
                        cb.blockSignals(True)
                        cb.setChecked(i == h)
                        cb.blockSignals(False)
        except (ValueError, IndexError):
            pass

    def _browse_folder(self, prefix: str):
        """浏览选择文件夹"""
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            getattr(self, f"{prefix}_path_edit").setText(path)

    def _load_task_data(self):
        """加载任务数据"""
        self.name_edit.setText(self.task.name)
        self.desc_edit.setText(self.task.description)
        self.cron_edit.setText(self.task.cron_expression)
        self.enabled_check.setChecked(self.task.enabled)

        config = self.task.sync_config
        if config:
            # 源端配置
            if config.source:
                self._load_connection("source", config.source)

            # 目标端配置
            if config.target:
                self._load_connection("target", config.target)

            # 同步选项
            idx = self.sync_mode_combo.findData(config.sync_mode.value)
            if idx >= 0:
                self.sync_mode_combo.setCurrentIndex(idx)

            idx = self.compare_combo.findData(config.compare_method.value)
            if idx >= 0:
                self.compare_combo.setCurrentIndex(idx)

            self.delete_extra_check.setChecked(config.delete_extra)
            self.continue_on_error_check.setChecked(config.continue_on_error)

            # 过滤规则
            if config.filter_rule:
                # 加载包含规则到列表
                include_rules = config.filter_rule.include_patterns.copy()
                if include_rules:
                    self.include_list.setText("\n".join(include_rules))

                # 加载排除规则到列表（合并文件模式和目录）
                exclude_rules = config.filter_rule.exclude_patterns.copy()
                for d in config.filter_rule.exclude_dirs:
                    exclude_rules.append(f"\\{d}\\")
                if exclude_rules:
                    self.exclude_list.setText("\n".join(exclude_rules))

                self.include_hidden_check.setChecked(config.filter_rule.include_hidden)

                # 时间过滤
                idx = self.time_filter_combo.findData(config.filter_rule.time_filter_type)
                if idx >= 0:
                    self.time_filter_combo.setCurrentIndex(idx)

                # 自定义时间范围
                if config.filter_rule.time_filter_start:
                    from PyQt5.QtCore import QDateTime
                    self.time_start_edit.setDateTime(
                        QDateTime.fromString(config.filter_rule.time_filter_start, "yyyy-MM-ddTHH:mm:ss")
                    )
                if config.filter_rule.time_filter_end:
                    from PyQt5.QtCore import QDateTime
                    self.time_end_edit.setDateTime(
                        QDateTime.fromString(config.filter_rule.time_filter_end, "yyyy-MM-ddTHH:mm:ss")
                    )

        # 加载 Webhook 和解析器表格
        self._refresh_webhook_table()
        self._refresh_parser_table()

    def _load_connection(self, prefix: str, conn: ConnectionConfig):
        """加载连接配置"""
        type_combo = getattr(self, f"{prefix}_type_combo")
        idx = type_combo.findData(conn.type.value)
        if idx >= 0:
            type_combo.setCurrentIndex(idx)

        getattr(self, f"{prefix}_path_edit").setText(conn.path or "")
        getattr(self, f"{prefix}_host_edit").setText(conn.host or "")
        getattr(self, f"{prefix}_port_spin").setValue(conn.port or 21)
        getattr(self, f"{prefix}_user_edit").setText(conn.username or "")
        getattr(self, f"{prefix}_pass_edit").setText(conn.password or "")

    def _get_connection_config(self, prefix: str) -> ConnectionConfig:
        """获取连接配置"""
        type_combo = getattr(self, f"{prefix}_type_combo")
        conn_type = ConnectionType(type_combo.currentData())

        return ConnectionConfig(
            type=conn_type,
            path=getattr(self, f"{prefix}_path_edit").text().strip(),
            host=getattr(self, f"{prefix}_host_edit").text().strip() if conn_type != ConnectionType.LOCAL else None,
            port=getattr(self, f"{prefix}_port_spin").value() if conn_type != ConnectionType.LOCAL else None,
            username=getattr(self, f"{prefix}_user_edit").text().strip() if conn_type != ConnectionType.LOCAL else None,
            password=getattr(self, f"{prefix}_pass_edit").text() if conn_type != ConnectionType.LOCAL else None
        )

    def _save(self):
        """保存任务"""
        name = self.name_edit.text().strip()
        if not name:
            MsgBox.warning(self, "错误", "请输入任务名称")
            return

        # 验证源端配置
        source_config = self._get_connection_config("source")
        if source_config.type == ConnectionType.LOCAL:
            if not source_config.path:
                MsgBox.warning(self, "错误", "请选择源端文件夹路径")
                return
        else:
            if not source_config.host:
                MsgBox.warning(self, "错误", "请输入源端服务器地址")
                return

        # 验证目标端配置
        target_config = self._get_connection_config("target")
        if target_config.type == ConnectionType.LOCAL:
            if not target_config.path:
                MsgBox.warning(self, "错误", "请选择目标端文件夹路径")
                return
        else:
            if not target_config.host:
                MsgBox.warning(self, "错误", "请输入目标端服务器地址")
                return

        cron = self.cron_edit.text().strip()
        if not cron:
            MsgBox.warning(self, "错误", "请输入 Cron 表达式")
            return

        # 构建过滤规则 - 从列表解析
        include_text = self.include_list.toPlainText()
        include_patterns = [line.strip() for line in include_text.split("\n") if line.strip()]

        exclude_text = self.exclude_list.toPlainText()
        exclude_patterns = []
        exclude_dirs = []
        for line in exclude_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 以 \ 结尾的是目录
            if line.endswith("\\") or line.endswith("/"):
                # 去掉开头和结尾的斜杠
                dir_name = line.strip("\\/")
                if dir_name:
                    exclude_dirs.append(dir_name)
            else:
                exclude_patterns.append(line)

        time_filter_type = self.time_filter_combo.currentData()
        time_start = None
        time_end = None
        if time_filter_type == "custom":
            time_start = self.time_start_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
            time_end = self.time_end_edit.dateTime().toString("yyyy-MM-ddTHH:mm:ss")

        filter_rule = SyncFilterRule(
            include_patterns=include_patterns if include_patterns else ["*"],
            exclude_patterns=exclude_patterns,
            exclude_dirs=exclude_dirs,
            include_hidden=self.include_hidden_check.isChecked(),
            time_filter_type=time_filter_type,
            time_filter_start=time_start,
            time_filter_end=time_end
        )

        # 构建同步配置
        sync_config = SyncConfig(
            source=source_config,
            target=target_config,
            sync_mode=SyncMode(self.sync_mode_combo.currentData()),
            compare_method=CompareMethod(self.compare_combo.currentData()),
            delete_extra=self.delete_extra_check.isChecked(),
            continue_on_error=self.continue_on_error_check.isChecked(),
            filter_rule=filter_rule
        )

        # 更新任务数据
        self.task.name = name
        self.task.description = self.desc_edit.text().strip()
        self.task.task_type = TaskType.SYNC
        self.task.cron_expression = cron
        self.task.enabled = self.enabled_check.isChecked()
        self.task.sync_config = sync_config
        self.task.webhooks = self.webhooks
        self.task.output_parsers = self.output_parsers

        if not self.task.enabled:
            self.task.status = TaskStatus.DISABLED
        elif self.task.status == TaskStatus.DISABLED:
            self.task.status = TaskStatus.PENDING

        self.accept()

    def get_task(self) -> Task:
        """获取任务对象"""
        return self.task

    # ==================== Webhook 方法 ====================

    def _refresh_global_webhooks(self):
        """刷新全局 Webhook 下拉列表"""
        self.global_webhook_combo.clear()
        global_webhooks = self.webhook_storage.load_webhooks()
        if not global_webhooks:
            self.global_webhook_combo.addItem("(无全局配置，请先在 Webhook 配置页面添加)", None)
        else:
            for wh in global_webhooks:
                self.global_webhook_combo.addItem(f"{wh.name} ({wh.url[:30]}...)", wh)

    def _refresh_webhook_table(self):
        """刷新 Webhook 表格"""
        self.webhook_table.setRowCount(len(self.webhooks))
        for row, wh in enumerate(self.webhooks):
            self.webhook_table.setItem(row, 0, QTableWidgetItem(wh.name))
            url_display = wh.url[:40] + "..." if len(wh.url) > 40 else wh.url
            self.webhook_table.setItem(row, 1, QTableWidgetItem(url_display))
            self.webhook_table.setItem(row, 2, QTableWidgetItem(wh.method))
            enabled_item = QTableWidgetItem("✓" if wh.enabled else "✗")
            self.webhook_table.setItem(row, 3, enabled_item)
        self.bottom_tabs.setTabText(self.webhook_tab_index, f"🔔 Webhooks ({len(self.webhooks)})")

    def _add_from_global(self):
        """从全局配置添加 Webhook"""
        webhook = self.global_webhook_combo.currentData()
        if not webhook:
            MsgBox.warning(self, "提示", "请先在 Webhook 配置页面添加全局配置")
            return

        # 检查是否已添加
        for wh in self.webhooks:
            if wh.id == webhook.id:
                MsgBox.warning(self, "提示", f"Webhook '{webhook.name}' 已添加")
                return

        # 复制一份添加到任务
        import copy
        new_webhook = copy.deepcopy(webhook)
        self.webhooks.append(new_webhook)
        self._refresh_webhook_table()

    def _add_webhook(self):
        """添加 Webhook"""
        from .webhook_dialog import WebhookDialog
        dialog = WebhookDialog(self)
        if dialog.exec_():
            webhook = dialog.get_webhook()
            self.webhooks.append(webhook)
            self._refresh_webhook_table()

    def _edit_webhook(self):
        """编辑 Webhook"""
        row = self.webhook_table.currentRow()
        if row < 0:
            MsgBox.warning(self, "提示", "请先选择一个 Webhook")
            return

        from .webhook_dialog import WebhookDialog
        webhook = self.webhooks[row]
        dialog = WebhookDialog(self, webhook)
        if dialog.exec_():
            self.webhooks[row] = dialog.get_webhook()
            self._refresh_webhook_table()

    def _delete_webhook(self):
        """删除 Webhook"""
        row = self.webhook_table.currentRow()
        if row < 0:
            MsgBox.warning(self, "提示", "请先选择一个 Webhook")
            return

        if MsgBox.question(self, "确认删除", f"确定要删除 Webhook '{self.webhooks[row].name}' 吗？"):
            del self.webhooks[row]
            self._refresh_webhook_table()

    # ==================== 输出解析器方法 ====================

    def _refresh_parser_table(self):
        """刷新解析器表格"""
        self.parser_table.setRowCount(len(self.output_parsers))
        for row, p in enumerate(self.output_parsers):
            self.parser_table.setItem(row, 0, QTableWidgetItem(f"{{var_{p.var_name}}}"))
            type_names = {"regex": "正则", "jsonpath": "JSON", "xpath": "XML", "line": "行", "split": "分隔"}
            self.parser_table.setItem(row, 1, QTableWidgetItem(type_names.get(p.parser_type, p.parser_type)))
            expr_display = p.expression[:30] + "..." if len(p.expression) > 30 else p.expression
            self.parser_table.setItem(row, 2, QTableWidgetItem(expr_display))
            enabled_item = QTableWidgetItem("✓" if p.enabled else "✗")
            self.parser_table.setItem(row, 3, enabled_item)
        self.bottom_tabs.setTabText(self.parser_tab_index, f"📊 输出解析 ({len(self.output_parsers)})")

    def _import_parsers(self):
        """从全局模板导入解析器"""
        storage = ParserStorage()
        global_parsers = storage.load_parsers()

        if not global_parsers:
            MsgBox.information(self, "提示", "没有全局解析器模板，请先在主界面的解析器模板页面添加")
            return

        from .parser_dialog import GlobalParserSelectDialog
        dialog = GlobalParserSelectDialog(self, global_parsers)
        if dialog.exec_():
            import copy
            for p in dialog.get_selected():
                # 检查是否已存在
                exists = any(ep.var_name == p.var_name for ep in self.output_parsers)
                if not exists:
                    self.output_parsers.append(copy.deepcopy(p))
            self._refresh_parser_table()

    def _add_parser(self):
        """添加解析器"""
        from .parser_dialog import ParserRuleDialog
        dialog = ParserRuleDialog(self)
        if dialog.exec_():
            self.output_parsers.append(dialog.get_parser())
            self._refresh_parser_table()

    def _edit_parser(self):
        """编辑解析器"""
        row = self.parser_table.currentRow()
        if row < 0:
            MsgBox.warning(self, "提示", "请先选择一个解析规则")
            return

        from .parser_dialog import ParserRuleDialog
        dialog = ParserRuleDialog(self, self.output_parsers[row])
        if dialog.exec_():
            self.output_parsers[row] = dialog.get_parser()
            self._refresh_parser_table()

    def _delete_parser(self):
        """删除解析器"""
        row = self.parser_table.currentRow()
        if row < 0:
            MsgBox.warning(self, "提示", "请先选择一个解析规则")
            return

        if MsgBox.question(self, "确认删除", f"确定要删除解析规则 '{{var_{self.output_parsers[row].var_name}}}' 吗？"):
            del self.output_parsers[row]
            self._refresh_parser_table()

