# -*- coding: utf-8 -*-
"""
清理任务配置对话框
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QTextEdit, QFileDialog,
    QGroupBox, QListWidget, QMessageBox, QWidget
)
from PyQt5.QtCore import Qt
from core.models import Task, CleanupConfig, TaskType
import os


class CleanupTaskDialog(QDialog):
    """清理任务配置对话框"""

    def __init__(self, task: Task = None, parent=None):
        super().__init__(parent)
        self.task = task or Task(task_type=TaskType.CLEANUP)
        self.is_new = (task is None)

        # 确保有清理配置
        if not self.task.cleanup_config:
            self.task.cleanup_config = CleanupConfig()

        self.setWindowTitle("清理任务配置" if self.is_new else f"编辑清理任务 - {self.task.name}")
        self.setMinimumWidth(600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._init_ui()
        self._load_data()

    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)

        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("任务名称")
        basic_layout.addRow("任务名称*:", self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("任务描述（可选）")
        basic_layout.addRow("描述:", self.desc_edit)

        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)

        # 定时设置组
        cron_group = QGroupBox("定时设置")
        cron_main_layout = QVBoxLayout(cron_group)

        # Cron 表达式输入
        cron_input_layout = QHBoxLayout()
        cron_input_layout.addWidget(QLabel("Cron 表达式:"))
        self.cron_edit = QLineEdit()
        self.cron_edit.setPlaceholderText("分 时 日 月 周 (例如: 0 2 * * * 每天凌晨2点)")
        self.cron_edit.setText("0 2 * * *")
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
            ("每小时", "0 * * * *"),
            ("每天凌晨2点", "0 2 * * *"),
            ("每天中午12点", "0 12 * * *"),
            ("每周一凌晨", "0 0 * * 1"),
            ("每月1号", "0 0 1 * *"),
        ]
        for label, cron in quick_btns:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=cron: self.cron_edit.setText(c))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        cron_main_layout.addLayout(quick_layout)

        layout.addWidget(cron_group)

        # 启用任务复选框
        self.enabled_checkbox = QCheckBox("启用任务")
        self.enabled_checkbox.setChecked(True)
        layout.addWidget(self.enabled_checkbox)

        # 清理配置组
        cleanup_group = QGroupBox("清理配置")
        cleanup_layout = QFormLayout()

        # 目标目录
        dir_layout = QHBoxLayout()
        self.target_dir_edit = QLineEdit()
        self.target_dir_edit.setPlaceholderText("选择要清理的目录")
        dir_layout.addWidget(self.target_dir_edit)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_directory)
        dir_layout.addWidget(browse_btn)

        cleanup_layout.addRow("目标目录*:", dir_layout)

        # 高阈值
        self.high_threshold_spin = QDoubleSpinBox()
        self.high_threshold_spin.setRange(0.1, 10000)
        self.high_threshold_spin.setValue(20.0)
        self.high_threshold_spin.setDecimals(2)
        self.high_threshold_spin.setSuffix(" GB")
        cleanup_layout.addRow("高阈值*:", self.high_threshold_spin)

        high_help = QLabel("超过此大小时开始清理")
        high_help.setStyleSheet("color: #666; font-size: 11px;")
        cleanup_layout.addRow("", high_help)

        # 低阈值
        self.low_threshold_spin = QDoubleSpinBox()
        self.low_threshold_spin.setRange(0.1, 10000)
        self.low_threshold_spin.setValue(10.0)
        self.low_threshold_spin.setDecimals(2)
        self.low_threshold_spin.setSuffix(" GB")
        cleanup_layout.addRow("低阈值*:", self.low_threshold_spin)

        low_help = QLabel("清理到此大小以下停止")
        low_help.setStyleSheet("color: #666; font-size: 11px;")
        cleanup_layout.addRow("", low_help)

        # 递归清理
        self.recursive_checkbox = QCheckBox("递归清理子目录")
        self.recursive_checkbox.setChecked(True)
        cleanup_layout.addRow("", self.recursive_checkbox)

        # 只删除文件
        self.files_only_checkbox = QCheckBox("只删除文件（保留空目录）")
        self.files_only_checkbox.setChecked(True)
        cleanup_layout.addRow("", self.files_only_checkbox)

        # 最小文件年龄
        self.min_age_spin = QSpinBox()
        self.min_age_spin.setRange(0, 3650)
        self.min_age_spin.setValue(0)
        self.min_age_spin.setSuffix(" 天")
        cleanup_layout.addRow("最小文件年龄:", self.min_age_spin)

        age_help = QLabel("只删除超过此天数的文件（0 = 不限制）")
        age_help.setStyleSheet("color: #666; font-size: 11px;")
        cleanup_layout.addRow("", age_help)

        cleanup_group.setLayout(cleanup_layout)
        layout.addWidget(cleanup_group)

        # 过滤选项组
        filter_group = QGroupBox("过滤选项（可选）")
        filter_layout = QVBoxLayout()

        # 文件扩展名过滤
        ext_label = QLabel("文件扩展名（留空表示所有文件）:")
        filter_layout.addWidget(ext_label)

        self.extensions_edit = QLineEdit()
        self.extensions_edit.setPlaceholderText("如: .log,.tmp,.bak（用逗号分隔）")
        filter_layout.addWidget(self.extensions_edit)

        # 排除模式
        exclude_label = QLabel("排除文件模式（支持通配符）:")
        filter_layout.addWidget(exclude_label)

        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText("如: *.keep,important_*（用逗号分隔）")
        filter_layout.addWidget(self.exclude_edit)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        test_btn = QPushButton("🔍 测试配置")
        test_btn.clicked.connect(self._test_config)
        btn_layout.addWidget(test_btn)

        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _browse_directory(self):
        """浏览选择目录"""
        directory = QFileDialog.getExistingDirectory(
            self, "选择要清理的目录",
            self.target_dir_edit.text() or os.path.expanduser("~")
        )
        if directory:
            self.target_dir_edit.setText(directory)

    def _load_data(self):
        """加载任务数据到界面"""
        self.name_edit.setText(self.task.name)
        self.desc_edit.setText(self.task.description)
        self.cron_edit.setText(self.task.cron_expression)
        self.enabled_checkbox.setChecked(self.task.enabled)

        # 加载清理配置
        config = self.task.cleanup_config
        if config:
            self.target_dir_edit.setText(config.target_dir)
            self.high_threshold_spin.setValue(config.high_threshold_gb)
            self.low_threshold_spin.setValue(config.low_threshold_gb)
            self.recursive_checkbox.setChecked(config.recursive)
            self.files_only_checkbox.setChecked(config.files_only)
            self.min_age_spin.setValue(config.min_age_days)

            # 文件扩展名
            if config.file_extensions:
                self.extensions_edit.setText(",".join(config.file_extensions))

            # 排除模式
            if config.exclude_patterns:
                self.exclude_edit.setText(",".join(config.exclude_patterns))

    def _save_data(self) -> bool:
        """保存界面数据到任务"""
        # 验证必填字段
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "验证失败", "请输入任务名称")
            return False

        if not self.target_dir_edit.text().strip():
            QMessageBox.warning(self, "验证失败", "请选择目标目录")
            return False

        target_dir = self.target_dir_edit.text().strip()
        if not os.path.exists(target_dir):
            QMessageBox.warning(self, "验证失败", f"目标目录不存在:\n{target_dir}")
            return False

        if not os.path.isdir(target_dir):
            QMessageBox.warning(self, "验证失败", f"目标路径不是目录:\n{target_dir}")
            return False

        # 验证阈值
        high_threshold = self.high_threshold_spin.value()
        low_threshold = self.low_threshold_spin.value()

        if low_threshold >= high_threshold:
            QMessageBox.warning(self, "验证失败", "低阈值必须小于高阈值")
            return False

        # 保存基本信息
        self.task.name = self.name_edit.text().strip()
        self.task.description = self.desc_edit.text().strip()
        self.task.cron_expression = self.cron_edit.text().strip()
        self.task.enabled = self.enabled_checkbox.isChecked()

        # 保存清理配置
        config = CleanupConfig()
        config.target_dir = target_dir
        config.high_threshold_gb = high_threshold
        config.low_threshold_gb = low_threshold
        config.recursive = self.recursive_checkbox.isChecked()
        config.files_only = self.files_only_checkbox.isChecked()
        config.min_age_days = self.min_age_spin.value()

        # 文件扩展名
        extensions_text = self.extensions_edit.text().strip()
        if extensions_text:
            config.file_extensions = [ext.strip() for ext in extensions_text.split(',') if ext.strip()]

        # 排除模式
        exclude_text = self.exclude_edit.text().strip()
        if exclude_text:
            config.exclude_patterns = [pattern.strip() for pattern in exclude_text.split(',') if pattern.strip()]

        self.task.cleanup_config = config
        return True

    def _test_config(self):
        """测试配置（显示当前目录大小和预计清理情况）"""
        target_dir = self.target_dir_edit.text().strip()

        if not target_dir or not os.path.exists(target_dir):
            QMessageBox.warning(self, "测试失败", "请先选择有效的目标目录")
            return

        from core.cleanup_executor import CleanupExecutor

        try:
            executor = CleanupExecutor()

            # 计算当前目录大小
            recursive = self.recursive_checkbox.isChecked()
            current_size = executor._calculate_directory_size(target_dir, recursive)
            current_gb = current_size / (1024**3)

            high_threshold = self.high_threshold_spin.value()
            low_threshold = self.low_threshold_spin.value()

            # 显示结果
            result_text = f"当前目录大小: {current_gb:.2f} GB\n\n"
            result_text += f"高阈值: {high_threshold} GB\n"
            result_text += f"低阈值: {low_threshold} GB\n\n"

            if current_gb > high_threshold:
                need_delete = current_gb - low_threshold
                result_text += f"⚠️ 已超过高阈值\n"
                result_text += f"需要清理: 约 {need_delete:.2f} GB\n"
            else:
                remain = high_threshold - current_gb
                result_text += f"✓ 未达到高阈值\n"
                result_text += f"剩余空间: 约 {remain:.2f} GB\n"

            QMessageBox.information(self, "配置测试", result_text)

        except Exception as e:
            QMessageBox.critical(self, "测试失败", f"测试配置时出错:\n{str(e)}")

    def accept(self):
        """确认按钮"""
        if self._save_data():
            super().accept()

    def get_task(self) -> Task:
        """获取任务对象"""
        return self.task

    def _select_hours(self, hours):
        """选择指定小时"""
        for i, cb in enumerate(self.hour_checkboxes):
            cb.setChecked(i in hours)

    def _update_cron_from_hours(self):
        """根据选择的小时更新 Cron 表达式"""
        selected_hours = []
        for i, cb in enumerate(self.hour_checkboxes):
            if cb.isChecked():
                selected_hours.append(i)

        if not selected_hours:
            return

        minute = self.hours_minute_spin.value()

        # 生成小时部分
        if len(selected_hours) == 24:
            hour_part = "*"
        elif len(selected_hours) == 1:
            hour_part = str(selected_hours[0])
        else:
            # 检查是否连续
            is_continuous = all(
                selected_hours[i] + 1 == selected_hours[i + 1]
                for i in range(len(selected_hours) - 1)
            )
            if is_continuous and len(selected_hours) > 2:
                hour_part = f"{selected_hours[0]}-{selected_hours[-1]}"
            else:
                hour_part = ",".join(map(str, selected_hours))

        # 生成 Cron 表达式
        cron_expr = f"{minute} {hour_part} * * *"
        self.cron_edit.setText(cron_expr)


