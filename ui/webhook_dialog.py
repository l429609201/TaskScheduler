# -*- coding: utf-8 -*-
"""
Webhook 配置对话框（全局配置）
"""
import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QTextEdit, QCheckBox, QPushButton,
    QComboBox, QLabel, QGroupBox, QScrollArea, QWidget, QFrame
)
from PyQt5.QtCore import Qt

from core.models import WebhookConfig
from .message_box import MsgBox


class WebhookConfigDialog(QDialog):
    """Webhook 配置编辑对话框"""
    
    def __init__(self, parent=None, webhook: WebhookConfig = None):
        super().__init__(parent)
        self.webhook = webhook or WebhookConfig()
        self.is_edit = webhook is not None
        
        self._init_ui()
        self._load_data()
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("编辑 Webhook 配置" if self.is_edit else "添加 Webhook 配置")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)

        layout = QVBoxLayout(self)

        # 基本信息
        form_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("配置名称，例如：钉钉通知、企业微信")
        form_layout.addRow("名称:", self.name_edit)

        url_layout = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/webhook")
        url_layout.addWidget(self.url_edit)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["POST", "GET", "PUT"])
        self.method_combo.setFixedWidth(80)
        url_layout.addWidget(self.method_combo)

        test_btn = QPushButton("🧪 测试")
        test_btn.setFixedWidth(70)
        test_btn.clicked.connect(self._test_webhook)
        url_layout.addWidget(test_btn)

        form_layout.addRow("URL:", url_layout)

        # 安全类型选择（统一管理钉钉和飞书签名）
        security_layout = QHBoxLayout()
        self.security_type_combo = QComboBox()
        self.security_type_combo.addItems(["无", "钉钉安全", "飞书安全"])
        self.security_type_combo.currentIndexChanged.connect(self._on_security_type_changed)
        self.security_type_combo.setFixedWidth(120)
        security_layout.addWidget(self.security_type_combo)

        self.security_secret_edit = QLineEdit()
        self.security_secret_edit.setPlaceholderText("请选择安全类型后输入对应密钥")
        self.security_secret_edit.setEnabled(False)
        security_layout.addWidget(self.security_secret_edit)
        form_layout.addRow("安全设置:", security_layout)

        self.headers_edit = QTextEdit()
        self.headers_edit.setPlaceholderText('可选，JSON格式，例如:\n{"Authorization": "Bearer token", "Content-Type": "application/json"}')
        self.headers_edit.setMaximumHeight(60)
        self.headers_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.headers_edit.customContextMenuRequested.connect(lambda pos: self._show_context_menu(self.headers_edit, pos))
        form_layout.addRow("Headers:", self.headers_edit)

        layout.addLayout(form_layout)

        # Body 模板区域
        body_header = QHBoxLayout()
        body_label = QLabel("Body模板:")
        body_label.setStyleSheet("font-weight: bold;")
        body_header.addWidget(body_label)
        body_header.addStretch()
        layout.addLayout(body_header)

        # Body 编辑区和变量按钮区
        body_layout = QHBoxLayout()

        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText(
            '请求体模板，支持变量替换，例如:\n'
            '{\n'
            '  "task": "{task_name}",\n'
            '  "status": "{status_cn}",\n'
            '  "message": "任务执行{status_cn}，耗时 {duration_str}"\n'
            '}'
        )
        self.body_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.body_edit.customContextMenuRequested.connect(lambda pos: self._show_context_menu(self.body_edit, pos))
        body_layout.addWidget(self.body_edit, 2)

        # 变量快捷按钮区
        var_widget = self._create_variable_buttons()
        body_layout.addWidget(var_widget, 1)

        layout.addLayout(body_layout)

        self.enabled_check = QCheckBox("启用此配置")
        self.enabled_check.setChecked(True)
        layout.addWidget(self.enabled_check)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _create_variable_buttons(self) -> QWidget:
        """创建变量快捷按钮区"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumWidth(220)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)

        # 变量分组
        var_groups = [
            ("📋 基础参数", [
                ("task_name", "任务名称"),
                ("status", "状态(en)"),
                ("status_cn", "状态(中文)"),
                ("exit_code", "退出码"),
            ]),
            ("📝 输出参数", [
                ("output", "标准输出"),
                ("output_first_line", "首行输出"),
                ("output_last_line", "末行输出"),
                ("error", "错误输出"),
            ]),
            ("⏰ 时间参数", [
                ("start_time_fmt", "开始时间"),
                ("end_time_fmt", "结束时间"),
                ("duration_str", "执行时长"),
                ("date", "日期"),
            ]),
            ("🖥️ 环境参数", [
                ("hostname", "主机名"),
                ("username", "用户名"),
            ]),
            ("📁 同步参数", [
                ("source_path", "源路径"),
                ("target_path", "目标路径"),
                ("sync_mode", "同步模式"),
                ("copied_files", "复制数"),
                ("updated_files", "更新数"),
                ("deleted_files", "删除数"),
                ("failed_files", "失败数"),
                ("total_files", "总文件数"),
                ("transferred_size", "传输大小"),
                ("summary", "摘要"),
                ("file_list_short", "文件列表(短)"),
            ]),
        ]

        for group_name, variables in var_groups:
            # 分组标题
            group_label = QLabel(group_name)
            group_label.setStyleSheet("font-weight: bold; color: #555; margin-top: 5px;")
            layout.addWidget(group_label)

            # 变量按钮网格
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, (var_name, var_desc) in enumerate(variables):
                btn = QPushButton(var_desc)
                btn.setToolTip(f"{{{var_name}}}")
                btn.setFixedHeight(24)
                btn.setStyleSheet("QPushButton { font-size: 11px; padding: 2px 4px; }")
                btn.clicked.connect(lambda checked, v=var_name: self._insert_variable(v))
                grid.addWidget(btn, i // 2, i % 2)
            layout.addLayout(grid)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _show_context_menu(self, text_edit: QTextEdit, pos):
        """显示汉化的右键菜单"""
        from PyQt5.QtWidgets import QMenu

        menu = QMenu(self)

        # 撤销/重做
        undo_action = menu.addAction("撤销")
        undo_action.setEnabled(text_edit.document().isUndoAvailable())
        undo_action.triggered.connect(text_edit.undo)

        redo_action = menu.addAction("重做")
        redo_action.setEnabled(text_edit.document().isRedoAvailable())
        redo_action.triggered.connect(text_edit.redo)

        menu.addSeparator()

        # 剪切/复制/粘贴
        cut_action = menu.addAction("剪切")
        cut_action.setEnabled(text_edit.textCursor().hasSelection())
        cut_action.triggered.connect(text_edit.cut)

        copy_action = menu.addAction("复制")
        copy_action.setEnabled(text_edit.textCursor().hasSelection())
        copy_action.triggered.connect(text_edit.copy)

        paste_action = menu.addAction("粘贴")
        paste_action.triggered.connect(text_edit.paste)

        delete_action = menu.addAction("删除")
        delete_action.setEnabled(text_edit.textCursor().hasSelection())
        delete_action.triggered.connect(lambda: text_edit.textCursor().removeSelectedText())

        menu.addSeparator()

        # 全选
        select_all_action = menu.addAction("全选")
        select_all_action.triggered.connect(text_edit.selectAll)

        menu.exec_(text_edit.mapToGlobal(pos))

    def _insert_variable(self, var_name: str):
        """插入变量到 Body 编辑框"""
        cursor = self.body_edit.textCursor()
        cursor.insertText(f"{{{var_name}}}")
        self.body_edit.setFocus()

    def _on_security_type_changed(self, index):
        """安全类型改变时的回调"""
        if index == 0:  # 无
            self.security_secret_edit.setEnabled(False)
            self.security_secret_edit.setPlaceholderText("无需密钥")
            self.security_secret_edit.clear()
        elif index == 1:  # 钉钉安全
            self.security_secret_edit.setEnabled(True)
            self.security_secret_edit.setPlaceholderText("SEC 开头的钉钉加签密钥")
        elif index == 2:  # 飞书安全
            self.security_secret_edit.setEnabled(True)
            self.security_secret_edit.setPlaceholderText("飞书签名校验密钥")

    def _generate_dingtalk_sign(self, secret: str) -> tuple:
        """生成钉钉加签参数"""
        import time
        import hmac
        import hashlib
        import base64
        import urllib.parse

        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return timestamp, sign

    def _generate_feishu_sign(self, secret: str) -> tuple:
        """生成飞书签名校验参数"""
        import time
        import hmac
        import hashlib
        import base64

        timestamp = str(int(time.time()))
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return timestamp, sign

    def _test_webhook(self):
        """测试 Webhook"""
        url = self.url_edit.text().strip()
        if not url:
            MsgBox.warning(self, "提示", "请先输入 URL")
            return

        # 安全处理
        security_type = self.security_type_combo.currentIndex()
        if security_type == 1:  # 钉钉安全
            secret = self.security_secret_edit.text().strip()
            if not secret:
                MsgBox.warning(self, "提示", "请输入钉钉加签密钥")
                return
            timestamp, sign = self._generate_dingtalk_sign(secret)
            # 添加签名参数到 URL
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}timestamp={timestamp}&sign={sign}"

        # 解析 headers
        headers = {'Content-Type': 'application/json'}
        headers_text = self.headers_edit.toPlainText().strip()
        if headers_text:
            try:
                headers.update(json.loads(headers_text))
            except json.JSONDecodeError:
                MsgBox.warning(self, "错误", "Headers 格式错误")
                return

        # 构建测试参数
        from datetime import datetime
        test_params = {
            'task_name': '测试任务',
            'status': 'success',
            'status_cn': '成功',
            'exit_code': 0,
            'output': '这是测试输出内容',
            'output_first_line': '第一行输出',
            'output_last_line': '最后一行输出',
            'error': '',
            'start_time_fmt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'end_time_fmt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'duration_str': '1.5秒',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'hostname': 'test-host',
            'username': 'test-user',
            'source_path': 'C:/source',
            'target_path': 'D:/target',
            'sync_mode': 'mirror',
            'copied_files': 5,
            'updated_files': 3,
            'deleted_files': 1,
            'failed_files': 0,
            'total_files': 9,
            'transferred_size': '1.5 MB',
            'summary': '复制:5 更新:3 删除:1 失败:0',
            'file_list_short': 'file1.txt, file2.txt, file3.txt',
        }

        # 替换模板变量
        body_template = self.body_edit.toPlainText()
        body = body_template
        for key, value in test_params.items():
            body = body.replace(f"{{{key}}}", str(value))

        # 飞书签名处理（在 body 中添加 timestamp 和 sign）
        if security_type == 2:  # 飞书安全
            secret = self.security_secret_edit.text().strip()
            if not secret:
                MsgBox.warning(self, "提示", "请输入飞书签名密钥")
                return
            timestamp, sign = self._generate_feishu_sign(secret)
            # 飞书需要在 body 中添加 timestamp 和 sign
            try:
                body_dict = json.loads(body)
                body_dict['timestamp'] = timestamp
                body_dict['sign'] = sign
                body = json.dumps(body_dict, ensure_ascii=False)
            except json.JSONDecodeError:
                MsgBox.warning(self, "错误", "飞书签名要求 Body 必须是有效的 JSON 格式")
                return

        # 发送测试请求
        import requests
        method = self.method_combo.currentText()

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, data=body.encode('utf-8'), headers=headers, timeout=10)
            else:
                MsgBox.warning(self, "错误", f"不支持的方法: {method}")
                return

            if response.status_code < 400:
                MsgBox.information(
                    self, "测试成功",
                    f"✅ 请求成功！\n\n"
                    f"状态码: {response.status_code}\n"
                    f"响应: {response.text[:500]}"
                )
            else:
                MsgBox.warning(
                    self, "测试失败",
                    f"❌ 请求失败\n\n"
                    f"状态码: {response.status_code}\n"
                    f"响应: {response.text[:500]}"
                )
        except requests.exceptions.Timeout:
            MsgBox.warning(self, "测试失败", "请求超时（10秒）")
        except requests.exceptions.ConnectionError as e:
            MsgBox.warning(self, "测试失败", f"连接失败: {str(e)}")
        except Exception as e:
            MsgBox.warning(self, "测试失败", f"发生错误: {str(e)}")
    
    def _load_data(self):
        """加载数据"""
        self.name_edit.setText(self.webhook.name)
        self.url_edit.setText(self.webhook.url)
        self.method_combo.setCurrentText(self.webhook.method)
        if self.webhook.headers:
            self.headers_edit.setPlainText(json.dumps(self.webhook.headers, indent=2, ensure_ascii=False))

        # 设置默认 Body 模板（如果为空）
        body_template = self.webhook.body_template
        if not body_template or body_template == '{"task": "{task_name}", "status": "{status}", "output": "{output}", "exit_code": {exit_code}}':
            # 使用新的钉钉 Markdown 模板
            body_template = '''{
  "msgtype": "markdown",
  "markdown": {
    "title": "{status_icon} {task_name} 同步 {status_cn}",
    "text": "## {status_icon} {task_name} 同步{status_cn}\\n\\n**基本信息**\\n- 🕐 开始时间: {start_time_fmt}\\n- ⏱️ 耗时: {duration_str}\\n- 🖥️ 源服务器: {source_server}\\n- 📂 源路径: {source_path}\\n- 📁 目标路径: {target_path}\\n- 🔄 同步模式: {sync_mode}\\n\\n**同步统计**\\n- ✅ 复制: {copied_files} 个\\n- 🔄 更新: {updated_files} 个\\n- 🗑️ 删除: {deleted_files} 个\\n- ⏭️ 相同: {unchanged_files} 个\\n- ❌ 失败: {failed_files} 个\\n- 📊 传输大小: {transferred_size}\\n\\n**{sync_message}**\\n\\n**文件列表**\\n```\\n{file_list}\\n```"
  }
}'''

        self.body_edit.setPlainText(body_template)
        self.enabled_check.setChecked(self.webhook.enabled)

        # 加载安全配置
        if self.webhook.dingtalk_sign_enabled:
            self.security_type_combo.setCurrentIndex(1)  # 钉钉安全
            self.security_secret_edit.setText(self.webhook.dingtalk_sign_secret)
        elif self.webhook.feishu_sign_enabled:
            self.security_type_combo.setCurrentIndex(2)  # 飞书安全
            self.security_secret_edit.setText(self.webhook.feishu_sign_secret)
        else:
            self.security_type_combo.setCurrentIndex(0)  # 无
    
    def _show_variables_help(self):
        """显示变量帮助"""
        help_text = """
