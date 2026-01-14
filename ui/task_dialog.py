# -*- coding: utf-8 -*-
"""
任务编辑对话框
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QTextEdit, QCheckBox, QPushButton,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QGroupBox,
    QLabel, QSpinBox, QAbstractItemView, QFileDialog, QFrame
)
from PyQt5.QtCore import Qt

from core.models import Task, WebhookConfig, TaskStatus, OutputParser, ParserStorage
from .message_box import MsgBox


class TaskDialog(QDialog):
    """任务编辑对话框"""
    
    def __init__(self, parent=None, task: Task = None):
        super().__init__(parent)
        self.task = task or Task()
        self.is_edit = task is not None
        self.webhooks = list(self.task.webhooks) if self.task.webhooks else []
        self.output_parsers = list(self.task.output_parsers) if self.task.output_parsers else []

        self._init_ui()
        self._load_task_data()
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("编辑任务" if self.is_edit else "添加任务")
        self.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(self)
        
        # 选项卡
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # 基本信息选项卡
        basic_tab = QWidget()
        basic_layout = QFormLayout(basic_tab)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("任务名称")
        basic_layout.addRow("名称:", self.name_edit)
        
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("任务描述（可选）")
        basic_layout.addRow("描述:", self.desc_edit)
        
        # 命令输入区域
        command_widget = QWidget()
        command_layout = QVBoxLayout(command_widget)
        command_layout.setContentsMargins(0, 0, 0, 0)

        self.command_edit = QTextEdit()
        self.command_edit.setPlaceholderText("输入要执行的批处理命令，或点击下方按钮选择批处理文件")
        self.command_edit.setMaximumHeight(80)
        command_layout.addWidget(self.command_edit)

        # 浏览按钮行
        browse_layout = QHBoxLayout()
        browse_layout.setContentsMargins(0, 0, 0, 0)

        browse_script_btn = QPushButton("选择脚本文件...")
        browse_script_btn.clicked.connect(self._browse_script_file)
        browse_layout.addWidget(browse_script_btn)

        browse_exe_btn = QPushButton("选择可执行文件(.exe)...")
        browse_exe_btn.clicked.connect(self._browse_exe_file)
        browse_layout.addWidget(browse_exe_btn)

        browse_layout.addStretch()
        command_layout.addLayout(browse_layout)

        basic_layout.addRow("命令:", command_widget)

        # 工作目录
        workdir_widget = QWidget()
        workdir_layout = QHBoxLayout(workdir_widget)
        workdir_layout.setContentsMargins(0, 0, 0, 0)

        self.workdir_edit = QLineEdit()
        self.workdir_edit.setPlaceholderText("工作目录（可选，默认为当前目录）")
        workdir_layout.addWidget(self.workdir_edit)

        browse_dir_btn = QPushButton("浏览...")
        browse_dir_btn.clicked.connect(self._browse_workdir)
        workdir_layout.addWidget(browse_dir_btn)

        basic_layout.addRow("工作目录:", workdir_widget)
        
        # 定时设置
        cron_group = QGroupBox("定时设置")
        cron_main_layout = QVBoxLayout(cron_group)

        # Cron 表达式输入
        cron_input_layout = QHBoxLayout()
        cron_input_layout.addWidget(QLabel("Cron 表达式:"))
        self.cron_edit = QLineEdit()
        self.cron_edit.setPlaceholderText("分 时 日 月 周 (例如: */5 * * * * 每5分钟)")
        self.cron_edit.setText("*/5 * * * *")
        cron_input_layout.addWidget(self.cron_edit)
        cron_main_layout.addLayout(cron_input_layout)

        # 指定小时选择卡片
        self.hours_group = QGroupBox("快捷选择执行小时")
        hours_group_layout = QVBoxLayout(self.hours_group)
        hours_group_layout.setSpacing(8)
        hours_group_layout.setContentsMargins(10, 15, 10, 10)

        # 小时复选框 - 4行6列
        self.hour_checkboxes = []
        hours_grid_widget = QWidget()
        hours_grid = QGridLayout(hours_grid_widget)
        hours_grid.setContentsMargins(0, 0, 0, 0)
        hours_grid.setHorizontalSpacing(8)
        hours_grid.setVerticalSpacing(6)
        for i in range(24):
            cb = QCheckBox(f"{i:02d}:00")
            cb.stateChanged.connect(self._update_cron_from_hours)
            self.hour_checkboxes.append(cb)
            hours_grid.addWidget(cb, i // 6, i % 6)
        hours_group_layout.addWidget(hours_grid_widget)

        # 快捷按钮
        quick_btn_widget = QWidget()
        quick_btn_layout = QHBoxLayout(quick_btn_widget)
        quick_btn_layout.setContentsMargins(0, 0, 0, 0)
        quick_btn_layout.setSpacing(5)
        for text, tip, hours in [
            ("全选", None, range(24)),
            ("清空", None, []),
            ("工作时间", "9:00-18:00", range(9, 18)),
            ("白天", "6:00-22:00", range(6, 22)),
            ("夜间", "22:00-6:00", list(range(22, 24)) + list(range(0, 6))),
        ]:
            btn = QPushButton(text)
            if tip:
                btn.setToolTip(tip)
            btn.clicked.connect(lambda _, h=hours: self._select_hours(h))
            quick_btn_layout.addWidget(btn)
        quick_btn_layout.addStretch()
        hours_group_layout.addWidget(quick_btn_widget)

        # 分钟设置
        minute_widget = QWidget()
        minute_layout = QHBoxLayout(minute_widget)
        minute_layout.setContentsMargins(0, 0, 0, 0)
        minute_layout.addWidget(QLabel("在选中小时的第"))
        self.hours_minute_spin = QSpinBox()
        self.hours_minute_spin.setRange(0, 59)
        self.hours_minute_spin.setValue(0)
        self.hours_minute_spin.setFixedWidth(50)
        self.hours_minute_spin.valueChanged.connect(self._update_cron_from_hours)
        minute_layout.addWidget(self.hours_minute_spin)
        minute_layout.addWidget(QLabel("分钟执行"))
        minute_layout.addStretch()
        hours_group_layout.addWidget(minute_widget)

        cron_main_layout.addWidget(self.hours_group)

        # 快捷选项
        quick_layout = QHBoxLayout()
        quick_btns = [
            ("每分钟", "* * * * *"),
            ("每5分钟", "*/5 * * * *"),
            ("每小时", "0 * * * *"),
            ("每天0点", "0 0 * * *"),
            ("每周一", "0 0 * * 1"),
        ]
        for label, cron in quick_btns:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=cron: self.cron_edit.setText(c))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        cron_main_layout.addLayout(quick_layout)

        # 兼容旧代码
        self.cron_preview = QLabel()
        self.cron_preview_main = QLabel()
        self.cron_edit.textChanged.connect(self._on_cron_text_changed)

        basic_layout.addRow(cron_group)

        self.enabled_check = QCheckBox("启用任务")
        self.enabled_check.setChecked(True)
        basic_layout.addRow("", self.enabled_check)

        # 执行窗口选项
        self.show_window_check = QCheckBox("手动执行时显示输出窗口")
        self.show_window_check.setChecked(True)
        self.show_window_check.setToolTip("勾选后点击执行按钮会弹出窗口显示实时输出；\n不勾选则在后台静默执行，可随时点击查看输出")
        basic_layout.addRow("", self.show_window_check)

        # 终止上次实例选项
        self.kill_previous_check = QCheckBox("执行前终止上次运行的实例")
        self.kill_previous_check.setChecked(False)
        self.kill_previous_check.setToolTip("如果上次执行的进程还在运行，先终止它再启动新实例；\n适用于需要确保只有一个实例运行的任务")
        basic_layout.addRow("", self.kill_previous_check)

        tabs.addTab(basic_tab, "基本信息")
        
        # Webhook 选项卡
        webhook_tab = QWidget()
        webhook_layout = QVBoxLayout(webhook_tab)

        # 提示信息
        hint_label = QLabel("从全局配置中选择要使用的 Webhook，或为此任务单独添加")
        hint_label.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 5px;")
        webhook_layout.addWidget(hint_label)

        # 从全局配置选择
        from core.models import WebhookStorage
        self.webhook_storage = WebhookStorage()

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

        tabs.addTab(webhook_tab, f"Webhooks ({len(self.webhooks)})")

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

        tabs.addTab(parser_tab, f"输出解析 ({len(self.output_parsers)})")

        self.tabs = tabs

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)

    def _browse_script_file(self):
        """浏览选择脚本文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择脚本文件",
            "",
            "批处理脚本 (*.bat *.cmd);;"
            "PowerShell 脚本 (*.ps1);;"
            "Python 脚本 (*.py);;"
            "VBScript (*.vbs);;"
            "JavaScript (*.js);;"
            "Shell 脚本 (*.sh);;"
            "所有脚本 (*.bat *.cmd *.ps1 *.py *.vbs *.js *.sh);;"
            "所有文件 (*.*)"
        )
        if file_path:
            import os
            ext = os.path.splitext(file_path)[1].lower()

            # 根据文件类型生成对应的执行命令
            if ext in ('.bat', '.cmd'):
                # 批处理文件使用 call
                if ' ' in file_path:
                    command = f'call "{file_path}"'
                else:
                    command = f'call {file_path}'
            elif ext == '.ps1':
                # PowerShell 脚本
                command = f'powershell -ExecutionPolicy Bypass -File "{file_path}"'
            elif ext == '.py':
                # Python 脚本
                command = f'python "{file_path}"'
            elif ext == '.vbs':
                # VBScript
                command = f'cscript //nologo "{file_path}"'
            elif ext == '.js':
                # JavaScript (Node.js)
                command = f'node "{file_path}"'
            elif ext == '.sh':
                # Shell 脚本 (Git Bash / WSL)
                command = f'bash "{file_path}"'
            else:
                # 其他文件直接执行
                if ' ' in file_path:
                    command = f'"{file_path}"'
                else:
                    command = file_path

            self.command_edit.setPlainText(command)

            # 自动设置工作目录为脚本文件所在目录
            work_dir = os.path.dirname(file_path)
            if work_dir and not self.workdir_edit.text():
                self.workdir_edit.setText(work_dir)

    def _browse_exe_file(self):
        """浏览选择可执行文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择可执行文件",
            "",
            "可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if file_path:
            # 如果路径包含空格，添加引号
            if ' ' in file_path:
                file_path = f'"{file_path}"'
            self.command_edit.setPlainText(file_path)

            # 自动设置工作目录
            import os
            work_dir = os.path.dirname(file_path.strip('"'))
            if work_dir and not self.workdir_edit.text():
                self.workdir_edit.setText(work_dir)

    def _browse_workdir(self):
        """浏览选择工作目录"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "选择工作目录",
            self.workdir_edit.text() or ""
        )
        if dir_path:
            self.workdir_edit.setText(dir_path)

    # ==================== 定时设置方法 ====================

    def _select_hours(self, hours):
        """选择指定的小时"""
        hours_set = set(hours)
        for i, cb in enumerate(self.hour_checkboxes):
            cb.setChecked(i in hours_set)
        self._update_cron_from_hours()

    def _update_cron_from_hours(self):
        """从小时选择生成 Cron 表达式"""
        selected_hours = [i for i, cb in enumerate(self.hour_checkboxes) if cb.isChecked()]
        minute = self.hours_minute_spin.value()
        if selected_hours:
            hours_str = ','.join(str(h) for h in selected_hours)
            cron = f"{minute} {hours_str} * * *"
            self.cron_edit.setText(cron)

    def _on_cron_text_changed(self):
        """Cron 文本改变时更新预览"""
        cron = self.cron_edit.text().strip()
        self.cron_preview.setText(cron if cron else "(空)")
        self.cron_preview_main.setText(cron if cron else "(空)")

    def _load_task_data(self):
        """加载任务数据"""
        self.name_edit.setText(self.task.name)
        self.desc_edit.setText(self.task.description)
        self.command_edit.setPlainText(self.task.command)
        self.workdir_edit.setText(self.task.working_dir)

        # 加载 Cron 表达式
        cron = self.task.cron_expression
        self.cron_edit.setText(cron)
        self._parse_cron_to_hours(cron)

        self.enabled_check.setChecked(self.task.enabled)
        self.show_window_check.setChecked(self.task.show_window)
        self.kill_previous_check.setChecked(getattr(self.task, 'kill_previous', False))
        self._refresh_webhook_table()
        self._refresh_parser_table()

    def _parse_cron_to_hours(self, cron: str):
        """尝试将 Cron 表达式解析到小时选择"""
        if not cron:
            return

        parts = cron.split()
        if len(parts) != 5:
            return

        minute, hour, day, month, weekday = parts

        try:
            # 指定小时: M H1,H2,H3 * * * 或单个小时 M H * * *
            if day == '*' and month == '*' and weekday == '*' and minute.isdigit():
                if ',' in hour:
                    hours = [int(h) for h in hour.split(',')]
                    self.hours_minute_spin.setValue(int(minute))
                    hours_set = set(hours)
                    for i, cb in enumerate(self.hour_checkboxes):
                        cb.blockSignals(True)
                        cb.setChecked(i in hours_set)
                        cb.blockSignals(False)
        except (ValueError, IndexError):
            pass
    
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
        self.tabs.setTabText(1, f"Webhooks ({len(self.webhooks)})")

    def _refresh_global_webhooks(self):
        """刷新全局 Webhook 下拉列表"""
        self.global_webhook_combo.clear()
        global_webhooks = self.webhook_storage.load_webhooks()
        if not global_webhooks:
            self.global_webhook_combo.addItem("(无全局配置，请先在 Webhook 配置页面添加)", None)
        else:
            for wh in global_webhooks:
                self.global_webhook_combo.addItem(f"{wh.name} ({wh.url[:30]}...)", wh)

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
        self.tabs.setTabText(2, f"输出解析 ({len(self.output_parsers)})")

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

    def _save(self):
        """保存任务"""
        name = self.name_edit.text().strip()
        if not name:
            MsgBox.warning(self, "错误", "请输入任务名称")
            return

        command = self.command_edit.toPlainText().strip()
        if not command:
            MsgBox.warning(self, "错误", "请输入要执行的命令")
            return

        cron = self.cron_edit.text().strip()
        if not cron:
            MsgBox.warning(self, "错误", "请输入 Cron 表达式")
            return

        # 更新任务数据
        self.task.name = name
        self.task.description = self.desc_edit.text().strip()
        self.task.command = command
        self.task.working_dir = self.workdir_edit.text().strip()
        self.task.cron_expression = cron
        self.task.enabled = self.enabled_check.isChecked()
        self.task.show_window = self.show_window_check.isChecked()
        self.task.kill_previous = self.kill_previous_check.isChecked()
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


