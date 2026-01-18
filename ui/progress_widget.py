# -*- coding: utf-8 -*-
"""
自定义进度条 Widget - 支持百分比文字镂空效果
"""
from PyQt5.QtWidgets import QWidget, QProgressBar, QVBoxLayout, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPainter, QFont, QColor, QPen


class ProgressWidget(QWidget):
    """带镂空百分比文字的进度条 Widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress_value = 0
        self.status_text = ""
        self.setMinimumHeight(24)
        
    def set_progress(self, value: int, text: str = ""):
        """设置进度值和状态文字"""
        self.progress_value = max(0, min(100, value))
        self.status_text = text
        self.update()
    
    def paintEvent(self, event):
        """绘制进度条和镂空文字"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 获取绘制区域
        rect = self.rect()
        
        # 绘制背景
        painter.setBrush(QColor("#E0E0E0"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 3, 3)
        
        # 绘制进度条
        if self.progress_value > 0:
            progress_width = int(rect.width() * self.progress_value / 100)
            progress_rect = rect.adjusted(0, 0, -(rect.width() - progress_width), 0)
            
            # 进度条颜色 - 根据状态变化
            if self.progress_value < 100:
                color = QColor("#4CAF50")  # 绿色
            else:
                color = QColor("#2196F3")  # 蓝色
            
            painter.setBrush(color)
            painter.drawRoundedRect(progress_rect, 3, 3)
        
        # 绘制百分比文字（镂空效果）
        if self.status_text:
            text = self.status_text
        else:
            text = f"{self.progress_value}%"
        
        # 设置字体
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        
        # 绘制白色文字阴影（增强镂空效果）
        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawText(rect.adjusted(1, 1, 1, 1), Qt.AlignCenter, text)
        
        # 绘制深色文字
        painter.setPen(QColor(50, 50, 50))
        painter.drawText(rect, Qt.AlignCenter, text)
        
        painter.end()
    
    def sizeHint(self):
        """建议大小"""
        return QSize(120, 24)


class TaskProgressWidget(QWidget):
    """任务进度显示 Widget - 用于表格单元格"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        
        # 进度条
        self.progress_bar = ProgressWidget()
        layout.addWidget(self.progress_bar)
        
        self.setLayout(layout)
    
    def set_progress(self, value: int, text: str = ""):
        """设置进度"""
        self.progress_bar.set_progress(value, text)
    
    def set_status(self, text: str):
        """设置状态文字（不显示进度条）"""
        self.progress_bar.set_progress(0, text)
        self.progress_bar.update()


class SimpleProgressWidget(QWidget):
    """简单的进度显示 - 只显示文字和进度条"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # 状态文字
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.status_label, 1)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setFixedWidth(100)
        self.progress_bar.setFixedHeight(20)
        layout.addWidget(self.progress_bar, 0)
        
        self.setLayout(layout)
    
    def set_progress(self, value: int, text: str = ""):
        """设置进度"""
        self.progress_bar.setValue(value)
        if text:
            self.status_label.setText(text)
    
    def set_status(self, text: str):
        """设置状态文字"""
        self.status_label.setText(text)
        self.progress_bar.setVisible(False)

