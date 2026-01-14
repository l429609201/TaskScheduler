# -*- coding: utf-8 -*-
"""
输出解析器配置对话框
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QCheckBox, QPushButton,
    QComboBox, QLabel, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSplitter, QWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from core.models import OutputParser
from .message_box import MsgBox
from core.output_parser import OutputParserEngine


class ParserRuleDialog(QDialog):
    """单个解析规则编辑对话框"""
    
    def __init__(self, parent=None, parser: OutputParser = None):
        super().__init__(parent)
        self.parser = parser or OutputParser()
        self.is_edit = parser is not None
        
        self._init_ui()
        self._load_data()
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("编辑解析规则" if self.is_edit else "添加解析规则")
        self.setMinimumWidth(500)
        
        layout = QFormLayout(self)
        
        # 规则名称（用于全局模板）
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("规则名称（可选，用于全局模板识别）")
        layout.addRow("规则名称:", self.name_edit)
        
        # 变量名
        self.var_name_edit = QLineEdit()
        self.var_name_edit.setPlaceholderText("变量名，将生成 {var_xxx} 供 Webhook 使用")
        layout.addRow("变量名:", self.var_name_edit)
        
        # 解析类型
        type_layout = QHBoxLayout()
        self.type_combo = QComboBox()
        for pt in OutputParserEngine.get_parser_types():
            self.type_combo.addItem(pt["name"], pt["id"])
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        
        self.hint_label = QLabel()
        self.hint_label.setStyleSheet("color: gray; font-size: 11px;")
        type_layout.addWidget(self.hint_label, 1)
        layout.addRow("解析类型:", type_layout)
        
        # 表达式
        self.expression_edit = QLineEdit()
        self.expression_edit.setPlaceholderText("解析表达式")
        layout.addRow("表达式:", self.expression_edit)
        
        # 默认值
        self.default_edit = QLineEdit()
        self.default_edit.setPlaceholderText("解析失败时的默认值（可选）")
        layout.addRow("默认值:", self.default_edit)
        
        # 启用
        self.enabled_check = QCheckBox("启用此规则")
        self.enabled_check.setChecked(True)
        layout.addRow("", self.enabled_check)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addRow(btn_layout)
        
        self._on_type_changed()
    
    def _on_type_changed(self):
        """解析类型改变"""
        parser_types = OutputParserEngine.get_parser_types()
        current_id = self.type_combo.currentData()
        for pt in parser_types:
            if pt["id"] == current_id:
                self.hint_label.setText(pt["hint"])
                break
    
    def _load_data(self):
        """加载数据"""
        self.name_edit.setText(self.parser.name)
        self.var_name_edit.setText(self.parser.var_name)
        
        index = self.type_combo.findData(self.parser.parser_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        
        self.expression_edit.setText(self.parser.expression)
        self.default_edit.setText(self.parser.default_value)
        self.enabled_check.setChecked(self.parser.enabled)
    
    def _save(self):
        """保存"""
        var_name = self.var_name_edit.text().strip()
        if not var_name:
            MsgBox.warning(self, "错误", "请输入变量名")
            return

        # 变量名只能包含字母数字下划线
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', var_name):
            MsgBox.warning(self, "错误", "变量名只能包含字母、数字和下划线，且不能以数字开头")
            return

        expression = self.expression_edit.text().strip()
        if not expression:
            MsgBox.warning(self, "错误", "请输入解析表达式")
            return
        
        self.parser.name = self.name_edit.text().strip()
        self.parser.var_name = var_name
        self.parser.parser_type = self.type_combo.currentData()
        self.parser.expression = expression
        self.parser.default_value = self.default_edit.text()
        self.parser.enabled = self.enabled_check.isChecked()
        
        self.accept()
    
    def get_parser(self) -> OutputParser:
        """获取解析器对象"""
        return self.parser


class OutputParserDialog(QDialog):
    """输出解析器配置对话框（带测试功能）"""

    def __init__(self, parent=None, parsers: list = None, is_global: bool = False):
        super().__init__(parent)
        self.parsers = parsers or []
        self.is_global = is_global  # 是否为全局配置模式

        self._init_ui()
        self._refresh_table()

    def _init_ui(self):
        """初始化界面"""
        title = "全局解析器模板" if self.is_global else "输出解析配置"
        self.setWindowTitle(title)
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # 使用分割器
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)

        # 上半部分：规则列表
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 规则表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["变量名", "类型", "表达式", "默认值", "启用"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        top_layout.addWidget(self.table)

        # 按钮行
        btn_layout = QHBoxLayout()

        add_btn = QPushButton("添加规则")
        add_btn.clicked.connect(self._add_rule)
        btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_rule)
        btn_layout.addWidget(edit_btn)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_rule)
        btn_layout.addWidget(del_btn)

        btn_layout.addStretch()

        # 如果不是全局模式，添加从全局导入按钮
        if not self.is_global:
            import_btn = QPushButton("从全局模板导入")
            import_btn.clicked.connect(self._import_from_global)
            btn_layout.addWidget(import_btn)

        top_layout.addLayout(btn_layout)
        splitter.addWidget(top_widget)

        # 下半部分：测试区域
        test_group = QGroupBox("测试解析")
        test_layout = QVBoxLayout(test_group)

        test_layout.addWidget(QLabel("示例输出（粘贴任务执行的输出内容）:"))
        self.test_input = QTextEdit()
        self.test_input.setPlaceholderText('例如:\n{"code": 200, "data": {"msg": "success"}}\n或\nstatus: OK\nresult: 12345')
        self.test_input.setMaximumHeight(100)
        test_layout.addWidget(self.test_input)

        test_btn = QPushButton("测试解析")
        test_btn.clicked.connect(self._test_parse)
        test_layout.addWidget(test_btn)

        test_layout.addWidget(QLabel("解析结果:"))
        self.test_output = QTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMaximumHeight(100)
        test_layout.addWidget(self.test_output)

        splitter.addWidget(test_group)

        # 底部按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        layout.addLayout(bottom_layout)

    def _refresh_table(self):
        """刷新表格"""
        self.table.setRowCount(len(self.parsers))
        for row, p in enumerate(self.parsers):
            self.table.setItem(row, 0, QTableWidgetItem(f"{{var_{p.var_name}}}"))

            # 类型显示
            type_names = {"regex": "正则", "jsonpath": "JSON", "xpath": "XML", "line": "行", "split": "分隔"}
            self.table.setItem(row, 1, QTableWidgetItem(type_names.get(p.parser_type, p.parser_type)))

            expr_display = p.expression[:30] + "..." if len(p.expression) > 30 else p.expression
            self.table.setItem(row, 2, QTableWidgetItem(expr_display))
            self.table.setItem(row, 3, QTableWidgetItem(p.default_value or "-"))

            enabled_item = QTableWidgetItem("✓" if p.enabled else "✗")
            enabled_item.setForeground(QColor(0, 150, 0) if p.enabled else QColor(150, 150, 150))
            self.table.setItem(row, 4, enabled_item)

    def _add_rule(self):
        """添加规则"""
        dialog = ParserRuleDialog(self)
        if dialog.exec_():
            self.parsers.append(dialog.get_parser())
            self._refresh_table()

    def _edit_rule(self):
        """编辑规则"""
        row = self.table.currentRow()
        if row < 0:
            MsgBox.warning(self, "提示", "请先选择一个规则")
            return

        dialog = ParserRuleDialog(self, self.parsers[row])
        if dialog.exec_():
            self.parsers[row] = dialog.get_parser()
            self._refresh_table()

    def _delete_rule(self):
        """删除规则"""
        row = self.table.currentRow()
        if row < 0:
            MsgBox.warning(self, "提示", "请先选择一个规则")
            return

        if MsgBox.question(self, "确认删除", f"确定要删除规则 '{{var_{self.parsers[row].var_name}}}' 吗？"):
            del self.parsers[row]
            self._refresh_table()

    def _import_from_global(self):
        """从全局模板导入"""
        from core.models import ParserStorage
        storage = ParserStorage()
        global_parsers = storage.load_parsers()

        if not global_parsers:
            MsgBox.information(self, "提示", "没有全局解析器模板，请先在主界面添加")
            return

        # 显示选择对话框
        dialog = GlobalParserSelectDialog(self, global_parsers)
        if dialog.exec_():
            import copy
            for p in dialog.get_selected():
                # 检查是否已存在
                exists = any(ep.var_name == p.var_name for ep in self.parsers)
                if not exists:
                    self.parsers.append(copy.deepcopy(p))
            self._refresh_table()

    def _test_parse(self):
        """测试解析"""
        output = self.test_input.toPlainText()
        if not output:
            MsgBox.warning(self, "提示", "请输入示例输出")
            return

        if not self.parsers:
            MsgBox.warning(self, "提示", "请先添加解析规则")
            return

        results = OutputParserEngine.parse_all(output, self.parsers)

        # 格式化显示
        lines = []
        for var_name, value in results.items():
            if value:
                lines.append(f"✓ {{{var_name}}} = {value}")
            else:
                lines.append(f"✗ {{{var_name}}} = (未匹配)")

        self.test_output.setPlainText("\n".join(lines) if lines else "无解析结果")

    def get_parsers(self) -> list:
        """获取解析器列表"""
        return self.parsers


class GlobalParserSelectDialog(QDialog):
    """全局解析器选择对话框"""

    def __init__(self, parent=None, parsers: list = None):
        super().__init__(parent)
        self.parsers = parsers or []
        self.selected = []

        self._init_ui()

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("选择全局解析器")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("选择要导入的解析器模板:"))

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["选择", "名称", "变量名", "类型"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        self.table.setRowCount(len(self.parsers))
        self.checkboxes = []

        for row, p in enumerate(self.parsers):
            # 复选框
            cb = QCheckBox()
            self.checkboxes.append(cb)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, cb_widget)

            self.table.setItem(row, 1, QTableWidgetItem(p.name or f"规则{row+1}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{{var_{p.var_name}}}"))

            type_names = {"regex": "正则", "jsonpath": "JSON", "xpath": "XML", "line": "行", "split": "分隔"}
            self.table.setItem(row, 3, QTableWidgetItem(type_names.get(p.parser_type, p.parser_type)))

        layout.addWidget(self.table)

        # 全选/取消
        select_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self._set_all(True))
        select_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("取消全选")
        select_none_btn.clicked.connect(lambda: self._set_all(False))
        select_layout.addWidget(select_none_btn)

        select_layout.addStretch()
        layout.addLayout(select_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ok_btn = QPushButton("导入选中")
        ok_btn.clicked.connect(self._confirm)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _set_all(self, checked: bool):
        """全选/取消全选"""
        for cb in self.checkboxes:
            cb.setChecked(checked)

    def _confirm(self):
        """确认选择"""
        self.selected = []
        for i, cb in enumerate(self.checkboxes):
            if cb.isChecked():
                self.selected.append(self.parsers[i])

        if not self.selected:
            MsgBox.warning(self, "提示", "请至少选择一个解析器")
            return

        self.accept()

    def get_selected(self) -> list:
        """获取选中的解析器"""
        return self.selected

