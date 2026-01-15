# -*- coding: utf-8 -*-
"""
任务实时执行对话框
支持 ANSI 转义码颜色显示
"""
import subprocess
import os
import sys
import re
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QTextCursor, QColor, QTextCharFormat

from core.models import Task

# 导入 ANSI 颜色定义
from .background_output_dialog import ANSI_COLORS, ANSI_BG_COLORS, ANSI_ESCAPE_RE


class ExecutionThread(QThread):
    """任务执行线程 - 支持命令任务和同步任务"""
    output_received = pyqtSignal(str, str)  # (text, type: 'stdout'/'stderr'/'info')
    execution_finished = pyqtSignal(int, float)  # (exit_code, duration)

    def __init__(self, task: Task, kill_previous: bool = False):
        super().__init__()
        self.task = task
        self.kill_previous = kill_previous
        self.process = None
        self._stop_requested = False
        self._tracker = None
        self._sync_engine = None

    def run(self):
        """执行任务 - 根据任务类型选择执行方式"""
        from core.models import TaskType
        from core.process_tracker import get_process_tracker
        self._tracker = get_process_tracker()

        start_time = datetime.now()

        # 如果需要，先终止上次的实例
        if self.kill_previous or getattr(self.task, 'kill_previous', False):
            if self._tracker.is_task_running(self.task.id):
                self.output_received.emit("检测到上次执行的实例仍在运行，正在终止...\n", 'info')
                self._tracker.kill_task_processes(self.task.id)
                self.output_received.emit("上次实例已终止\n", 'info')

        # 根据任务类型执行
        if self.task.task_type == TaskType.SYNC:
            exit_code = self._run_sync_task()
        else:
            exit_code = self._run_command_task()

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.execution_finished.emit(exit_code, duration)

    def _run_command_task(self):
        """执行命令任务"""
        # 设置工作目录
        working_dir = self.task.working_dir
        if working_dir and not os.path.isabs(working_dir):
            working_dir = os.path.abspath(working_dir)
        if not working_dir or not os.path.exists(working_dir):
            working_dir = os.getcwd()

        self.output_received.emit(f"开始执行任务: {self.task.name}\n", 'info')
        self.output_received.emit(f"工作目录: {working_dir}\n", 'info')
        self.output_received.emit(f"命令: {self.task.command}\n", 'info')
        self.output_received.emit("=" * 50 + "\n\n", 'info')

        try:
            # 设置环境变量
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            # Windows 使用 UTF-8 代码页
            if sys.platform == 'win32':
                command = f'chcp 65001 >nul && {self.task.command}'
                self.process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_dir,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                self.process = subprocess.Popen(
                    self.task.command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_dir,
                    env=env
                )

            # 注册到进程追踪器
            self._tracker.register_task(self.task.id, self.process.pid)

            # 实时读取输出
            import threading

            def decode_output(data: bytes) -> str:
                """智能解码输出，尝试多种编码"""
                # 尝试的编码顺序
                encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'cp936', 'latin-1']
                for encoding in encodings:
                    try:
                        return data.decode(encoding)
                    except (UnicodeDecodeError, LookupError):
                        continue
                # 最后使用 utf-8 并替换错误字符
                return data.decode('utf-8', errors='replace')

            def read_stdout():
                for line in iter(self.process.stdout.readline, b''):
                    if self._stop_requested:
                        break
                    text = decode_output(line)
                    self.output_received.emit(text, 'stdout')
                self.process.stdout.close()

            def read_stderr():
                for line in iter(self.process.stderr.readline, b''):
                    if self._stop_requested:
                        break
                    text = decode_output(line)
                    self.output_received.emit(text, 'stderr')
                self.process.stderr.close()

            stdout_thread = threading.Thread(target=read_stdout)
            stderr_thread = threading.Thread(target=read_stderr)
            stdout_thread.start()
            stderr_thread.start()

            # 等待进程完成
            self.process.wait()
            stdout_thread.join()
            stderr_thread.join()

            exit_code = self.process.returncode

        except Exception as e:
            self.output_received.emit(f"\n执行出错: {e}\n", 'stderr')
            exit_code = -1
        finally:
            # 从追踪器注销
            if self._tracker:
                self._tracker.unregister_task(self.task.id)

        return exit_code

    def _run_sync_task(self):
        """执行同步任务"""
        from core.sync_engine import SyncEngine

        self.output_received.emit(f"开始执行同步任务: {self.task.name}\n", 'info')
        self.output_received.emit("=" * 50 + "\n\n", 'info')

        if not self.task.sync_config:
            self.output_received.emit("错误: 同步配置为空\n", 'stderr')
            return 1

        try:
            # 创建同步引擎
            self._sync_engine = SyncEngine(
                self.task.sync_config,
                thread_count=self.task.sync_config.max_concurrent or 4
            )

            # 设置进度回调
            def on_progress(msg, current, total):
                self.output_received.emit(f"[{current}/{total}] {msg}\n", 'info')

            self._sync_engine.set_progress_callback(on_progress)

            # 执行同步流程
            success, msg = self._sync_engine.connect()
            if not success:
                self.output_received.emit(f"连接失败: {msg}\n", 'stderr')
                return 1

            # 比较文件
            self.output_received.emit("正在比较文件...\n", 'info')
            sync_items = self._sync_engine.compare()
            items_to_process = [
                item for item in sync_items
                if item.action.value not in ('equal', 'skip', 'conflict')
            ]

            total_files = len(items_to_process)
            self.output_received.emit(f"发现 {total_files} 个文件需要同步\n", 'info')

            if total_files == 0:
                self._sync_engine.disconnect()
                self.output_received.emit("\n所有文件已是最新，无需同步\n", 'info')
                return 0

            # 执行同步
            result = self._sync_engine.execute(sync_items)
            self._sync_engine.disconnect()

            # 显示结果
            self.output_received.emit("\n" + "=" * 50 + "\n", 'info')
            self.output_received.emit(f"同步完成\n", 'info')
            self.output_received.emit(f"复制: {result.copied_files}  更新: {result.updated_files}  删除: {result.deleted_files}\n", 'info')
            self.output_received.emit(f"失败: {result.failed_files}  跳过: {result.skipped_files}\n", 'info')

            if result.errors:
                self.output_received.emit(f"\n错误信息:\n", 'stderr')
                for err in result.errors:
                    self.output_received.emit(f"  - {err}\n", 'stderr')
                return 1

            return 0

        except Exception as e:
            import traceback
            self.output_received.emit(f"\n同步执行异常: {e}\n", 'stderr')
            self.output_received.emit(traceback.format_exc(), 'stderr')
            return 1

    def stop(self):
        """停止执行"""
        self._stop_requested = True
        # 如果是同步任务，设置取消标志
        if self._sync_engine:
            self._sync_engine.cancel()
        # 使用进程追踪器终止所有相关进程
        if self._tracker:
            self._tracker.kill_task_processes(self.task.id)
        elif self.process:
            self.process.terminate()


