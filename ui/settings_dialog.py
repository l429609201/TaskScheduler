# -*- coding: utf-8 -*-
"""
设置对话框
"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QCheckBox, QPushButton, QGroupBox,
    QSpinBox, QFileDialog, QLabel, QComboBox, QWidget
)
from PyQt5.QtCore import Qt

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
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        
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

        # 启动设置组
        startup_group = QGroupBox("启动设置")
        startup_layout = QFormLayout(startup_group)

        # 开机启动
        startup_widget = QWidget()
        startup_h_layout = QHBoxLayout(startup_widget)
        startup_h_layout.setContentsMargins(0, 0, 0, 0)

        self.startup_check = QCheckBox("开机时自动启动程序")
        self.startup_check.setToolTip("登录 Windows 后自动启动任务调度器（带托盘图标）")
        startup_h_layout.addWidget(self.startup_check)

        startup_h_layout.addStretch()

        startup_layout.addRow("", startup_widget)

        # 启动状态提示
        self.startup_status_label = QLabel()
        self.startup_status_label.setStyleSheet("color: gray; font-size: 11px;")
        startup_layout.addRow("", self.startup_status_label)

        layout.addWidget(startup_group)

        layout.addStretch()
        
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
    
    def _load_settings(self):
        """加载设置"""
        self.log_enabled_check.setChecked(self.settings.log_enabled)
        self.log_dir_edit.setText(self.settings.log_dir)
        self.retention_spin.setValue(self.settings.log_retention_days)

        # 关闭行为
        index = self.close_action_combo.findData(self.settings.close_action)
        if index >= 0:
            self.close_action_combo.setCurrentIndex(index)

        # 开机启动状态
        from service.installer import StartupManager
        is_startup = StartupManager.is_enabled()
        self.startup_check.setChecked(is_startup)
        self._update_startup_status(is_startup)

        self._update_log_info()
        self._on_log_enabled_changed()

    def _update_startup_status(self, enabled: bool):
        """更新开机启动状态显示"""
        if enabled:
            self.startup_status_label.setText("✓ 已设置开机启动")
            self.startup_status_label.setStyleSheet("color: #4ec9b0; font-size: 11px;")
        else:
            self.startup_status_label.setText("未设置开机启动")
            self.startup_status_label.setStyleSheet("color: gray; font-size: 11px;")
    
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
        
        log_dir = self.log_dir_edit.text() or "logs"
        days = self.retention_spin.value()
        
        if MsgBox.question(self, "确认清理", f"确定要清理 {days} 天前的日志吗？"):
            logger = TaskLogger(log_dir=log_dir)
            logger.clear_old_logs(days)
            self._update_log_info()
            MsgBox.information(self, "完成", "旧日志已清理")
    
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

        # 处理开机启动设置
        from service.installer import StartupManager
        current_startup = StartupManager.is_enabled()
        want_startup = self.startup_check.isChecked()

        if want_startup != current_startup:
            if want_startup:
                success, msg = StartupManager.enable()
            else:
                success, msg = StartupManager.disable()

            if not success:
                MsgBox.warning(self, "开机启动设置", msg)

        self.settings_changed = True
        self.accept()
    
    def get_settings(self) -> AppSettings:
        """获取设置"""
        return self.settings

