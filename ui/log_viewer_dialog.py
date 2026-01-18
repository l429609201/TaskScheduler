# -*- coding: utf-8 -*-
"""
任务执行日志查看对话框
"""
import os
import re
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QTextEdit, QLabel,
    QPushButton, QFileDialog, QLineEdit, QCheckBox, QFrame,
    QComboBox, QDateEdit, QGroupBox, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, QDate, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QColor

from core.logger import TaskLogger
from .message_box import MsgBox


class LogFileLoader(QThread):
    """异步加载日志文件列表的工作线程"""

    # 信号：加载进度 (当前数量, 总数量)
    progress = pyqtSignal(int, int)
    # 信号：加载完成 (文件列表)
    finished = pyqtSignal(list)
    # 信号：加载错误
    error = pyqtSignal(str)

    def __init__(self, log_dir: str, task_name: str):
        super().__init__()
        self.log_dir = log_dir
        self.task_name = task_name
        self._is_cancelled = False

    def cancel(self):
        """取消加载"""
        self._is_cancelled = True

    def run(self):
        """执行加载"""
        try:
            # 清理任务名用于匹配文件
            safe_name = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in self.task_name)
            safe_name = safe_name.strip().replace(' ', '_')
            prefix = safe_name + '_'

            if not os.path.exists(self.log_dir):
                self.finished.emit([])
                return

            files = []
            count = 0

            # 使用 scandir 扫描文件
            with os.scandir(self.log_dir) as entries:
                for entry in entries:
                    # 检查是否取消
                    if self._is_cancelled:
                        return

                    # 快速过滤
                    if not entry.is_file() or not entry.name.endswith('.log'):
                        continue
                    if not entry.name.startswith(prefix):
                        continue

                    try:
                        stat_info = entry.stat()
                        mtime = stat_info.st_mtime
                        display_time = self._parse_display_time(entry.name, mtime)
                        files.append((entry.name, entry.path, mtime, display_time))

                        count += 1
                        # 每10个文件更新一次进度
                        if count % 10 == 0:
                            self.progress.emit(count, -1)
                    except (OSError, ValueError):
                        continue

            # 检查是否取消
            if self._is_cancelled:
                return

            # 按时间倒序排序
            files.sort(key=lambda x: x[2], reverse=True)

            # 发送完成信号
            self.finished.emit(files)

        except Exception as e:
            self.error.emit(str(e))

    def _parse_display_time(self, filename: str, mtime: float) -> str:
        """解析文件名中的时间"""
        try:
            name_without_ext = filename[:-4]
            parts = name_without_ext.rsplit('_', 2)

            if len(parts) >= 3:
                date_str = parts[-2]
                time_str = parts[-1]

                if len(date_str) == 8 and len(time_str) == 6:
                    if date_str.isdigit() and time_str.isdigit():
                        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
        except (IndexError, ValueError):
            pass

        return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')