class ExecutionDialog(QDialog):
    """任务实时执行对话框"""

    def __init__(self, parent=None, task: Task = None, task_logger=None):
        super().__init__(parent)
        self.task = task
        self.task_logger = task_logger
        self.thread = None
        self.start_time = None
        self.output_buffer = []  # 用于收集输出以便记录日志

        self.setWindowTitle(f"执行任务 - {task.name}")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)

        self._init_ui()

        # 自动开始执行
        QTimer.singleShot(100, self._start_execution)
    
    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 状态栏
        status_layout = QHBoxLayout()
        self.status_label = QLabel("准备执行...")
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        self.time_label = QLabel("耗时: 0.0 秒")
        status_layout.addStretch()
        status_layout.addWidget(self.time_label)
        layout.addLayout(status_layout)
        
        # 进度条（不确定模式）
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

        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

        # 计时器
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_time)

    def _start_execution(self):
        """开始执行"""
        self.start_time = datetime.now()
        self.timer.start(100)  # 每100ms更新一次

        self.status_label.setText("正在执行...")
        self.status_label.setStyleSheet("font-weight: bold; color: #0078d4;")

        self.thread = ExecutionThread(self.task)
        self.thread.output_received.connect(self._on_output)
        self.thread.execution_finished.connect(self._on_finished)
        self.thread.start()

    def _stop_execution(self):
        """停止执行"""
        from ui.message_box import MsgBox

        if MsgBox.question(self, "确认", "确定要停止执行吗？") == MsgBox.Yes:
            if self.thread and self.thread.isRunning():
                self.thread.stop()
                self.status_label.setText("正在停止...")
                self.stop_btn.setEnabled(False)

    def _update_time(self):
        """更新耗时显示"""
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.time_label.setText(f"耗时: {elapsed:.1f} 秒")

    def _on_output(self, text: str, output_type: str):
        """收到输出，支持 ANSI 转义码"""
        # 收集输出用于日志记录
        self.output_buffer.append((text, output_type))

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

    def _on_finished(self, exit_code: int, duration: float):
        """执行完成"""
        self.timer.stop()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

        self.time_label.setText(f"耗时: {duration:.2f} 秒")

        if exit_code == 0:
            self.status_label.setText("✓ 执行成功")
            self.status_label.setStyleSheet("font-weight: bold; color: #4ec9b0;")
            self._on_output(f"\n{'=' * 50}\n执行成功，退出代码: {exit_code}\n", 'info')
        else:
            self.status_label.setText(f"✗ 执行失败 (退出代码: {exit_code})")
            self.status_label.setStyleSheet("font-weight: bold; color: #f14c4c;")
            self._on_output(f"\n{'=' * 50}\n执行失败，退出代码: {exit_code}\n", 'stderr')

        # 更新任务状态
        self._update_task_status(exit_code)

        # 记录执行日志
        self._save_log(exit_code, duration)

        self.stop_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.close_btn.setFocus()

    def _update_task_status(self, exit_code: int):
        """更新任务状态到存储"""
        from core.models import TaskStorage, TaskStatus

        storage = TaskStorage()
        task = storage.get_task(self.task.id)
        if task:
            task.status = TaskStatus.SUCCESS if exit_code == 0 else TaskStatus.FAILED
            task.last_run = datetime.now().isoformat()
            task.last_result = f"Exit code: {exit_code}"
            storage.update_task(task)

    def _save_log(self, exit_code: int, duration: float):
        """保存执行日志"""
        if not self.task_logger:
            return

        from core.executor import ExecutionResult

        # 从缓冲区提取 stdout 和 stderr
        stdout_lines = []
        stderr_lines = []
        for text, output_type in self.output_buffer:
            if output_type == 'stdout':
                stdout_lines.append(text)
            elif output_type == 'stderr':
                stderr_lines.append(text)

        end_time = datetime.now()

        # 创建 ExecutionResult 对象
        result = ExecutionResult(
            success=(exit_code == 0),
            exit_code=exit_code,
            stdout=''.join(stdout_lines),
            stderr=''.join(stderr_lines),
            start_time=self.start_time,
            end_time=end_time,
            duration=duration
        )

        # 使用输出解析器解析控制台输出
        parsed_vars = {}
        if self.task.output_parsers:
            from core.output_parser import OutputParserEngine
            full_output = result.stdout + "\n" + result.stderr
            parsed_vars = OutputParserEngine.parse_all(full_output, self.task.output_parsers)

        # 记录日志
        self.task_logger.log_execution(
            task_id=self.task.id,
            task_name=self.task.name,
            command=self.task.command,
            working_dir=self.task.working_dir,
            result=result,
            parsed_vars=parsed_vars
        )

    def closeEvent(self, event):
        """关闭事件"""
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(1000)
        event.accept()

