# -*- coding: utf-8 -*-
"""
后台同步任务进度对话框
用于查看正在后台运行的同步任务的进度
"""
import time
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QFrame
)
from PyQt5.QtCore import Qt, QTimer

from core.models import Task


class BackgroundSyncProgressDialog(QDialog):
    """后台同步任务进度对话框 - 连接到正在运行的后台同步任务"""

    def __init__(self, parent=None, task: Task = None, bg_manager=None):
        super().__init__(parent)
        self.task = task
        self.bg_manager = bg_manager
        self.start_time = time.time()
        self._last_output_len = 0
        
        # 进度数据
        self.processed_files = 0
        self.total_files = 0
        self.transferred_bytes = 0
        self.file_results = []  # [(action, file_path, success), ...]

        self.setWindowTitle(f"同步进度 - {task.name}")
        self.setMinimumSize(550, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._init_ui()
        self._load_existing_output()
        self._start_timer()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ===== 顶部：总体进度 =====
        progress_group = QGroupBox("同步进度")
        progress_layout = QVBoxLayout(progress_group)

        self.current_file_label = QLabel("后台运行中...")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("color: #666;")
        progress_layout.addWidget(self.current_file_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不确定模式
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(25)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # ===== 中部：统计信息 =====
        stats_group = QGroupBox("统计信息")
        stats_layout = QHBoxLayout(stats_group)

        left_stats = QVBoxLayout()
        self.files_label = QLabel("已处理: 0 文件")
        self.speed_label = QLabel("速度: -- /s")
        self.transferred_label = QLabel("已传输: 0 B")
        left_stats.addWidget(self.files_label)
        left_stats.addWidget(self.speed_label)
        left_stats.addWidget(self.transferred_label)
        stats_layout.addLayout(left_stats)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        stats_layout.addWidget(line)

        right_stats = QVBoxLayout()
        self.elapsed_label = QLabel("已用时间: 00:00")
        self.remaining_label = QLabel("剩余时间: --:--")
        self.status_label = QLabel("状态: 运行中")
        self.status_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        right_stats.addWidget(self.elapsed_label)
        right_stats.addWidget(self.remaining_label)
        right_stats.addWidget(self.status_label)
        stats_layout.addLayout(right_stats)

        layout.addWidget(stats_group)

        # ===== 底部：操作结果 =====
        result_group = QGroupBox("操作详情")
        result_layout = QVBoxLayout(result_group)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["操作", "文件", "状态"])
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setMaximumHeight(150)
        result_layout.addWidget(self.result_table)

        layout.addWidget(result_group)

        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.stop_btn = QPushButton("停止执行")
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.clicked.connect(self._stop_execution)
        btn_layout.addWidget(self.stop_btn)

        self.close_btn = QPushButton("关闭窗口")
        self.close_btn.setMinimumWidth(100)
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _load_existing_output(self):
        """加载已有的输出并解析进度"""
        if self.bg_manager:
            output = self.bg_manager.get_output(self.task.id)
            self._parse_output(output)
            self._last_output_len = len(output)

    def _start_timer(self):
        """启动更新定时器"""
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._refresh)
        self.update_timer.start(200)

    def _refresh(self):
        """刷新进度"""
        if not self.bg_manager:
            return

        # 检查任务状态
        is_running = self.bg_manager.is_running(self.task.id)

        # 获取新输出
        output = self.bg_manager.get_output(self.task.id)
        if len(output) > self._last_output_len:
            self._parse_output(output[self._last_output_len:])
            self._last_output_len = len(output)

        # 更新统计
        self._update_stats()

        # 更新状态
        if not is_running:
            self.update_timer.stop()
            self.status_label.setText("✓ 执行完成")
            self.status_label.setStyleSheet("font-weight: bold; color: #4ec9b0;")
            self.stop_btn.setEnabled(False)
            if self.total_files > 0:
                self.progress_bar.setRange(0, self.total_files)
                self.progress_bar.setValue(self.total_files)

    def _parse_output(self, output_list):
        """解析输出文本，提取进度信息"""
        import re
        for text, output_type in output_list:
            # 解析 [current/total] 格式的进度
            match = re.search(r'\[(\d+)/(\d+)\]\s*(.+)', text)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                file_info = match.group(3).strip()

                self.processed_files = current
                self.total_files = total
                self.current_file_label.setText(file_info)

                # 更新进度条
                if total > 0:
                    self.progress_bar.setRange(0, total)
                    self.progress_bar.setValue(current)
                    self.progress_bar.setFormat(f"%v / %m 文件 (%p%)")

                # 添加到结果表格
                action = "同步"
                if "复制" in file_info or "copy" in file_info.lower():
                    action = "复制"
                elif "更新" in file_info or "update" in file_info.lower():
                    action = "更新"
                elif "删除" in file_info or "delete" in file_info.lower():
                    action = "删除"

                self._add_result_row(action, file_info, True)

            # 解析发现文件数
            if "发现" in text and "文件需要同步" in text:
                match = re.search(r'发现\s*(\d+)\s*个文件', text)
                if match:
                    self.total_files = int(match.group(1))
                    if self.total_files > 0:
                        self.progress_bar.setRange(0, self.total_files)
                        self.progress_bar.setFormat(f"%v / %m 文件 (%p%)")

            # 解析完成信息
            if "同步完成" in text:
                self.current_file_label.setText("同步完成！")

    def _add_result_row(self, action: str, file_path: str, success: bool):
        """添加操作结果行"""
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)

        self.result_table.setItem(row, 0, QTableWidgetItem(action))
        self.result_table.setItem(row, 1, QTableWidgetItem(file_path))

        status_item = QTableWidgetItem("✓ 成功" if success else "✗ 失败")
        if success:
            status_item.setForeground(Qt.darkGreen)
        else:
            status_item.setForeground(Qt.red)
        self.result_table.setItem(row, 2, status_item)

        self.result_table.scrollToBottom()

    def _update_stats(self):
        """更新统计信息"""
        elapsed = time.time() - self.start_time

        # 已用时间
        self.elapsed_label.setText(f"已用时间: {self._format_time(elapsed)}")

        # 文件数
        if self.total_files > 0:
            self.files_label.setText(f"已处理: {self.processed_files} / {self.total_files} 文件")
        else:
            self.files_label.setText(f"已处理: {self.processed_files} 文件")

        # 剩余时间估算
        if self.processed_files > 0 and self.processed_files < self.total_files:
            avg_time = elapsed / self.processed_files
            remaining = avg_time * (self.total_files - self.processed_files)
            self.remaining_label.setText(f"剩余时间: {self._format_time(remaining)}")

    def _stop_execution(self):
        """停止执行"""
        from ui.message_box import MsgBox

        if MsgBox.question(self, "确认", "确定要停止同步任务吗？") == MsgBox.Yes:
            if self.bg_manager:
                self.bg_manager.stop_task(self.task.id)
                self.status_label.setText("正在停止...")
                self.stop_btn.setEnabled(False)

    def _format_time(self, seconds: float) -> str:
        """格式化时间"""
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins:02d}:{secs:02d}"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours:02d}:{mins:02d}:{secs:02d}"

    def closeEvent(self, event):
        """关闭事件"""
        self.update_timer.stop()
        event.accept()


