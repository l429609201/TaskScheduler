# -*- coding: utf-8 -*-
"""
后台任务输出查看对话框
支持 ANSI 转义码颜色显示
"""
import re
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor, QColor, QTextCharFormat

from core.models import Task


# ANSI 标准颜色（前景色）
ANSI_COLORS = {
    30: '#0c0c0c',  # 黑色
    31: '#c50f1f',  # 红色
    32: '#13a10e',  # 绿色
    33: '#c19c00',  # 黄色
    34: '#0037da',  # 蓝色
    35: '#881798',  # 品红
    36: '#3a96dd',  # 青色
    37: '#cccccc',  # 白色
    # 亮色版本
    90: '#767676',  # 亮黑（灰）
    91: '#e74856',  # 亮红
    92: '#16c60c',  # 亮绿
    93: '#f9f1a5',  # 亮黄
    94: '#3b78ff',  # 亮蓝
    95: '#b4009e',  # 亮品红
    96: '#61d6d6',  # 亮青
    97: '#f2f2f2',  # 亮白
}

# ANSI 背景色
ANSI_BG_COLORS = {
    40: '#0c0c0c',  # 黑色
    41: '#c50f1f',  # 红色
    42: '#13a10e',  # 绿色
    43: '#c19c00',  # 黄色
    44: '#0037da',  # 蓝色
    45: '#881798',  # 品红
    46: '#3a96dd',  # 青色
    47: '#cccccc',  # 白色
    # 亮色版本
    100: '#767676',
    101: '#e74856',
    102: '#16c60c',
    103: '#f9f1a5',
    104: '#3b78ff',
    105: '#b4009e',
    106: '#61d6d6',
    107: '#f2f2f2',
}

# ANSI 转义码正则表达式
ANSI_ESCAPE_RE = re.compile(r'\x1b\[([0-9;]*)m')


