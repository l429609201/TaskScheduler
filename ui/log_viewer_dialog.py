# -*- coding: utf-8 -*-
"""
任务执行日志查看对话框
"""
import os
import re
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QTextEdit, QLabel,
    QPushButton, QFileDialog, QLineEdit, QCheckBox, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QColor

from core.logger import TaskLogger
from .message_box import MsgBox


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

        self._init_ui()
        self._load_log_files()

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

        list_label = QLabel("执行记录:")
        left_layout.addWidget(list_label)

        self.log_list = QListWidget()
        self.log_list.setMinimumWidth(250)
        self.log_list.setMaximumWidth(350)
        self.log_list.currentItemChanged.connect(self._on_log_selected)
        left_layout.addWidget(self.log_list)

        # 刷新按钮
        refresh_btn = QPushButton("刷新列表")
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

        export_btn = QPushButton("导出日志")
        export_btn.clicked.connect(self._export_log)
        btn_layout.addWidget(export_btn)

        delete_btn = QPushButton("删除此日志")
        delete_btn.clicked.connect(self._delete_log)
        btn_layout.addWidget(delete_btn)

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
    
    def _load_log_files(self):
        """加载日志文件列表"""
        self.log_list.clear()

        # 清理任务名用于匹配文件（与 logger.py 中的逻辑保持一致）
        safe_name = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in self.task_name)
        safe_name = safe_name.strip().replace(' ', '_')

        # 确保日志目录存在
        if not os.path.exists(self.log_dir):
            try:
                os.makedirs(self.log_dir)
            except OSError:
                pass
            self.log_content.setPlainText(f"暂无执行日志记录\n\n任务: {self.task_name}\n日志目录: {self.log_dir}")
            return

        files = []
        for f in os.listdir(self.log_dir):
            # 匹配当前任务的日志文件
            if f.endswith('.log') and f.startswith(safe_name + '_'):
                filepath = os.path.join(self.log_dir, f)
                mtime = os.path.getmtime(filepath)
                files.append((f, filepath, mtime))

        # 按时间倒序
        files.sort(key=lambda x: x[2], reverse=True)

        for filename, filepath, mtime in files:
            # 解析时间显示
            try:
                # 文件名格式: taskname_YYYYMMDD_HHMMSS.log
                parts = filename.rsplit('_', 2)
                if len(parts) >= 3:
                    date_str = parts[-2]
                    time_str = parts[-1].replace('.log', '')
                    display_time = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
                else:
                    display_time = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            except:
                display_time = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

            item = QListWidgetItem(display_time)
            item.setData(Qt.UserRole, filepath)
            self.log_list.addItem(item)

        if self.log_list.count() == 0:
            self.log_content.setPlainText(f"暂无执行日志记录\n\n任务: {self.task_name}\n日志目录: {self.log_dir}\n匹配前缀: {safe_name}_")
        elif self.log_list.count() > 0:
            self.log_list.setCurrentRow(0)

    def _on_log_selected(self, current, _previous):
        """选择日志文件"""
        if not current:
            return

        filepath = current.data(Qt.UserRole)
        if filepath and os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
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

