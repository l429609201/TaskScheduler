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
from PyQt5.QtGui import QColor

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

        # 文件列表：{file_path: (action, row_index, status)}
        self._file_map = {}
        self._parsing_file_list = False

        self.setWindowTitle(f"同步进度 - {task.name}")
        self.setMinimumSize(550, 450)
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
        # 不设置最大高度，让表格可以扩展
        result_layout.addWidget(self.result_table)

        layout.addWidget(result_group, 1)  # stretch factor = 1，让表格占据剩余空间

        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

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

        # 更新进度条
        if self.total_files > 0:
            self.progress_bar.setRange(0, self.total_files)
            self.progress_bar.setValue(self.processed_files)
            self.progress_bar.setFormat(f"%v / %m 文件 (%p%)")

        # 更新统计
        self._update_stats()

        # 更新状态
        if not is_running:
            self.update_timer.stop()
            self.status_label.setText("✓ 执行完成")
            self.status_label.setStyleSheet("font-weight: bold; color: #4ec9b0;")
            if self.total_files > 0:
                self.progress_bar.setValue(self.processed_files)

    def _parse_output(self, output_list):
        """解析输出文本，提取进度信息"""
        import re
        for text, output_type in output_list:
            text = text.strip()

            # 解析任务开始信息
            if "开始执行同步任务:" in text:
                self.current_file_label.setText("任务已开始...")
                self.status_label.setText("状态: 正在执行")
                continue

            # 解析正在比较文件
            if "正在比较文件" in text:
                self.current_file_label.setText("正在比较文件...")
                continue

            # 解析文件列表开始标记
            if "===FILE_LIST_START===" in text:
                self._parsing_file_list = True
                continue

            # 解析文件列表结束标记
            if "===FILE_LIST_END===" in text:
                self._parsing_file_list = False
                continue

            # 解析文件列表项: FILE:操作:文件路径
            if self._parsing_file_list and text.startswith("FILE:"):
                parts = text.split(":", 2)
                if len(parts) >= 3:
                    action = parts[1]
                    file_path = parts[2]
                    # 根据操作类型设置初始状态
                    if action in ["无需同步", "跳过"]:
                        self._add_file_row(action, file_path, "✓ 已跳过")
                    elif action == "冲突":
                        self._add_file_row(action, file_path, "⚠ 冲突")
                    else:
                        # 需要同步的文件
                        self._add_file_row(action, file_path, "等待中")
                continue

            # 解析文件完成: DONE:SUCCESS/FAILED:操作:文件路径:字节数
            if text.startswith("DONE:"):
                parts = text.split(":", 4)
                if len(parts) >= 4:
                    status = parts[1]  # SUCCESS or FAILED
                    action = parts[2]
                    file_path = parts[3]
                    # 解析字节数（如果有）
                    if len(parts) >= 5:
                        try:
                            bytes_transferred = int(parts[4])
                            self.transferred_bytes += bytes_transferred
                        except:
                            pass
                    success = (status == "SUCCESS")
                    self._update_file_status(file_path, success)
                    self.processed_files += 1
                continue

            # 解析 [current/total] 格式的进度，包含 BYTES:xxx
            match = re.search(r'\[(\d+)/(\d+)\]\s*(.+?)(?:\s+BYTES:(\d+))?$', text)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                file_info = match.group(3).strip()
                bytes_str = match.group(4)

                self.total_files = total
                self.current_file_label.setText(file_info)

                # 更新传输字节数（实时）
                if bytes_str:
                    try:
                        self.transferred_bytes = int(bytes_str)
                    except:
                        pass

                # 从 file_info 中提取文件路径，设置为传输中
                # 格式: "处理: path" 或 "传输: path (xx%)"
                if file_info.startswith("处理:") or file_info.startswith("传输:"):
                    # 提取文件路径
                    path_match = re.match(r'(?:处理|传输):\s*(.+?)(?:\s*\(\d+%\))?$', file_info)
                    if path_match:
                        file_path = path_match.group(1).strip()
                        self._set_file_transferring(file_path)

                # 更新进度条
                if total > 0:
                    self.progress_bar.setRange(0, total)
                    self.progress_bar.setValue(current)
                    self.progress_bar.setFormat(f"%v / %m 文件 (%p%)")
                continue

            # 解析发现文件数
            if "发现" in text and "文件需要同步" in text:
                match = re.search(r'发现\s*(\d+)\s*个文件', text)
                if match:
                    self.total_files = int(match.group(1))
                    if self.total_files > 0:
                        self.progress_bar.setRange(0, self.total_files)
                        self.progress_bar.setFormat(f"%v / %m 文件 (%p%)")

            # 解析无需同步
            if "所有文件已是最新" in text or "无需同步" in text:
                self.current_file_label.setText("所有文件已是最新，无需同步")

            # 解析完成信息
            if "同步完成" in text:
                self.current_file_label.setText("同步完成！")

    def _add_file_row(self, action: str, file_path: str, status: str):
        """添加文件行到表格"""
        # 检查是否已存在
        if file_path in self._file_map:
            return

        row = self.result_table.rowCount()
        self.result_table.insertRow(row)

        self.result_table.setItem(row, 0, QTableWidgetItem(action))
        self.result_table.setItem(row, 1, QTableWidgetItem(file_path))

        status_item = QTableWidgetItem(status)
        if status == "等待中":
            status_item.setForeground(Qt.gray)
        elif status == "✓ 已跳过":
            status_item.setForeground(QColor("#888888"))  # 灰色
        elif status == "⚠ 冲突":
            status_item.setForeground(QColor("#ff9800"))  # 橙色
        self.result_table.setItem(row, 2, status_item)

        # 记录文件位置
        self._file_map[file_path] = (action, row, status)

        # 只有需要同步的文件才计入 total_files
        # "无需同步"、"跳过"、"冲突" 不计入需要处理的数量
        if action not in ["无需同步", "跳过", "冲突"]:
            # 重新计算需要处理的文件数量
            self.total_files = len([k for k, v in self._file_map.items()
                                   if v[0] not in ["无需同步", "跳过", "冲突"]])

    def _set_file_transferring(self, file_path: str):
        """设置文件为传输中状态"""
        if file_path not in self._file_map:
            return

        action, row, current_status = self._file_map[file_path]
        # 只有等待中的文件才更新为传输中
        if current_status != "等待中":
            return

        status_item = self.result_table.item(row, 2)
        if status_item:
            status_item.setText("⏳ 传输中...")
            status_item.setForeground(QColor("#0078d4"))  # 蓝色

        self._file_map[file_path] = (action, row, "传输中")

        # 滚动到当前行
        self.result_table.scrollToItem(status_item)

    def _update_file_status(self, file_path: str, success: bool):
        """更新文件状态为完成或失败"""
        if file_path not in self._file_map:
            return

        action, row, _ = self._file_map[file_path]
        status = "✓ 完成" if success else "✗ 失败"

        status_item = self.result_table.item(row, 2)
        if status_item:
            status_item.setText(status)
            if success:
                status_item.setForeground(Qt.darkGreen)
            else:
                status_item.setForeground(Qt.red)

        self._file_map[file_path] = (action, row, status)

        # 滚动到当前行
        self.result_table.scrollToItem(status_item)

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

        # 传输大小
        self.transferred_label.setText(f"已传输: {self._format_size(self.transferred_bytes)}")

        # 传输速度
        if elapsed > 0 and self.transferred_bytes > 0:
            speed = self.transferred_bytes / elapsed
            self.speed_label.setText(f"速度: {self._format_size(speed)}/s")
        else:
            self.speed_label.setText("速度: -- /s")

        # 剩余时间估算
        if self.processed_files > 0 and self.processed_files < self.total_files:
            avg_time = elapsed / self.processed_files
            remaining = avg_time * (self.total_files - self.processed_files)
            self.remaining_label.setText(f"剩余时间: {self._format_time(remaining)}")

    def _format_size(self, size: float) -> str:
        """格式化文件大小"""
        if size < 1024:
            return f"{size:.0f} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

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