<h3>可用变量列表</h3>
<p><b>基础参数:</b></p>
<ul>
<li><code>{task_name}</code> - 任务名称</li>
<li><code>{status}</code> - 状态 (success/failed)</li>
<li><code>{status_cn}</code> - 状态中文 (成功/失败)</li>
<li><code>{exit_code}</code> - 退出码</li>
</ul>
<p><b>输出参数:</b></p>
<ul>
<li><code>{output}</code> - 标准输出 (前2000字符)</li>
<li><code>{output_first_line}</code> - 输出第一行</li>
<li><code>{output_last_line}</code> - 输出最后一行</li>
<li><code>{error}</code> - 错误输出</li>
</ul>
<p><b>时间参数:</b></p>
<ul>
<li><code>{start_time_fmt}</code> - 开始时间</li>
<li><code>{end_time_fmt}</code> - 结束时间</li>
<li><code>{duration_str}</code> - 执行时长</li>
<li><code>{date}</code> - 日期</li>
</ul>
<p><b>环境参数:</b></p>
<ul>
<li><code>{hostname}</code> - 主机名</li>
<li><code>{username}</code> - 用户名</li>
</ul>
<p><b>自定义变量:</b></p>
<p>脚本输出 <code>KEY=VALUE</code> 格式会自动解析为 <code>{var_KEY}</code></p>
"""
        MsgBox.information(self, "可用变量", help_text)
    
    def _save(self):
        """保存"""
        name = self.name_edit.text().strip()
        if not name:
            MsgBox.warning(self, "错误", "请输入配置名称")
            return

        url = self.url_edit.text().strip()
        if not url:
            MsgBox.warning(self, "错误", "请输入 URL")
            return
        
        # 解析 headers
        headers = {}
        headers_text = self.headers_edit.toPlainText().strip()
        if headers_text:
            try:
                headers = json.loads(headers_text)
            except json.JSONDecodeError:
                MsgBox.warning(self, "错误", "Headers 格式错误，请使用 JSON 格式")
                return
        
        self.webhook.name = name
        self.webhook.url = url
        self.webhook.method = self.method_combo.currentText()
        self.webhook.headers = headers
        self.webhook.body_template = self.body_edit.toPlainText()
        self.webhook.enabled = self.enabled_check.isChecked()

        # 保存安全配置
        security_type = self.security_type_combo.currentIndex()
        if security_type == 1:  # 钉钉安全
            self.webhook.dingtalk_sign_enabled = True
            self.webhook.dingtalk_sign_secret = self.security_secret_edit.text().strip()
            self.webhook.feishu_sign_enabled = False
            self.webhook.feishu_sign_secret = ""
        elif security_type == 2:  # 飞书安全
            self.webhook.feishu_sign_enabled = True
            self.webhook.feishu_sign_secret = self.security_secret_edit.text().strip()
            self.webhook.dingtalk_sign_enabled = False
            self.webhook.dingtalk_sign_secret = ""
        else:  # 无
            self.webhook.dingtalk_sign_enabled = False
            self.webhook.dingtalk_sign_secret = ""
            self.webhook.feishu_sign_enabled = False
            self.webhook.feishu_sign_secret = ""

        self.accept()
    
    def get_webhook(self) -> WebhookConfig:
        """获取 Webhook 对象"""
        return self.webhook

