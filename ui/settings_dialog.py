# -*- coding: utf-8 -*-
"""
设置对话框
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QCheckBox, QPushButton, QGroupBox,
    QSpinBox, QFileDialog, QLabel, QComboBox, QWidget,
    QTabWidget, QTextBrowser
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from core.models import AppSettings, SettingsStorage
from .message_box import MsgBox


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.settings = settings or AppSettings()
        self.settings_changed = False

        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("设置")
        self.setMinimumWidth(550)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        # 创建标签页
        self.tab_widget = QTabWidget()

        # 1. 常规设置页
        general_tab = self._create_general_tab()
        self.tab_widget.addTab(general_tab, "常规设置")

        # 2. 开机启动页
        service_tab = self._create_service_tab()
        self.tab_widget.addTab(service_tab, "开机启动")

        # 3. 关于页
        about_tab = self._create_about_tab()
        self.tab_widget.addTab(about_tab, "关于")

        layout.addWidget(self.tab_widget)

        # 底部按钮（只在常规设置页显示）
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()

        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._save)
        self.btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        self.btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(self.btn_layout)

        # 标签页切换时更新按钮显示
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    def _create_general_tab(self):
        """创建常规设置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 日志设置组
        log_group = QGroupBox("执行日志设置")
        log_layout = QFormLayout(log_group)

        # 启用日志开关
        self.log_enabled_check = QCheckBox("启用执行日志记录")
        self.log_enabled_check.setToolTip("开启后，每次任务执行的结果都会保存到日志文件")
        self.log_enabled_check.stateChanged.connect(self._on_log_enabled_changed)
        log_layout.addRow("", self.log_enabled_check)

        # 日志目录
        log_dir_widget = QWidget()
        log_dir_layout = QHBoxLayout(log_dir_widget)
        log_dir_layout.setContentsMargins(0, 0, 0, 0)

        self.log_dir_edit = QLineEdit()
        self.log_dir_edit.setPlaceholderText("日志保存目录（默认: logs）")
        log_dir_layout.addWidget(self.log_dir_edit)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_log_dir)
        log_dir_layout.addWidget(browse_btn)

        log_layout.addRow("日志目录:", log_dir_widget)

        # 日志保留天数
        retention_widget = QWidget()
        retention_layout = QHBoxLayout(retention_widget)
        retention_layout.setContentsMargins(0, 0, 0, 0)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setValue(30)
        self.retention_spin.setSuffix(" 天")
        retention_layout.addWidget(self.retention_spin)

        retention_layout.addStretch()

        clear_btn = QPushButton("立即清理旧日志")
        clear_btn.clicked.connect(self._clear_old_logs)
        retention_layout.addWidget(clear_btn)

        log_layout.addRow("日志保留:", retention_widget)

        # 日志目录信息
        self.log_info_label = QLabel()
        self.log_info_label.setStyleSheet("color: gray; font-size: 11px;")
        log_layout.addRow("", self.log_info_label)

        layout.addWidget(log_group)

        # 打开日志目录按钮
        open_log_btn = QPushButton("打开日志目录")
        open_log_btn.clicked.connect(self._open_log_dir)
        layout.addWidget(open_log_btn)

        # 窗口行为设置组
        behavior_group = QGroupBox("窗口行为")
        behavior_layout = QFormLayout(behavior_group)

        # 关闭按钮行为
        self.close_action_combo = QComboBox()
        self.close_action_combo.addItem("最小化到系统托盘", "minimize")
        self.close_action_combo.addItem("直接退出程序", "exit")
        self.close_action_combo.setToolTip("设置点击窗口关闭按钮时的行为")
        behavior_layout.addRow("关闭窗口时:", self.close_action_combo)

        layout.addWidget(behavior_group)

        layout.addStretch()

        return tab

    def _create_service_tab(self):
        """创建开机启动管理标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 说明
        info_label = QLabel(
            "使用 Windows 任务计划程序实现开机自动启动。\n"
            "这是比传统 Windows 服务更简单、更可靠的方案。\n"
            "程序将在系统启动30秒后自动运行（无需用户登录）。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
        layout.addWidget(info_label)

        # 状态组
        status_group = QGroupBox("开机启动状态")
        status_layout = QVBoxLayout(status_group)

        self.service_status_label = QLabel("正在检查...")
        self.service_status_label.setStyleSheet("font-size: 13px; padding: 5px;")
        status_layout.addWidget(self.service_status_label)

        layout.addWidget(status_group)

        # 操作组
        action_group = QGroupBox("操作")
        action_layout = QVBoxLayout(action_group)

        # 创建开机启动按钮
        install_btn = QPushButton("✓ 启用开机自动启动")
        install_btn.setToolTip("创建开机启动任务（30秒延迟启动）")
        install_btn.clicked.connect(self._install_service)
        action_layout.addWidget(install_btn)

        # 删除开机启动按钮
        uninstall_btn = QPushButton("✗ 禁用开机自动启动")
        uninstall_btn.setToolTip("删除开机启动任务")
        uninstall_btn.clicked.connect(self._uninstall_service)
        action_layout.addWidget(uninstall_btn)

        # 立即运行按钮
        start_btn = QPushButton("⚡ 立即运行一次")
        start_btn.setToolTip("立即运行程序（测试用）")
        start_btn.clicked.connect(self._start_service)
        action_layout.addWidget(start_btn)

        # 刷新状态按钮
        refresh_btn = QPushButton("🔄 刷新状态")
        refresh_btn.clicked.connect(self._refresh_service_status)
        action_layout.addWidget(refresh_btn)

        layout.addWidget(action_group)

        layout.addStretch()

        # 初始化时刷新状态
        self._refresh_service_status()

        return tab

    def _create_about_tab(self):
        """创建关于标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 使用 QTextBrowser 显示富文本
        about_browser = QTextBrowser()
        about_browser.setOpenExternalLinks(True)
        about_browser.setStyleSheet("""
            QTextBrowser {
                border: none;
                background: transparent;
            }
        """)

        about_html = """
        <div style='padding: 20px;'>
            <h2 style='color: #2c3e50; margin-bottom: 10px;'>任务调度器 Task Scheduler</h2>
            <p style='color: #7f8c8d; font-size: 12px; margin-bottom: 20px;'>版本 1.0.0</p>

            <h3 style='color: #34495e; margin-top: 20px;'>功能特性</h3>
            <ul style='color: #555; line-height: 1.8;'>
                <li>✓ 支持 Cron 表达式定时任务</li>
                <li>✓ 文件同步（FTP/SFTP/本地）</li>
                <li>✓ 命令执行与批处理</li>
                <li>✓ Webhook 通知（钉钉/企业微信等）</li>
                <li>✓ 输出解析器（正则/JSON/XML）</li>
                <li>✓ Windows 开机启动（任务计划程序）</li>
                <li>✓ 系统托盘运行</li>
            </ul>

            <h3 style='color: #34495e; margin-top: 20px;'>开发信息</h3>
            <p style='color: #555; line-height: 1.8;'>
                <strong>开发者：</strong>您的名字<br>
                <strong>技术栈：</strong>Python 3.x + PyQt5 + APScheduler<br>
                <strong>开发时间：</strong>2026年1月<br>
            </p>

            <h3 style='color: #34495e; margin-top: 20px;'>使用说明</h3>
            <p style='color: #555; line-height: 1.8;'>
                1. <strong>创建任务：</strong>点击"新建任务"按钮，选择任务类型（命令/同步）<br>
                2. <strong>配置定时：</strong>使用 Cron 表达式或可视化小时选择器<br>
                3. <strong>设置通知：</strong>在 Webhook 页面配置通知渠道<br>
                4. <strong>启用任务：</strong>勾选任务的"启用"复选框<br>
                5. <strong>查看日志：</strong>右键任务选择"查看日志"<br>
            </p>

            <h3 style='color: #34495e; margin-top: 20px;'>技术支持</h3>
            <p style='color: #555; line-height: 1.8;'>
                如有问题或建议，请联系开发者。<br>
                <br>
                <em style='color: #95a5a6; font-size: 11px;'>
                    本软件基于 MIT 许可证开源
                </em>
            </p>
        </div>
        """

        about_browser.setHtml(about_html)
        layout.addWidget(about_browser)

        return tab

    def _on_tab_changed(self, index):
        """标签页切换时的处理"""
        # 只在常规设置页显示保存/取消按钮
        show_buttons = (index == 0)
        self.save_btn.setVisible(show_buttons)
        self.cancel_btn.setVisible(show_buttons)

    def _refresh_service_status(self):
        """刷新开机启动状态"""
        try:
            from utils.task_scheduler_manager import TaskSchedulerManager
            manager = TaskSchedulerManager()
            success, msg, info = manager.get_task_status()

            if success:
                state = info.get('state', 0)
                enabled = info.get('enabled', False)

                if enabled and state in [3, 4]:  # 就绪或运行中
                    status_text = "✓ 开机启动已启用"
                    color = "#4ec9b0"
                elif enabled:
                    status_text = "✓ 开机启动已启用（等待触发）"
                    color = "#ce9178"
                else:
                    status_text = "⚠ 开机启动已创建但被禁用"
                    color = "#ce9178"
            else:
                status_text = "✗ 开机启动未启用"
                color = "#f48771"

            self.service_status_label.setText(f"<b>{status_text}</b><br><span style='font-size: 11px; color: #666;'>{msg}</span>")
            self.service_status_label.setStyleSheet(f"color: {color}; font-size: 13px; padding: 5px;")
        except Exception as e:
            self.service_status_label.setText(f"<b>✗ 状态检查失败</b><br><span style='font-size: 11px; color: #666;'>错误: {str(e)}</span>")
            self.service_status_label.setStyleSheet(f"color: #f48771; font-size: 13px; padding: 5px;")

    def _install_service(self):
        """启用开机自动启动"""
        if not MsgBox.question(self, "启用开机启动", "确定要启用开机自动启动吗？\n程序将在系统启动30秒后自动运行（无需用户登录）。"):
            return

        try:
            from utils.task_scheduler_manager import TaskSchedulerManager
            manager = TaskSchedulerManager()
            success, msg = manager.create_startup_task()

            if success:
                MsgBox.information(self, "操作成功", msg)
            else:
                MsgBox.warning(self, "操作失败", msg)
        except Exception as e:
            MsgBox.warning(self, "操作失败", f"发生异常: {str(e)}")

        self._refresh_service_status()

    def _uninstall_service(self):
        """禁用开机自动启动"""
        if not MsgBox.question(self, "禁用开机启动", "确定要禁用开机自动启动吗？"):
            return

        try:
            from utils.task_scheduler_manager import TaskSchedulerManager
            manager = TaskSchedulerManager()
            success, msg = manager.delete_task()

            if success:
                MsgBox.information(self, "操作成功", msg)
            else:
                MsgBox.warning(self, "操作失败", msg)
        except Exception as e:
            MsgBox.warning(self, "操作失败", f"发生异常: {str(e)}")

        self._refresh_service_status()

    def _start_service(self):
        """立即运行一次（测试用）"""
        if not MsgBox.question(self, "立即运行", "这将立即启动程序一次（用于测试）。\n确定要执行吗？"):
            return

        try:
            from utils.task_scheduler_manager import TaskSchedulerManager
            manager = TaskSchedulerManager()
            success, msg = manager.run_task_now()

            if success:
                MsgBox.information(self, "操作成功", msg)
            else:
                MsgBox.warning(self, "操作失败", msg)
        except Exception as e:
            MsgBox.warning(self, "操作失败", f"发生异常: {str(e)}")

        self._refresh_service_status()

    def _load_settings(self):
        """加载设置"""
        self.log_enabled_check.setChecked(self.settings.log_enabled)
        self.log_dir_edit.setText(self.settings.log_dir)
        self.retention_spin.setValue(self.settings.log_retention_days)

        # 关闭行为
        index = self.close_action_combo.findData(self.settings.close_action)
        if index >= 0:
            self.close_action_combo.setCurrentIndex(index)

        self._update_log_info()
        self._on_log_enabled_changed()

    def _on_log_enabled_changed(self):
        """日志启用状态改变"""
        enabled = self.log_enabled_check.isChecked()
        self.log_dir_edit.setEnabled(enabled)
        self.retention_spin.setEnabled(enabled)
    
    def _browse_log_dir(self):
        """浏览选择日志目录"""
        current = self.log_dir_edit.text() or "logs"
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择日志目录", current
        )
        if dir_path:
            self.log_dir_edit.setText(dir_path)
            self._update_log_info()
    
    def _update_log_info(self):
        """更新日志目录信息"""
        log_dir = self.log_dir_edit.text() or "logs"
        if os.path.exists(log_dir):
            files = [f for f in os.listdir(log_dir) if f.endswith('.log')]
            total_size = sum(os.path.getsize(os.path.join(log_dir, f)) for f in files)
            size_str = self._format_size(total_size)
            self.log_info_label.setText(f"当前日志: {len(files)} 个文件, 共 {size_str}")
        else:
            self.log_info_label.setText("日志目录尚未创建")
    
    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / 1024 / 1024:.1f} MB"
    
    def _clear_old_logs(self):
        """清理旧日志"""
        from core.logger import TaskLogger
        import time

        log_dir = self.log_dir_edit.text() or "logs"
        days = self.retention_spin.value()

        if not os.path.exists(log_dir):
            MsgBox.information(self, "提示", "日志目录不存在，无需清理")
            return

        if not MsgBox.question(self, "确认清理", f"确定要清理 {days} 天前的日志吗？"):
            return

        # 统计要删除的文件
        now = time.time()
        cutoff = now - (days * 86400)
        files_to_delete = []

        for f in os.listdir(log_dir):
            if f.endswith('.log'):
                filepath = os.path.join(log_dir, f)
                if os.path.getmtime(filepath) < cutoff:
                    files_to_delete.append(filepath)

        if not files_to_delete:
            MsgBox.information(self, "完成", f"没有找到 {days} 天前的日志文件")
            return

        # 删除文件
        deleted_count = 0
        failed_count = 0

        for filepath in files_to_delete:
            try:
                os.remove(filepath)
                deleted_count += 1
            except OSError as e:
                failed_count += 1
                print(f"删除日志失败: {filepath}, 错误: {e}")

        # 更新显示
        self._update_log_info()

        # 显示结果
        if failed_count == 0:
            MsgBox.information(self, "完成", f"成功清理 {deleted_count} 个旧日志文件")
        else:
            MsgBox.warning(self, "部分成功", f"成功清理 {deleted_count} 个文件\n失败 {failed_count} 个文件")
    
    def _open_log_dir(self):
        """打开日志目录"""
        log_dir = self.log_dir_edit.text() or "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 使用系统默认方式打开目录
        import subprocess
        import sys
        if sys.platform == 'win32':
            os.startfile(log_dir)
        elif sys.platform == 'darwin':
            subprocess.run(['open', log_dir])
        else:
            subprocess.run(['xdg-open', log_dir])
    
    def _save(self):
        """保存设置"""
        self.settings.log_enabled = self.log_enabled_check.isChecked()
        self.settings.log_dir = self.log_dir_edit.text() or "logs"
        self.settings.log_retention_days = self.retention_spin.value()
        self.settings.close_action = self.close_action_combo.currentData()

        self.settings_changed = True
        self.accept()
    
    def get_settings(self) -> AppSettings:
        """获取设置"""
        return self.settings

