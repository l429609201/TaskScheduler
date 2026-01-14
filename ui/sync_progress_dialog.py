# -*- coding: utf-8 -*-
"""
同步进度对话框 - FreeFileSync 风格
显示详细的同步进度、速度、剩余时间等信息
"""
import time
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QFont


class SyncWorkerThread(QThread):
    """同步工作线程"""
    progress_updated = pyqtSignal(str, int, int, int)  # message, current, total, bytes_transferred
    file_completed = pyqtSignal(str, str, bool, int)  # file_path, action, success, bytes
    sync_finished = pyqtSignal(object)  # result

    def __init__(self, engine, sync_items=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.sync_items = sync_items  # 预先比较好的同步项
        self._bytes_transferred = 0

    def run(self):
        from core.sync_engine import SyncResult
        import logging
        logger = logging.getLogger(__name__)

        logger.info("SyncWorkerThread.run() 开始执行")

        try:
            # 设置进度回调
            def on_progress(msg, current, total):
                logger.debug(f"进度回调: {msg}, {current}/{total}, 传输字节: {self.engine._transferred_bytes}")
                self.progress_updated.emit(msg, current, total, self.engine._transferred_bytes)

            self.engine.set_progress_callback(on_progress)

            # 设置文件完成回调
            def on_file_completed(file_path, action, success, bytes_transferred):
                logger.debug(f"文件完成: {file_path}, action={action}, success={success}, bytes={bytes_transferred}")
                self.file_completed.emit(file_path, action, success, bytes_transferred)

            self.engine.set_file_completed_callback(on_file_completed)

            # 执行同步 - 传递预先比较好的同步项
            logger.info(f"开始调用 engine.execute(), sync_items={len(self.sync_items) if self.sync_items else 'None'}")
            result = self.engine.execute(self.sync_items)
            logger.info(f"engine.execute() 完成, success={result.success}")
            self.sync_finished.emit(result)
        except Exception as e:
            # 发生异常时返回失败结果
            import traceback
            logger.error(f"同步执行异常: {e}")
            traceback.print_exc()
            result = SyncResult()
            result.success = False
            result.errors.append(f"同步执行异常: {str(e)}")
            self.sync_finished.emit(result)


class SyncProgressDialog(QDialog):
    """同步进度对话框 - FreeFileSync 风格"""

    def __init__(self, engine, total_files: int, total_bytes: int = 0, sync_items=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.sync_items = sync_items or []  # 保存同步项列表
        self.start_time = time.time()
        self.transferred_bytes = 0
        self.processed_files = 0
        self.current_file = ""
        self._cancelled = False
        self.result = None
        self._file_row_map = {}  # 文件路径 -> 表格行号的映射
        self._file_items = {}  # 行号 -> QTableWidgetItem 映射

        self._init_ui()
        self._populate_file_table()  # 预先填充文件表
        self._start_timer()
        
    def _init_ui(self):
        self.setWindowTitle("同步进度")
        self.setMinimumSize(550, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # ===== 顶部：总体进度 =====
        progress_group = QGroupBox("同步进度")
        progress_layout = QVBoxLayout(progress_group)
        
        # 当前文件
        self.current_file_label = QLabel("准备中...")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("color: #666;")
        progress_layout.addWidget(self.current_file_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_files)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m 文件 (%p%)")
        self.progress_bar.setMinimumHeight(25)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(progress_group)
        
        # ===== 中部：统计信息 =====
        stats_group = QGroupBox("统计信息")
        stats_layout = QHBoxLayout(stats_group)
        
        # 左侧统计
        left_stats = QVBoxLayout()
        self.files_label = QLabel("已处理: 0 / 0 文件")
        self.speed_label = QLabel("速度: -- /s")
        self.transferred_label = QLabel("已传输: 0 B")
        left_stats.addWidget(self.files_label)
        left_stats.addWidget(self.speed_label)
        left_stats.addWidget(self.transferred_label)
        stats_layout.addLayout(left_stats)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        stats_layout.addWidget(line)
        
        # 右侧统计
        right_stats = QVBoxLayout()
        self.elapsed_label = QLabel("已用时间: 00:00")
        self.remaining_label = QLabel("剩余时间: --:--")
        self.eta_label = QLabel("预计完成: --:--")
        right_stats.addWidget(self.elapsed_label)
        right_stats.addWidget(self.remaining_label)
        right_stats.addWidget(self.eta_label)
        stats_layout.addLayout(right_stats)
        
        layout.addWidget(stats_group)
        
        # ===== 底部：操作结果 =====
        result_group = QGroupBox("同步文件列表")
        result_layout = QVBoxLayout(result_group)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(["状态", "操作", "文件", "大小"])
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setMinimumHeight(200)
        result_layout.addWidget(self.result_table)

        layout.addWidget(result_group)
        
        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        
        self.close_btn = QPushButton("关闭")
        self.close_btn.setMinimumWidth(100)
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _populate_file_table(self):
        """预先填充文件表格"""
        if not self.sync_items:
            return

        from core.models import FileAction

        self.result_table.setRowCount(0)

        # 只显示需要处理的文件（跳过 equal, skip, conflict）
        items_to_show = [
            item for item in self.sync_items
            if item.action not in (FileAction.EQUAL, FileAction.SKIP, FileAction.CONFLICT)
        ]

        self.result_table.setRowCount(len(items_to_show))

        for row, item in enumerate(items_to_show):
            # 操作类型
            action_map = {
                FileAction.COPY_TO_TARGET: "复制→",
                FileAction.COPY_TO_SOURCE: "←复制",
                FileAction.UPDATE_TARGET: "更新→",
                FileAction.UPDATE_SOURCE: "←更新",
                FileAction.DELETE_TARGET: "删除→",
                FileAction.DELETE_SOURCE: "←删除",
            }
            action_text = action_map.get(item.action, "未知")
            self.result_table.setItem(row, 1, QTableWidgetItem(action_text))

            # 文件路径
            self.result_table.setItem(row, 2, QTableWidgetItem(item.relative_path))

            # 文件大小
            size = (item.source_file.size if item.source_file else 0) or \
                   (item.target_file.size if item.target_file else 0)
            self.result_table.setItem(row, 3, QTableWidgetItem(self._format_size(size)))

            # 状态（初始为等待）
            status_item = QTableWidgetItem("⏳ 等待")
            status_item.setForeground(Qt.gray)
            self.result_table.setItem(row, 0, status_item)

            # 建立映射
            self._file_row_map[item.relative_path] = row
            self._file_items[row] = {
                'status': status_item,
                'action': action_text,
                'path': item.relative_path
            }

    def _start_timer(self):
        """启动更新定时器"""
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_stats)
        self.update_timer.start(500)  # 每500ms更新一次

    def _update_stats(self):
        """更新统计信息"""
        elapsed = time.time() - self.start_time

        # 已用时间
        elapsed_str = self._format_time(elapsed)
        self.elapsed_label.setText(f"已用时间: {elapsed_str}")

        # 速度计算
        if elapsed > 0 and self.transferred_bytes > 0:
            speed = self.transferred_bytes / elapsed
            self.speed_label.setText(f"速度: {self._format_size(speed)}/s")

            # 剩余时间估算
            if self.processed_files > 0 and self.processed_files < self.total_files:
                avg_time_per_file = elapsed / self.processed_files
                remaining_files = self.total_files - self.processed_files
                remaining_time = avg_time_per_file * remaining_files
                self.remaining_label.setText(f"剩余时间: {self._format_time(remaining_time)}")

                # 预计完成时间
                import datetime
                eta = datetime.datetime.now() + datetime.timedelta(seconds=remaining_time)
                self.eta_label.setText(f"预计完成: {eta.strftime('%H:%M:%S')}")

    def update_progress(self, message: str, current: int, total: int, bytes_transferred: int = 0):
        """更新进度"""
        self.processed_files = current
        self.current_file = message
        if bytes_transferred > 0:
            self.transferred_bytes = bytes_transferred

        # 更新UI
        self.current_file_label.setText(message)
        self.progress_bar.setValue(current)
        self.files_label.setText(f"已处理: {current} / {self.total_files} 文件")
        self.transferred_label.setText(f"已传输: {self._format_size(self.transferred_bytes)}")

        # 更新当前文件状态为"进行中"
        self._update_file_status(self.current_file, "🔄 进行中", Qt.blue)

    def _update_file_status(self, file_path: str, status_text: str, color):
        """更新文件状态"""
        # 提取文件路径（移除"处理: "前缀）
        if file_path.startswith("处理: "):
            file_path = file_path.replace("处理: ", "")

        row = self._file_row_map.get(file_path)
        if row is not None and row < self.result_table.rowCount():
            status_item = self.result_table.item(row, 0)
            if status_item:
                status_item.setText(status_text)
                status_item.setForeground(color)

    def add_result_row(self, action: str, file_path: str, success: bool, bytes_transferred: int = 0):
        """更新文件操作结果"""
        if success:
            self._update_file_status(file_path, "✓ 成功", Qt.darkGreen)
        else:
            self._update_file_status(file_path, "✗ 失败", Qt.red)

        # 更新传输大小（如果成功）
        if success and bytes_transferred > 0:
            # 获取行
            row = self._file_row_map.get(file_path)
            if row is not None and row < self.result_table.rowCount():
                size_item = self.result_table.item(row, 3)
                if size_item:
                    # 更新大小显示（添加已传输字节数）
                    size_item.setText(f"{self._format_size(bytes_transferred)}")

    def on_sync_finished(self, result):
        """同步完成"""
        self.result = result
        self.update_timer.stop()

        # 更新UI
        self.progress_bar.setValue(self.total_files)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

        if self._cancelled:
            self.current_file_label.setText("同步已取消")
            self.setWindowTitle("同步已取消")
        elif result.success:
            self.current_file_label.setText("同步完成！")
            self.setWindowTitle("同步完成")
        else:
            self.current_file_label.setText(f"同步完成，{result.failed_files} 个文件失败")
            self.setWindowTitle("同步完成（有错误）")

    def _on_cancel(self):
        """取消同步"""
        self._cancelled = True
        self.engine.cancel()
        self.cancel_btn.setEnabled(False)
        self.current_file_label.setText("正在取消...")

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
            secs = int(seconds % 60)
            return f"{hours:02d}:{mins:02d}:{secs:02d}"

    def _format_size(self, size: float) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def closeEvent(self, event):
        """关闭事件"""
        if not self.close_btn.isEnabled():
            # 同步进行中，询问是否取消
            from ui.message_box import MsgBox
            if MsgBox.question(self, "确认", "同步正在进行中，确定要取消吗？"):
                self._on_cancel()
                event.ignore()  # 等待同步取消完成
            else:
                event.ignore()
        else:
            event.accept()

