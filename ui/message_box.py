# -*- coding: utf-8 -*-
"""
汉化的消息框模块
"""
from PyQt5.QtWidgets import QMessageBox, QPushButton


class ChineseMessageBox:
    """汉化的消息框"""
    
    @staticmethod
    def question(parent, title, text, default_no=False):
        """询问对话框，返回 True 表示是，False 表示否"""
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setIcon(QMessageBox.Question)
        
        yes_btn = msg_box.addButton("是", QMessageBox.YesRole)
        no_btn = msg_box.addButton("否", QMessageBox.NoRole)
        
        if default_no:
            msg_box.setDefaultButton(no_btn)
        else:
            msg_box.setDefaultButton(yes_btn)
        
        msg_box.exec_()
        return msg_box.clickedButton() == yes_btn
    
    @staticmethod
    def information(parent, title, text):
        """信息对话框"""
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.addButton("确定", QMessageBox.AcceptRole)
        msg_box.exec_()
    
    @staticmethod
    def warning(parent, title, text):
        """警告对话框"""
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.addButton("确定", QMessageBox.AcceptRole)
        msg_box.exec_()
    
    @staticmethod
    def critical(parent, title, text):
        """错误对话框"""
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.addButton("确定", QMessageBox.AcceptRole)
        msg_box.exec_()


# 简化导入
MsgBox = ChineseMessageBox

