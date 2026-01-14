# -*- coding: utf-8 -*-
"""
智能解析器提取向导
支持选中文本自动生成正则、JSON可视化选择、常用模板等
"""
import re
import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel,
    QComboBox, QGroupBox, QTabWidget, QWidget,
    QTreeWidget, QTreeWidgetItem, QSplitter,
    QListWidget, QListWidgetItem, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QTextCursor, QTextCharFormat, QColor, QFont

from core.models import OutputParser
from .message_box import MsgBox


class SmartParserWizard(QDialog):
    """智能解析器提取向导"""
    
    parser_created = pyqtSignal(OutputParser)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.generated_parser = None
        self._init_ui()
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("智能提取向导")
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # 选项卡
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # 选项卡1：智能选择提取
        tabs.addTab(self._create_smart_select_tab(), "🎯 智能选择")
        
        # 选项卡2：JSON 提取
        tabs.addTab(self._create_json_tab(), "📋 JSON 提取")
        
        # 选项卡3：常用模板
        tabs.addTab(self._create_template_tab(), "📦 常用模板")
        
        # 底部：生成的规则预览
        preview_group = QGroupBox("生成的规则")
        preview_layout = QFormLayout(preview_group)
        
        self.var_name_edit = QLineEdit()
        self.var_name_edit.setPlaceholderText("输入变量名（将生成 {var_xxx}）")
        preview_layout.addRow("变量名:", self.var_name_edit)
        
        self.type_label = QLabel("regex")
        preview_layout.addRow("类型:", self.type_label)
        
        self.expression_edit = QLineEdit()
        self.expression_edit.setReadOnly(True)
        preview_layout.addRow("表达式:", self.expression_edit)
        
        self.preview_result = QLabel("（选择内容后显示提取结果）")
        self.preview_result.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        preview_layout.addRow("预览结果:", self.preview_result)
        
        layout.addWidget(preview_group)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        create_btn = QPushButton("创建规则")
        create_btn.clicked.connect(self._create_parser)
        btn_layout.addWidget(create_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _create_smart_select_tab(self):
        """创建智能选择选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明
        hint = QLabel("1. 粘贴示例输出  2. 选中要提取的内容  3. 点击「生成规则」")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)
        
        # 示例输出输入框
        layout.addWidget(QLabel("示例输出:"))
        self.sample_text = QTextEdit()
        self.sample_text.setPlaceholderText(
            "粘贴任务执行的输出内容，例如:\n\n"
            "Build completed successfully!\n"
            "Version: 1.2.3\n"
            "Total time: 45.6 seconds\n"
            "Files processed: 128\n\n"
            "然后用鼠标选中你想提取的部分（如 1.2.3 或 45.6）"
        )
        self.sample_text.setFont(QFont("Consolas", 10))
        self.sample_text.selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.sample_text)
        
        # 选中内容显示
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("选中内容:"))
        self.selected_text_label = QLabel("（请选中文本）")
        self.selected_text_label.setStyleSheet("color: #dcdcaa; font-family: Consolas;")
        select_layout.addWidget(self.selected_text_label, 1)
        
        gen_btn = QPushButton("生成规则")
        gen_btn.clicked.connect(self._generate_regex_from_selection)
        select_layout.addWidget(gen_btn)
        
        layout.addLayout(select_layout)
        
        # 高级选项
        adv_layout = QHBoxLayout()
        self.match_similar_cb = QCheckBox("匹配相似格式")
        self.match_similar_cb.setChecked(True)
        self.match_similar_cb.setToolTip("自动识别数字、字母等模式，生成通用规则")
        adv_layout.addWidget(self.match_similar_cb)
        
        self.use_context_cb = QCheckBox("使用上下文定位")
        self.use_context_cb.setChecked(True)
        self.use_context_cb.setToolTip("使用选中内容前后的文本作为定位锚点")
        adv_layout.addWidget(self.use_context_cb)
        
        adv_layout.addStretch()
        layout.addLayout(adv_layout)
        
        return widget
    
    def _create_json_tab(self):
        """创建 JSON 提取选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明
        hint = QLabel("粘贴 JSON 内容，点击树形节点自动生成 JSONPath")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)
        
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：JSON 输入
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("JSON 内容:"))
        self.json_input = QTextEdit()
        self.json_input.setPlaceholderText('{"code": 200, "data": {"msg": "success", "count": 42}}')
        self.json_input.setFont(QFont("Consolas", 10))
        left_layout.addWidget(self.json_input)
        
        parse_btn = QPushButton("解析 JSON")
        parse_btn.clicked.connect(self._parse_json)
        left_layout.addWidget(parse_btn)
        
        splitter.addWidget(left_widget)
        
        # 右侧：JSON 树
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        right_layout.addWidget(QLabel("点击选择要提取的字段:"))
        self.json_tree = QTreeWidget()
        self.json_tree.setHeaderLabels(["路径", "值"])
        self.json_tree.itemClicked.connect(self._on_json_item_clicked)
        right_layout.addWidget(self.json_tree)
        
        splitter.addWidget(right_widget)
        layout.addWidget(splitter)

        return widget

    def _create_template_tab(self):
        """创建常用模板选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        hint = QLabel("选择常用的提取模板，快速创建规则")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        # 模板列表
        self.template_list = QListWidget()
        self.template_list.itemClicked.connect(self._on_template_selected)

        # 添加常用模板
        templates = [
            ("📊 提取数字", "regex", r"(\d+)", "匹配任意数字"),
            ("📊 提取小数", "regex", r"(\d+\.\d+)", "匹配小数，如 3.14"),
            ("📊 提取百分比", "regex", r"(\d+(?:\.\d+)?%)", "匹配百分比，如 85.5%"),
            ("📝 提取引号内容", "regex", r'"([^"]+)"', "匹配双引号内的内容"),
            ("📝 提取单引号内容", "regex", r"'([^']+)'", "匹配单引号内的内容"),
            ("📝 提取括号内容", "regex", r"\(([^)]+)\)", "匹配圆括号内的内容"),
            ("📝 提取方括号内容", "regex", r"\[([^\]]+)\]", "匹配方括号内的内容"),
            ("🔗 提取 URL", "regex", r"(https?://[^\s]+)", "匹配 HTTP/HTTPS 链接"),
            ("🔗 提取 IP 地址", "regex", r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", "匹配 IPv4 地址"),
            ("📧 提取邮箱", "regex", r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", "匹配邮箱地址"),
            ("📅 提取日期 (YYYY-MM-DD)", "regex", r"(\d{4}-\d{2}-\d{2})", "匹配日期格式"),
            ("⏰ 提取时间 (HH:MM:SS)", "regex", r"(\d{2}:\d{2}:\d{2})", "匹配时间格式"),
            ("🏷️ 提取版本号", "regex", r"v?(\d+\.\d+(?:\.\d+)?)", "匹配版本号，如 1.2.3"),
            ("📋 提取键值对", "regex", r"(\w+)\s*[:=]\s*(.+)", "匹配 key: value 或 key=value"),
            ("✅ 提取状态词", "regex", r"(success|failed|error|ok|done|completed)", "匹配常见状态词（不区分大小写）"),
            ("📄 JSON: 提取 code 字段", "jsonpath", "$.code", "提取 JSON 中的 code 字段"),
            ("📄 JSON: 提取 message 字段", "jsonpath", "$.message", "提取 JSON 中的 message 字段"),
            ("📄 JSON: 提取 data 字段", "jsonpath", "$.data", "提取 JSON 中的 data 字段"),
            ("📄 JSON: 提取嵌套字段", "jsonpath", "$.data.result", "提取 JSON 中的嵌套字段"),
            ("📃 提取第一行", "line", "1", "提取输出的第一行"),
            ("📃 提取最后一行", "line", "-1", "提取输出的最后一行"),
        ]

        self._templates = templates
        for name, ptype, expr, desc in templates:
            item = QListWidgetItem(f"{name}\n    {desc}")
            item.setData(Qt.UserRole, (ptype, expr))
            self.template_list.addItem(item)

        layout.addWidget(self.template_list)

        # 测试区域
        test_layout = QHBoxLayout()
        test_layout.addWidget(QLabel("测试文本:"))
        self.template_test_input = QLineEdit()
        self.template_test_input.setPlaceholderText("输入测试文本，查看提取结果")
        self.template_test_input.textChanged.connect(self._test_template)
        test_layout.addWidget(self.template_test_input)

        self.template_test_result = QLabel("")
        self.template_test_result.setStyleSheet("color: #4ec9b0; min-width: 150px;")
        test_layout.addWidget(self.template_test_result)

        layout.addLayout(test_layout)

        return widget

    def _on_selection_changed(self):
        """文本选择变化"""
        cursor = self.sample_text.textCursor()
        selected = cursor.selectedText()
        if selected:
            # 限制显示长度
            display = selected if len(selected) <= 50 else selected[:50] + "..."
            self.selected_text_label.setText(f'"{display}"')
        else:
            self.selected_text_label.setText("（请选中文本）")

    def _generate_regex_from_selection(self):
        """根据选中内容智能生成正则表达式"""
        cursor = self.sample_text.textCursor()
        selected = cursor.selectedText()

        if not selected:
            MsgBox.warning(self, "提示", "请先选中要提取的内容")
            return

        full_text = self.sample_text.toPlainText()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()

        # 获取上下文
        context_before = full_text[max(0, start_pos - 30):start_pos]
        context_after = full_text[end_pos:min(len(full_text), end_pos + 30)]

        # 智能生成正则
        if self.match_similar_cb.isChecked():
            # 分析选中内容的模式
            pattern = self._analyze_pattern(selected)
        else:
            # 直接转义选中内容
            pattern = re.escape(selected)

        # 是否使用上下文定位
        if self.use_context_cb.isChecked() and (context_before.strip() or context_after.strip()):
            # 提取有意义的上下文锚点
            before_anchor = self._extract_anchor(context_before, is_before=True)
            after_anchor = self._extract_anchor(context_after, is_before=False)

            if before_anchor or after_anchor:
                if before_anchor and after_anchor:
                    regex = f"{re.escape(before_anchor)}\\s*({pattern})\\s*{re.escape(after_anchor)}"
                elif before_anchor:
                    regex = f"{re.escape(before_anchor)}\\s*({pattern})"
                else:
                    regex = f"({pattern})\\s*{re.escape(after_anchor)}"
            else:
                regex = f"({pattern})"
        else:
            regex = f"({pattern})"

        # 更新界面
        self.type_label.setText("regex")
        self.expression_edit.setText(regex)

        # 测试并显示结果
        self._test_and_preview(full_text, "regex", regex)

    def _analyze_pattern(self, text: str) -> str:
        """分析文本模式，生成通用正则"""
        # 纯数字
        if re.match(r'^\d+$', text):
            return r'\d+'

        # 小数
        if re.match(r'^\d+\.\d+$', text):
            return r'\d+\.\d+'

        # 版本号 (1.2.3)
        if re.match(r'^\d+\.\d+\.\d+$', text):
            return r'\d+\.\d+\.\d+'

        # 百分比
        if re.match(r'^\d+(?:\.\d+)?%$', text):
            return r'\d+(?:\.\d+)?%'

        # 日期 YYYY-MM-DD
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            return r'\d{4}-\d{2}-\d{2}'

        # 时间 HH:MM:SS
        if re.match(r'^\d{2}:\d{2}:\d{2}$', text):
            return r'\d{2}:\d{2}:\d{2}'

        # IP 地址
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', text):
            return r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'

        # URL
        if re.match(r'^https?://', text):
            return r'https?://[^\s]+'

        # 邮箱
        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', text):
            return r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

        # 纯字母
        if re.match(r'^[a-zA-Z]+$', text):
            return r'[a-zA-Z]+'

        # 字母数字混合
        if re.match(r'^[a-zA-Z0-9]+$', text):
            return r'[a-zA-Z0-9]+'

        # 带下划线的标识符
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', text):
            return r'[a-zA-Z_][a-zA-Z0-9_]*'

        # 默认：转义特殊字符，但保留基本结构
        # 将连续数字替换为 \d+，连续字母替换为 [a-zA-Z]+
        pattern = text
        pattern = re.sub(r'\d+', r'\\d+', pattern)

        # 转义其他特殊字符
        special_chars = r'[](){}.*+?^$|\\'
        for char in special_chars:
            if char in pattern and char != '\\':
                pattern = pattern.replace(char, '\\' + char)

        return pattern

    def _extract_anchor(self, context: str, is_before: bool) -> str:
        """从上下文中提取有意义的锚点"""
        if not context.strip():
            return ""

        # 查找最近的标识符或关键词
        if is_before:
            # 从后往前找
            # 查找 "key:" 或 "key=" 或 "key " 模式
            match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]?\s*$', context)
            if match:
                return match.group(0).strip()
            # 查找最后一个词
            match = re.search(r'(\S+)\s*$', context)
            if match:
                return match.group(1)
        else:
            # 从前往后找
            match = re.search(r'^\s*(\S+)', context)
            if match:
                word = match.group(1)
                # 如果是标点符号，返回它
                if len(word) <= 2:
                    return word

        return ""

    def _test_and_preview(self, text: str, parser_type: str, expression: str):
        """测试表达式并预览结果"""
        try:
            if parser_type == "regex":
                match = re.search(expression, text, re.IGNORECASE)
                if match:
                    result = match.group(1) if match.groups() else match.group(0)
                    self.preview_result.setText(f'✓ "{result}"')
                    self.preview_result.setStyleSheet("color: #4ec9b0; font-weight: bold;")
                else:
                    self.preview_result.setText("✗ 未匹配")
                    self.preview_result.setStyleSheet("color: #f14c4c; font-weight: bold;")
            elif parser_type == "jsonpath":
                try:
                    import jsonpath_ng
                    from jsonpath_ng import parse as jsonpath_parse
                    data = json.loads(text)
                    expr = jsonpath_parse(expression)
                    matches = [m.value for m in expr.find(data)]
                    if matches:
                        result = str(matches[0])
                        self.preview_result.setText(f'✓ "{result}"')
                        self.preview_result.setStyleSheet("color: #4ec9b0; font-weight: bold;")
                    else:
                        self.preview_result.setText("✗ 未匹配")
                        self.preview_result.setStyleSheet("color: #f14c4c; font-weight: bold;")
                except ImportError:
                    # 简单的 JSON 路径解析
                    data = json.loads(text)
                    result = self._simple_jsonpath(data, expression)
                    if result is not None:
                        self.preview_result.setText(f'✓ "{result}"')
                        self.preview_result.setStyleSheet("color: #4ec9b0; font-weight: bold;")
                    else:
                        self.preview_result.setText("✗ 未匹配")
                        self.preview_result.setStyleSheet("color: #f14c4c; font-weight: bold;")
        except Exception as e:
            self.preview_result.setText(f"✗ 错误: {str(e)[:30]}")
            self.preview_result.setStyleSheet("color: #f14c4c;")

    def _simple_jsonpath(self, data, path: str):
        """简单的 JSONPath 解析（不依赖外部库）"""
        # 移除 $ 前缀
        if path.startswith('$.'):
            path = path[2:]
        elif path.startswith('$'):
            path = path[1:]

        parts = path.split('.')
        current = data

        for part in parts:
            if not part:
                continue
            # 处理数组索引 [0]
            if '[' in part:
                key = part[:part.index('[')]
                idx = int(part[part.index('[')+1:part.index(']')])
                if key:
                    current = current.get(key, {})
                if isinstance(current, list) and len(current) > idx:
                    current = current[idx]
                else:
                    return None
            else:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None

            if current is None:
                return None

        return current

    def _parse_json(self):
        """解析 JSON 并构建树"""
        text = self.json_input.toPlainText().strip()
        if not text:
            MsgBox.warning(self, "提示", "请输入 JSON 内容")
            return

        try:
            data = json.loads(text)
            self.json_tree.clear()
            self._build_json_tree(data, self.json_tree.invisibleRootItem(), "$")
            self.json_tree.expandAll()
        except json.JSONDecodeError as e:
            MsgBox.warning(self, "JSON 解析错误", f"无效的 JSON 格式:\n{e}")

    def _build_json_tree(self, data, parent_item, path: str):
        """递归构建 JSON 树"""
        if isinstance(data, dict):
            for key, value in data.items():
                child_path = f"{path}.{key}"
                if isinstance(value, (dict, list)):
                    item = QTreeWidgetItem([key, f"({type(value).__name__})"])
                    item.setData(0, Qt.UserRole, child_path)
                    parent_item.addChild(item)
                    self._build_json_tree(value, item, child_path)
                else:
                    item = QTreeWidgetItem([key, str(value)])
                    item.setData(0, Qt.UserRole, child_path)
                    item.setForeground(1, QColor("#4ec9b0"))
                    parent_item.addChild(item)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                child_path = f"{path}[{i}]"
                if isinstance(value, (dict, list)):
                    item = QTreeWidgetItem([f"[{i}]", f"({type(value).__name__})"])
                    item.setData(0, Qt.UserRole, child_path)
                    parent_item.addChild(item)
                    self._build_json_tree(value, item, child_path)
                else:
                    item = QTreeWidgetItem([f"[{i}]", str(value)])
                    item.setData(0, Qt.UserRole, child_path)
                    item.setForeground(1, QColor("#4ec9b0"))
                    parent_item.addChild(item)

    def _on_json_item_clicked(self, item, column):
        """点击 JSON 树节点"""
        path = item.data(0, Qt.UserRole)
        if path:
            self.type_label.setText("jsonpath")
            self.expression_edit.setText(path)

            # 测试并预览
            text = self.json_input.toPlainText().strip()
            self._test_and_preview(text, "jsonpath", path)

    def _on_template_selected(self, item):
        """选择模板"""
        data = item.data(Qt.UserRole)
        if data:
            ptype, expr = data
            self.type_label.setText(ptype)
            self.expression_edit.setText(expr)

            # 测试
            self._test_template()

    def _test_template(self):
        """测试模板"""
        test_text = self.template_test_input.text()
        if not test_text:
            self.template_test_result.setText("")
            return

        expr = self.expression_edit.text()
        ptype = self.type_label.text()

        if not expr:
            return

        self._test_and_preview(test_text, ptype, expr)
        # 同步到模板测试结果
        self.template_test_result.setText(self.preview_result.text())

    def _create_parser(self):
        """创建解析器"""
        var_name = self.var_name_edit.text().strip()
        if not var_name:
            MsgBox.warning(self, "提示", "请输入变量名")
            return

        # 验证变量名格式
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', var_name):
            MsgBox.warning(self, "错误", "变量名只能包含字母、数字和下划线，且不能以数字开头")
            return

        expression = self.expression_edit.text().strip()
        if not expression:
            MsgBox.warning(self, "提示", "请先生成或选择一个表达式")
            return

        parser_type = self.type_label.text()

        self.generated_parser = OutputParser(
            var_name=var_name,
            parser_type=parser_type,
            expression=expression,
            enabled=True
        )

        self.accept()

    def get_parser(self) -> OutputParser:
        """获取生成的解析器"""
        return self.generated_parser