class BackgroundOutputDialog(QDialog):
    """后台任务输出查看对话框"""
    
    def __init__(self, parent=None, task: Task = None, bg_manager=None):
        super().__init__(parent)
        self.task = task
        self.bg_manager = bg_manager
        self._last_output_len = 0
        
        self.setWindowTitle(f"后台任务输出 - {task.name}")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)
        
        self._init_ui()
        self._load_existing_output()
        
        # 定时刷新输出
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_output)
        self.refresh_timer.start(200)  # 每200ms刷新一次
    
    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 状态栏
        status_layout = QHBoxLayout()
        self.status_label = QLabel("后台运行中...")
        self.status_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # 进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # 不确定模式
        layout.addWidget(self.progress)

        # 输出文本框
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Consolas", 10))
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
            }
        """)
        layout.addWidget(self.output_text)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.stop_btn = QPushButton("停止执行")
        self.stop_btn.clicked.connect(self._stop_execution)
        btn_layout.addWidget(self.stop_btn)

        self.close_btn = QPushButton("关闭窗口")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)
    
    def _load_existing_output(self):
        """加载已有的输出"""
        if self.bg_manager:
            output = self.bg_manager.get_output(self.task.id)
            for text, output_type in output:
                self._append_output(text, output_type)
                self._update_status_from_output(text)
            self._last_output_len = len(output)

    def _refresh_output(self):
        """刷新输出"""
        if not self.bg_manager:
            return

        # 检查任务状态
        is_running = self.bg_manager.is_running(self.task.id)

        # 获取新输出
        output = self.bg_manager.get_output(self.task.id)
        if len(output) > self._last_output_len:
            for text, output_type in output[self._last_output_len:]:
                self._append_output(text, output_type)
                self._update_status_from_output(text)
            self._last_output_len = len(output)

        # 更新状态
        if not is_running:
            self.refresh_timer.stop()
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.status_label.setText("✓ 执行完成")
            self.status_label.setStyleSheet("font-weight: bold; color: #4ec9b0;")
            self.stop_btn.setEnabled(False)

    def _update_status_from_output(self, text: str):
        """根据输出更新状态显示"""
        if "开始执行任务:" in text:
            self.status_label.setText("正在执行...")
        elif "执行成功" in text:
            self.status_label.setText("✓ 执行成功")
            self.status_label.setStyleSheet("font-weight: bold; color: #4ec9b0;")
        elif "执行失败" in text:
            self.status_label.setText("✗ 执行失败")
            self.status_label.setStyleSheet("font-weight: bold; color: #f14c4c;")
    
    def _append_output(self, text: str, output_type: str):
        """追加输出，支持 ANSI 转义码"""
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.End)

        # 默认颜色
        if output_type == 'stderr':
            default_color = '#f14c4c'  # 红色
        elif output_type == 'info':
            default_color = '#3794ff'  # 蓝色
        else:
            default_color = '#d4d4d4'  # 默认灰白色

        # 解析 ANSI 转义码
        self._parse_ansi_text(cursor, text, default_color)

        # 滚动到底部
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

    def _parse_ansi_text(self, cursor: QTextCursor, text: str, default_color: str):
        """解析包含 ANSI 转义码的文本"""
        # 当前格式状态
        current_fg = default_color
        current_bg = None
        is_bold = False
        is_dim = False
        is_italic = False
        is_underline = False

        # 分割文本
        last_end = 0
        for match in ANSI_ESCAPE_RE.finditer(text):
            # 输出转义码之前的文本
            before_text = text[last_end:match.start()]
            if before_text:
                self._insert_formatted_text(cursor, before_text, current_fg, current_bg,
                                           is_bold, is_dim, is_italic, is_underline)

            # 解析转义码
            codes_str = match.group(1)
            if codes_str:
                codes = [int(c) for c in codes_str.split(';') if c]
            else:
                codes = [0]  # 空的等同于重置

            # 处理每个代码
            i = 0
            while i < len(codes):
                code = codes[i]

                if code == 0:  # 重置
                    current_fg = default_color
                    current_bg = None
                    is_bold = False
                    is_dim = False
                    is_italic = False
                    is_underline = False
                elif code == 1:  # 粗体/高亮
                    is_bold = True
                elif code == 2:  # 暗淡
                    is_dim = True
                elif code == 3:  # 斜体
                    is_italic = True
                elif code == 4:  # 下划线
                    is_underline = True
                elif code == 22:  # 取消粗体/暗淡
                    is_bold = False
                    is_dim = False
                elif code == 23:  # 取消斜体
                    is_italic = False
                elif code == 24:  # 取消下划线
                    is_underline = False
                elif code in ANSI_COLORS:  # 前景色
                    current_fg = ANSI_COLORS[code]
                elif code in ANSI_BG_COLORS:  # 背景色
                    current_bg = ANSI_BG_COLORS[code]
                elif code == 39:  # 默认前景色
                    current_fg = default_color
                elif code == 49:  # 默认背景色
                    current_bg = None
                elif code == 38:  # 扩展前景色 (256色或RGB)
                    if i + 1 < len(codes):
                        if codes[i + 1] == 5 and i + 2 < len(codes):  # 256色
                            color_idx = codes[i + 2]
                            current_fg = self._get_256_color(color_idx)
                            i += 2
                        elif codes[i + 1] == 2 and i + 4 < len(codes):  # RGB
                            r, g, b = codes[i + 2], codes[i + 3], codes[i + 4]
                            current_fg = f'#{r:02x}{g:02x}{b:02x}'
                            i += 4
                elif code == 48:  # 扩展背景色
                    if i + 1 < len(codes):
                        if codes[i + 1] == 5 and i + 2 < len(codes):  # 256色
                            color_idx = codes[i + 2]
                            current_bg = self._get_256_color(color_idx)
                            i += 2
                        elif codes[i + 1] == 2 and i + 4 < len(codes):  # RGB
                            r, g, b = codes[i + 2], codes[i + 3], codes[i + 4]
                            current_bg = f'#{r:02x}{g:02x}{b:02x}'
                            i += 4

                i += 1

            last_end = match.end()

        # 输出剩余文本
        remaining = text[last_end:]
        if remaining:
            self._insert_formatted_text(cursor, remaining, current_fg, current_bg,
                                       is_bold, is_dim, is_italic, is_underline)

    def _insert_formatted_text(self, cursor: QTextCursor, text: str,
                               fg_color: str, bg_color: str,
                               bold: bool, dim: bool, italic: bool, underline: bool):
        """插入格式化文本"""
        fmt = QTextCharFormat()

        # 前景色
        color = QColor(fg_color)
        if dim:
            color.setAlpha(128)  # 暗淡效果
        fmt.setForeground(color)

        # 背景色
        if bg_color:
            fmt.setBackground(QColor(bg_color))

        # 粗体
        if bold:
            fmt.setFontWeight(75)  # Bold

        # 斜体
        if italic:
            fmt.setFontItalic(True)

        # 下划线
        if underline:
            fmt.setFontUnderline(True)

        cursor.insertText(text, fmt)

    def _get_256_color(self, idx: int) -> str:
        """获取 256 色调色板中的颜色"""
        if idx < 16:
            # 标准 16 色
            colors_16 = [
                '#0c0c0c', '#c50f1f', '#13a10e', '#c19c00',
                '#0037da', '#881798', '#3a96dd', '#cccccc',
                '#767676', '#e74856', '#16c60c', '#f9f1a5',
                '#3b78ff', '#b4009e', '#61d6d6', '#f2f2f2'
            ]
            return colors_16[idx]
        elif idx < 232:
            # 216 色立方体 (6x6x6)
            idx -= 16
            r = (idx // 36) * 51
            g = ((idx // 6) % 6) * 51
            b = (idx % 6) * 51
            return f'#{r:02x}{g:02x}{b:02x}'
        else:
            # 24 级灰度
            gray = (idx - 232) * 10 + 8
            return f'#{gray:02x}{gray:02x}{gray:02x}'
    
    def _stop_execution(self):
        """停止执行"""
        from ui.message_box import MsgBox

        if MsgBox.question(self, "确认", "确定要停止执行吗？") == MsgBox.Yes:
            if self.bg_manager:
                self.bg_manager.stop_task(self.task.id)
                self.status_label.setText("正在停止...")
                self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        """关闭事件"""
        self.refresh_timer.stop()
        event.accept()

