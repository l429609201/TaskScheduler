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
    progress_updated = pyqtSignal(str, int, int, int)  # message, current, total, bytes
    file_completed = pyqtSignal(str, str, bool)  # file_path, action, success
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
                logger.debug(f"进度回调: {msg}, {current}/{total}")
                self.progress_updated.emit(msg, current, total, self.engine._processed_count)

            self.engine.set_progress_callback(on_progress)

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
    
    def __init__(self, engine, total_files: int, total_bytes: int = 0, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.start_time = time.time()
        self.transferred_bytes = 0
        self.processed_files = 0
        self.current_file = ""
        self._cancelled = False
        self.result = None
        
        self._init_ui()
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

    def add_result_row(self, action: str, file_path: str, success: bool):
        """添加结果行"""
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        self.result_table.setItem(row, 0, QTableWidgetItem(action))
        self.result_table.setItem(row, 1, QTableWidgetItem(file_path))

        status_item = QTableWidgetItem("✓ 成功" if success else "✗ 失败")
        status_item.setForeground(Qt.darkGreen if success else Qt.red)
        self.result_table.setItem(row, 2, status_item)

        # 滚动到最新行
        self.result_table.scrollToBottom()

        # 限制显示行数
        if row > 100:
            self.result_table.removeRow(0)

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