class WebhookDialog(QDialog):
    """Webhook 编辑对话框"""

    def __init__(self, parent=None, webhook: WebhookConfig = None):
        super().__init__(parent)
        self.webhook = webhook or WebhookConfig()
        self.is_edit = webhook is not None

        self._init_ui()
        self._load_data()

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("编辑 Webhook" if self.is_edit else "添加 Webhook")
        self.setMinimumWidth(500)

        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Webhook 名称")
        layout.addRow("名称:", self.name_edit)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/webhook")
        layout.addRow("URL:", self.url_edit)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["POST", "GET", "PUT"])
        layout.addRow("方法:", self.method_combo)

        self.headers_edit = QTextEdit()
        self.headers_edit.setPlaceholderText('可选，JSON格式，例如:\n{"Authorization": "Bearer token"}')
        self.headers_edit.setMaximumHeight(60)
        layout.addRow("Headers:", self.headers_edit)

        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText(
            '请求体模板，支持变量替换:\n'
            '{task_name} - 任务名称\n'
            '{status} - 执行状态 (success/failed)\n'
            '{exit_code} - 退出码\n'
            '{output} - 输出内容\n'
            '{error} - 错误信息\n'
            '{start_time} - 开始时间\n'
            '{end_time} - 结束时间\n'
            '{duration} - 执行时长(秒)\n'
            '{duration_str} - 执行时长(格式化)'
        )
        self.body_edit.setMaximumHeight(120)
        layout.addRow("Body模板:", self.body_edit)

        self.enabled_check = QCheckBox("启用")
        self.enabled_check.setChecked(True)
        layout.addRow("", self.enabled_check)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addRow(btn_layout)

    def _load_data(self):
        """加载数据"""
        self.name_edit.setText(self.webhook.name)
        self.url_edit.setText(self.webhook.url)
        self.method_combo.setCurrentText(self.webhook.method)
        if self.webhook.headers:
            import json
            self.headers_edit.setPlainText(json.dumps(self.webhook.headers, indent=2))
        self.body_edit.setPlainText(self.webhook.body_template)
        self.enabled_check.setChecked(self.webhook.enabled)

    def _save(self):
        """保存"""
        name = self.name_edit.text().strip()
        if not name:
            MsgBox.warning(self, "错误", "请输入名称")
            return

        url = self.url_edit.text().strip()
        if not url:
            MsgBox.warning(self, "错误", "请输入 URL")
            return

        # 解析 headers
        headers = {}
        headers_text = self.headers_edit.toPlainText().strip()
        if headers_text:
            try:
                import json
                headers = json.loads(headers_text)
            except json.JSONDecodeError:
                MsgBox.warning(self, "错误", "Headers 格式错误，请使用 JSON 格式")
                return

        self.webhook.name = name
        self.webhook.url = url
        self.webhook.method = self.method_combo.currentText()
        self.webhook.headers = headers
        self.webhook.body_template = self.body_edit.toPlainText()
        self.webhook.enabled = self.enabled_check.isChecked()

        self.accept()

    def get_webhook(self) -> WebhookConfig:
        """获取 Webhook 对象"""
        return self.webhook