class LogViewerDialog(QDialog):
    """日志查看对话框"""

    def __init__(self, parent=None, task_name: str = "", log_dir: str = "logs"):
        super().__init__(parent)
        self.task_name = task_name
        self.log_dir = log_dir
        self.task_logger = TaskLogger(log_dir=log_dir)

        # 搜索相关状态
        self._search_matches = []  # 存储所有匹配位置
        self._current_match_index = -1  # 当前高亮的匹配索引
        self._original_content = ""  # 原始日志内容

        # 所有日志文件（用于过滤）
        self._all_log_files = []  # [(filename, filepath, mtime, display_time), ...]

        # 筛选去抖动定时器
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._do_apply_filters)

        # 加载线程
        self._loader_thread = None
        self._is_loading = False

        self._init_ui()
        self._start_async_load()

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle(f"执行日志 - {self.task_name}")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)

        # 使用分割器
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：日志文件列表
        left_w = QWidget()
        left_layout = QVBoxLayout(left_w)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 过滤区域
        filter_group = QGroupBox("筛选条件")
        filter_layout = QVBoxLayout()
        filter_layout.setSpacing(8)

        # 文件名搜索
        filename_layout = QHBoxLayout()
        filename_layout.addWidget(QLabel("文件名:"))
        self.filename_filter = QLineEdit()
        self.filename_filter.setPlaceholderText("搜索文件名...")
        # 使用去抖动定时器，减少频繁触发
        self.filename_filter.textChanged.connect(self._apply_filters_debounced)
        filename_layout.addWidget(self.filename_filter)
        filter_layout.addLayout(filename_layout)

        # 时间范围筛选
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("时间范围:"))
        self.time_range_combo = QComboBox()
        self.time_range_combo.addItems([
            "全部时间",
            "最近1小时",
            "最近24小时",
            "最近3天",
            "最近7天",
            "最近30天",
            "自定义范围"
        ])
        self.time_range_combo.currentIndexChanged.connect(self._on_time_range_changed)
        time_layout.addWidget(self.time_range_combo, 1)
        filter_layout.addLayout(time_layout)

        # 自定义日期范围（默认隐藏）
        self.custom_date_widget = QWidget()
        custom_date_layout = QVBoxLayout(self.custom_date_widget)
        custom_date_layout.setContentsMargins(0, 0, 0, 0)
        custom_date_layout.setSpacing(4)

        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("开始:"))
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate().addDays(-7))
        self.start_date.dateChanged.connect(self._apply_filters)
        start_layout.addWidget(self.start_date)
        custom_date_layout.addLayout(start_layout)

        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("结束:"))
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())
        self.end_date.dateChanged.connect(self._apply_filters)
        end_layout.addWidget(self.end_date)
        custom_date_layout.addLayout(end_layout)

        self.custom_date_widget.hide()
        filter_layout.addWidget(self.custom_date_widget)

        # 清除筛选按钮
        clear_filter_btn = QPushButton("清除筛选")
        clear_filter_btn.clicked.connect(self._clear_filters)
        filter_layout.addWidget(clear_filter_btn)

        filter_group.setLayout(filter_layout)
        left_layout.addWidget(filter_group)

        # 日志列表
        list_label = QLabel("执行记录:")
        left_layout.addWidget(list_label)

        # 加载状态标签
        self.loading_label = QLabel("正在加载日志文件...")
        self.loading_label.setStyleSheet("color: #1976d2; padding: 5px;")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.hide()  # 默认隐藏
        left_layout.addWidget(self.loading_label)

        self.log_list = QListWidget()
        self.log_list.setMinimumWidth(250)
        self.log_list.setMaximumWidth(350)
        self.log_list.currentItemChanged.connect(self._on_log_selected)
        left_layout.addWidget(self.log_list)

        # 刷新按钮
        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self._load_log_files)
        left_layout.addWidget(refresh_btn)

        # 右侧：日志内容
        right_w = QWidget()
        right_layout = QVBoxLayout(right_w)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 搜索栏（VSCode 风格）
        self._create_search_bar(right_layout)

        content_label = QLabel("日志内容:")
        right_layout.addWidget(content_label)

        self.log_content = QTextEdit()
        self.log_content.setReadOnly(True)
        self.log_content.setFont(QFont("Consolas", 10))
        self.log_content.setLineWrapMode(QTextEdit.NoWrap)
        self.log_content.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_content.customContextMenuRequested.connect(self._show_context_menu)
        right_layout.addWidget(self.log_content)

        # 底部按钮
        btn_layout = QHBoxLayout()

        export_btn = QPushButton("📤 导出日志")
        export_btn.clicked.connect(self._export_log)
        btn_layout.addWidget(export_btn)

        delete_btn = QPushButton("🗑️ 删除此日志")
        delete_btn.clicked.connect(self._delete_log)
        btn_layout.addWidget(delete_btn)

        delete_all_btn = QPushButton("🗑️ 删除全部日志")
        delete_all_btn.clicked.connect(self._delete_all_logs)
        delete_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f44336;
            }
        """)
        btn_layout.addWidget(delete_all_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        right_layout.addLayout(btn_layout)

        # 添加到分割器
        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)

    def _create_search_bar(self, parent_layout):
        """创建 VSCode 风格的搜索栏"""
        # 搜索栏容器
        search_frame = QFrame()
        search_frame.setStyleSheet("""
            QFrame {
                background-color: #3c3c3c;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(8, 4, 8, 4)
        search_layout.setSpacing(6)

        # 搜索输入框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #007acc;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.returnPressed.connect(self._find_next)
        search_layout.addWidget(self.search_input, 1)

        # 匹配计数标签
        self.match_count_label = QLabel("无结果")
        self.match_count_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 12px;
                min-width: 70px;
            }
        """)
        search_layout.addWidget(self.match_count_label)

        # 大小写敏感复选框
        self.case_sensitive_cb = QCheckBox("Aa")
        self.case_sensitive_cb.setToolTip("区分大小写")
        self.case_sensitive_cb.setStyleSheet("""
            QCheckBox {
                color: #888;
                font-size: 12px;
                font-weight: bold;
            }
            QCheckBox:checked {
                color: #007acc;
            }
        """)
        self.case_sensitive_cb.toggled.connect(self._on_search_text_changed)
        search_layout.addWidget(self.case_sensitive_cb)

        # 上一个按钮
        self.prev_btn = QPushButton("↑")
        self.prev_btn.setToolTip("上一个匹配 (Shift+Enter)")
        self.prev_btn.setFixedSize(28, 24)
        self.prev_btn.setStyleSheet(self._get_nav_button_style())
        self.prev_btn.clicked.connect(self._find_previous)
        search_layout.addWidget(self.prev_btn)

        # 下一个按钮
        self.next_btn = QPushButton("↓")
        self.next_btn.setToolTip("下一个匹配 (Enter)")
        self.next_btn.setFixedSize(28, 24)
        self.next_btn.setStyleSheet(self._get_nav_button_style())
        self.next_btn.clicked.connect(self._find_next)
        search_layout.addWidget(self.next_btn)

        # 关闭搜索按钮
        close_search_btn = QPushButton("×")
        close_search_btn.setToolTip("关闭搜索")
        close_search_btn.setFixedSize(24, 24)
        close_search_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #fff;
                background-color: #555;
                border-radius: 3px;
            }
        """)
        close_search_btn.clicked.connect(self._close_search)
        search_layout.addWidget(close_search_btn)

        parent_layout.addWidget(search_frame)

    def _get_nav_button_style(self):
        """获取导航按钮样式"""
        return """
            QPushButton {
                background-color: #505050;
                color: #ccc;
                border: 1px solid #555;
                border-radius: 3px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #606060;
                border-color: #666;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
            QPushButton:disabled {
                background-color: #3c3c3c;
                color: #555;
            }
        """
    
    def _start_async_load(self):
        """开始异步加载日志文件"""
        # 如果已经在加载，取消之前的加载
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.cancel()
            self._loader_thread.wait(1000)  # 等待最多1秒

        # 显示加载状态
        self.loading_label.setText("正在加载日志文件...")
        self.loading_label.show()
        self.log_list.hide()
        self._is_loading = True

        # 创建并启动加载线程
        self._loader_thread = LogFileLoader(self.log_dir, self.task_name)
        self._loader_thread.progress.connect(self._on_load_progress)
        self._loader_thread.finished.connect(self._on_load_finished)
        self._loader_thread.error.connect(self._on_load_error)
        self._loader_thread.start()

    def _on_load_progress(self, current: int, total: int):
        """加载进度更新"""
        if total > 0:
            self.loading_label.setText(f"正在加载日志文件... {current}/{total}")
        else:
            self.loading_label.setText(f"正在加载日志文件... ({current} 个)")

    def _on_load_finished(self, files: list):
        """加载完成"""
        self._is_loading = False
        self.loading_label.hide()
        self.log_list.show()

        # 保存文件列表
        self._all_log_files = files

        # 应用过滤
        self._do_apply_filters()

        # 如果没有日志文件，显示提示
        if not files:
            self.log_content.setPlainText(f"暂无执行日志记录\n\n任务: {self.task_name}\n日志目录: {self.log_dir}")

    def _on_load_error(self, error_msg: str):
        """加载错误"""
        self._is_loading = False
        self.loading_label.hide()
        self.log_list.show()

        self.log_content.setPlainText(f"加载日志失败\n\n错误: {error_msg}\n\n任务: {self.task_name}\n日志目录: {self.log_dir}")
        self._all_log_files = []

    def _load_log_files(self):
        """手动刷新日志文件列表（点击刷新按钮时调用）"""
        self._start_async_load()

    def _apply_filters_debounced(self):
        """去抖动的筛选触发（延迟300ms）"""
        self._filter_timer.stop()
        self._filter_timer.start(300)  # 300ms延迟

    def _apply_filters(self):
        """立即应用筛选（用于下拉框等需要立即响应的场景）"""
        self._filter_timer.stop()
        self._do_apply_filters()

    def _parse_display_time(self, filename: str, mtime: float) -> str:
        """解析文件名中的时间（优化版本）"""
        try:
            # 文件名格式: taskname_YYYYMMDD_HHMMSS.log
            # 从后往前查找，避免任务名中包含下划线的情况
            name_without_ext = filename[:-4]  # 去掉 .log
            parts = name_without_ext.rsplit('_', 2)

            if len(parts) >= 3:
                date_str = parts[-2]
                time_str = parts[-1]

                # 快速验证格式
                if len(date_str) == 8 and len(time_str) == 6:
                    if date_str.isdigit() and time_str.isdigit():
                        # 格式化时间字符串
                        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
        except (IndexError, ValueError):
            pass

        # 降级方案：使用文件修改时间
        return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

    def _do_apply_filters(self):
        """应用筛选条件（优化：减少UI更新）"""
        # 暂时禁用信号以提高性能
        self.log_list.blockSignals(True)
        self.log_list.clear()

        if not self._all_log_files:
            self.log_content.setPlainText(f"暂无执行日志记录\n\n任务: {self.task_name}\n日志目录: {self.log_dir}")
            self.log_list.blockSignals(False)
            return

        # 获取筛选条件
        filename_filter = self.filename_filter.text().strip().lower()
        time_range_index = self.time_range_combo.currentIndex()

        # 计算时间范围
        now = datetime.now()
        start_time = None
        end_time = now

        if time_range_index == 1:  # 最近1小时
            start_time = now - timedelta(hours=1)
        elif time_range_index == 2:  # 最近24小时
            start_time = now - timedelta(days=1)
        elif time_range_index == 3:  # 最近3天
            start_time = now - timedelta(days=3)
        elif time_range_index == 4:  # 最近7天
            start_time = now - timedelta(days=7)
        elif time_range_index == 5:  # 最近30天
            start_time = now - timedelta(days=30)
        elif time_range_index == 6:  # 自定义范围
            start_qdate = self.start_date.date()
            end_qdate = self.end_date.date()
            start_time = datetime(start_qdate.year(), start_qdate.month(), start_qdate.day())
            end_time = datetime(end_qdate.year(), end_qdate.month(), end_qdate.day(), 23, 59, 59)

        # 过滤文件
        filtered_files = []
        for filename, filepath, mtime, display_time in self._all_log_files:
            # 文件名过滤
            if filename_filter and filename_filter not in filename.lower():
                continue

            # 时间范围过滤
            file_time = datetime.fromtimestamp(mtime)
            if start_time and file_time < start_time:
                continue
            if end_time and file_time > end_time:
                continue

            filtered_files.append((filename, filepath, mtime, display_time))

        # 批量添加到列表（减少重绘）
        from PyQt5.QtWidgets import QListWidgetItem

        # 限制显示数量，防止卡顿
        max_display = 500  # 最多显示500条
        if len(filtered_files) > max_display:
            self.log_content.setPlainText(
                f"⚠️ 过滤结果过多（{len(filtered_files)} 条）\n"
                f"仅显示最新的 {max_display} 条日志\n"
                f"请使用更精确的筛选条件"
            )
            filtered_files = filtered_files[-max_display:]  # 只取最新的

        for filename, filepath, mtime, display_time in filtered_files:
            item = QListWidgetItem(display_time)
            item.setData(Qt.UserRole, filepath)
            item.setToolTip(filename)
            self.log_list.addItem(item)

        # 恢复信号
        self.log_list.blockSignals(False)

        # 显示过滤结果
        if self.log_list.count() == 0:
            self.log_content.setPlainText(
                f"没有符合筛选条件的日志\n\n"
                f"总日志数: {len(self._all_log_files)}\n"
                f"筛选结果: 0"
            )
        elif self.log_list.count() > 0:
            # 选择第一项（会触发信号）
            self.log_list.setCurrentRow(0)

    def _on_time_range_changed(self, index):
        """时间范围改变"""
        # 显示/隐藏自定义日期范围
        self.custom_date_widget.setVisible(index == 6)
        self._apply_filters()

    def _clear_filters(self):
        """清除所有筛选条件"""
        self.filename_filter.clear()
        self.time_range_combo.setCurrentIndex(0)
        self.custom_date_widget.hide()
        self._apply_filters()

    def _on_log_selected(self, current, _previous):
        """选择日志文件（优化：限制大文件加载）"""
        if not current:
            return

        filepath = current.data(Qt.UserRole)
        if filepath and os.path.exists(filepath):
            try:
                # 检查文件大小
                file_size = os.path.getsize(filepath)
                max_size = 10 * 1024 * 1024  # 10MB限制

                if file_size > max_size:
                    # 文件太大，只读取最后部分
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(max(0, file_size - max_size))
                        content = f.read()
                    self._original_content = content
                    self.log_content.setPlainText(
                        f"⚠️ 日志文件过大（{file_size / 1024 / 1024:.2f} MB），仅显示最后 10MB\n"
                        f"{'='*60}\n\n" + content
                    )
                else:
                    # 正常读取
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    self._original_content = content
                    self.log_content.setPlainText(content)

                # 清除搜索状态
                self._search_matches = []
                self._current_match_index = -1
                self.match_count_label.setText("无结果")
                # 如果搜索框有内容，重新搜索
                if self.search_input.text():
                    self._on_search_text_changed(self.search_input.text())
            except Exception as e:
                self.log_content.setPlainText(f"读取日志失败: {e}")

    def _on_search_text_changed(self, text=None):
        """搜索文本变化时触发"""
        if text is None:
            text = self.search_input.text()

        # 清除之前的高亮
        self._clear_highlights()
        self._search_matches = []
        self._current_match_index = -1

        if not text:
            self.match_count_label.setText("无结果")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return

        # 执行搜索
        content = self._original_content or self.log_content.toPlainText()
        case_sensitive = self.case_sensitive_cb.isChecked()

        if case_sensitive:
            search_content = content
            search_text = text
        else:
            search_content = content.lower()
            search_text = text.lower()

        # 查找所有匹配位置
        start = 0
        while True:
            pos = search_content.find(search_text, start)
            if pos == -1:
                break
            self._search_matches.append((pos, pos + len(text)))
            start = pos + 1

        # 更新 UI
        total = len(self._search_matches)
        if total == 0:
            self.match_count_label.setText("无结果")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
        else:
            self._current_match_index = 0
            self._highlight_all_matches()
            self._goto_current_match()
            self._update_match_label()
            self.prev_btn.setEnabled(True)
            self.next_btn.setEnabled(True)

    def _clear_highlights(self):
        """清除所有高亮"""
        # 使用 ExtraSelections 方式，直接清空即可
        self.log_content.setExtraSelections([])

    def _highlight_all_matches(self):
        """高亮所有匹配项（使用 ExtraSelections）"""
        if not self._search_matches:
            self.log_content.setExtraSelections([])
            return

        selections = []

        # 普通匹配的高亮颜色（明亮黄色背景）
        normal_fmt = QTextCharFormat()
        normal_fmt.setBackground(QColor("#FFFF00"))  # 亮黄色
        normal_fmt.setForeground(QColor("#000000"))  # 黑色文字

        # 当前匹配的高亮颜色（橙色背景）
        current_fmt = QTextCharFormat()
        current_fmt.setBackground(QColor("#FF8C00"))  # 橙色
        current_fmt.setForeground(QColor("#000000"))  # 黑色文字

        for i, (start, end) in enumerate(self._search_matches):
            selection = QTextEdit.ExtraSelection()
            cursor = self.log_content.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.cursor = cursor

            # 当前匹配用橙色，其他用黄色
            if i == self._current_match_index:
                selection.format = current_fmt
            else:
                selection.format = normal_fmt

            selections.append(selection)

        self.log_content.setExtraSelections(selections)

    def _highlight_current_match(self):
        """高亮当前匹配项（重新应用所有高亮）"""
        # 使用 ExtraSelections 时，需要重新设置所有高亮
        self._highlight_all_matches()

    def _goto_current_match(self):
        """跳转到当前匹配位置"""
        if self._current_match_index < 0 or self._current_match_index >= len(self._search_matches):
            return

        start, end = self._search_matches[self._current_match_index]
        cursor = self.log_content.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.log_content.setTextCursor(cursor)
        self.log_content.ensureCursorVisible()

    def _update_match_label(self):
        """更新匹配计数标签"""
        total = len(self._search_matches)
        if total == 0:
            self.match_count_label.setText("无结果")
        else:
            current = self._current_match_index + 1
            self.match_count_label.setText(f"{current}/{total}")

    def _find_next(self):
        """查找下一个匹配"""
        if not self._search_matches:
            return

        # 先将当前匹配恢复为普通高亮
        self._restore_normal_highlight(self._current_match_index)

        # 移动到下一个
        self._current_match_index = (self._current_match_index + 1) % len(self._search_matches)

        # 高亮新的当前匹配
        self._highlight_current_match()
        self._goto_current_match()
        self._update_match_label()

    def _find_previous(self):
        """查找上一个匹配"""
        if not self._search_matches:
            return

        # 先将当前匹配恢复为普通高亮
        self._restore_normal_highlight(self._current_match_index)

        # 移动到上一个
        self._current_match_index = (self._current_match_index - 1) % len(self._search_matches)

        # 高亮新的当前匹配
        self._highlight_current_match()
        self._goto_current_match()
        self._update_match_label()

    def _restore_normal_highlight(self, index):  # noqa: ARG002
        """将指定索引的匹配恢复为普通高亮（使用 ExtraSelections 时不需要单独处理）"""
        # 使用 ExtraSelections 方式时，_highlight_all_matches 会统一处理
        pass

    def _close_search(self):
        """关闭搜索"""
        self.search_input.clear()
        self._clear_highlights()
        self._search_matches = []
        self._current_match_index = -1
        self.match_count_label.setText("无结果")

    def keyPressEvent(self, event):
        """键盘事件处理"""
        # Ctrl+F 聚焦搜索框
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            self.search_input.setFocus()
            self.search_input.selectAll()
            return

        # Shift+Enter 查找上一个
        if event.modifiers() == Qt.ShiftModifier and event.key() == Qt.Key_Return:
            self._find_previous()
            return

        # Escape 关闭搜索
        if event.key() == Qt.Key_Escape:
            if self.search_input.hasFocus():
                self._close_search()
                self.log_content.setFocus()
                return

        super().keyPressEvent(event)

    def _export_log(self):
        """导出当前日志"""
        current = self.log_list.currentItem()
        if not current:
            MsgBox.warning(self, "提示", "请先选择一个日志文件")
            return

        filepath = current.data(Qt.UserRole)
        if not filepath:
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出日志",
            os.path.basename(filepath),
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*)"
        )
        if save_path:
            try:
                import shutil
                shutil.copy(filepath, save_path)
                MsgBox.information(self, "成功", f"日志已导出到:\n{save_path}")
            except Exception as e:
                MsgBox.critical(self, "错误", f"导出失败: {e}")

    def _delete_log(self):
        """删除当前日志"""
        current = self.log_list.currentItem()
        if not current:
            MsgBox.warning(self, "提示", "请先选择一个日志文件")
            return

        filepath = current.data(Qt.UserRole)
        if not filepath:
            return

        if MsgBox.question(self, "确认删除", f"确定要删除这条执行日志吗？\n{current.text()}"):
            try:
                os.remove(filepath)
                self._load_log_files()
                self.log_content.clear()
            except Exception as e:
                MsgBox.critical(self, "错误", f"删除失败: {e}")

    def _delete_all_logs(self):
        """删除全部显示的日志（受筛选影响）"""
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt as QtCore_Qt

        # 获取当前显示的日志文件列表
        displayed_files = []
        for i in range(self.log_list.count()):
            item = self.log_list.item(i)
            filepath = item.data(Qt.UserRole)
            if filepath:  # 确保路径有效
                displayed_files.append(filepath)

        if not displayed_files:
            MsgBox.information(self, "提示", "没有可删除的日志文件")
            return

        total_count = len(displayed_files)
        all_count = len(self._all_log_files)

        # 二次确认
        if total_count == all_count:
            confirm_msg = f"确定要删除当前任务的全部 {total_count} 条日志吗？"
        else:
            confirm_msg = f"确定要删除当前显示的 {total_count} 条日志吗？\n（共有 {all_count} 条日志，当前已应用筛选）"

        reply = MsgBox.question(
            self,
            "⚠️ 危险操作",
            f"{confirm_msg}\n\n"
            f"任务名称: {self.task_name}\n"
            f"此操作无法撤销！",
            default_no=True
        )

        if not reply:
            return

        # 创建进度对话框
        progress = QProgressDialog("正在删除日志文件...", "取消", 0, total_count, self)
        progress.setWindowTitle("删除进度")
        progress.setWindowModality(QtCore_Qt.WindowModal)
        progress.setMinimumDuration(0)  # 立即显示
        progress.setValue(0)

        # 执行删除
        success_count = 0
        failed_files = []

        for idx, filepath in enumerate(displayed_files):
            # 更新进度
            progress.setValue(idx)
            progress.setLabelText(f"正在删除 ({idx + 1}/{total_count})...\n{os.path.basename(filepath)}")

            # 检查是否取消
            if progress.wasCanceled():
                break

            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    success_count += 1
                else:
                    failed_files.append((os.path.basename(filepath), "文件不存在"))
            except PermissionError:
                failed_files.append((os.path.basename(filepath), "权限不足"))
            except Exception as e:
                failed_files.append((os.path.basename(filepath), str(e)))

        progress.setValue(total_count)
        progress.close()

        # 显示结果
        if progress.wasCanceled():
            MsgBox.information(self, "已取消", f"已删除 {success_count} 条日志，操作已取消")
        elif failed_files:
            error_msg = f"成功删除 {success_count} 条日志\n失败 {len(failed_files)} 条:\n\n"
            for fname, err in failed_files[:5]:  # 最多显示5条错误
                error_msg += f"• {fname}: {err}\n"
            if len(failed_files) > 5:
                error_msg += f"\n... 还有 {len(failed_files) - 5} 条失败"
            MsgBox.warning(self, "部分删除失败", error_msg)
        else:
            MsgBox.information(self, "成功", f"已成功删除 {success_count} 条日志")

        # 重新加载
        self._load_log_files()
        self.log_content.clear()

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        from PyQt5.QtWidgets import QMenu, QApplication

        menu = QMenu(self)

        # 复制
        copy_action = menu.addAction("复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.log_content.copy)

        # 全选
        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self.log_content.selectAll)

        menu.addSeparator()

        # 复制全部
        copy_all_action = menu.addAction("复制全部内容")
        copy_all_action.triggered.connect(self._copy_all_content)

        # 显示菜单
        menu.exec_(self.log_content.mapToGlobal(pos))

    def _copy_all_content(self):
        """复制全部内容到剪贴板"""
        from PyQt5.QtWidgets import QApplication

        text = self.log_content.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            MsgBox.information(self, "提示", "日志内容已复制到剪贴板")

    def closeEvent(self, event):
        """关闭事件：停止加载线程"""
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.cancel()
            self._loader_thread.wait(1000)  # 等待最多1秒
        event.accept()

