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

        # 钉钉加签设置
        dingtalk_sign_layout = QHBoxLayout()
        self.dingtalk_sign_check = QCheckBox("钉钉加签")
        self.dingtalk_sign_check.setToolTip("启用钉钉机器人加签验证")
        self.dingtalk_sign_check.stateChanged.connect(self._on_dingtalk_sign_check_changed)
        dingtalk_sign_layout.addWidget(self.dingtalk_sign_check)

        self.dingtalk_sign_secret_edit = QLineEdit()
        self.dingtalk_sign_secret_edit.setPlaceholderText("SEC 开头的密钥")
        self.dingtalk_sign_secret_edit.setEnabled(False)
        dingtalk_sign_layout.addWidget(self.dingtalk_sign_secret_edit)
        form_layout.addRow("钉钉安全:", dingtalk_sign_layout)

        # 飞书签名校验设置
        feishu_sign_layout = QHBoxLayout()
        self.feishu_sign_check = QCheckBox("飞书签名")
        self.feishu_sign_check.setToolTip("启用飞书机器人签名校验")
        self.feishu_sign_check.stateChanged.connect(self._on_feishu_sign_check_changed)
        feishu_sign_layout.addWidget(self.feishu_sign_check)

        self.feishu_sign_secret_edit = QLineEdit()
        self.feishu_sign_secret_edit.setPlaceholderText("签名校验密钥")
        self.feishu_sign_secret_edit.setEnabled(False)
        feishu_sign_layout.addWidget(self.feishu_sign_secret_edit)
        form_layout.addRow("飞书安全:", feishu_sign_layout)

        self.headers_edit = QTextEdit()
        self.headers_edit.setPlaceholderText('可选，JSON格式，例如:\n{"Authorization": "Bearer token", "Content-Type": "application/json"}')
        self.headers_edit.setMaximumHeight(60)
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

    def _insert_variable(self, var_name: str):
        """插入变量到 Body 编辑框"""
        cursor = self.body_edit.textCursor()
        cursor.insertText(f"{{{var_name}}}")
        self.body_edit.setFocus()

    def _on_dingtalk_sign_check_changed(self, state):
        """钉钉加签复选框状态改变"""
        self.dingtalk_sign_secret_edit.setEnabled(state == Qt.Checked)

    def _on_feishu_sign_check_changed(self, state):
        """飞书签名复选框状态改变"""
        self.feishu_sign_secret_edit.setEnabled(state == Qt.Checked)

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

        # 钉钉加签处理
        if self.dingtalk_sign_check.isChecked():
            secret = self.dingtalk_sign_secret_edit.text().strip()
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
        self.body_edit.setPlainText(self.webhook.body_template)
        self.enabled_check.setChecked(self.webhook.enabled)
        # 加载钉钉加签配置
        self.dingtalk_sign_check.setChecked(self.webhook.dingtalk_sign_enabled)
        self.dingtalk_sign_secret_edit.setText(self.webhook.dingtalk_sign_secret)
        self.dingtalk_sign_secret_edit.setEnabled(self.webhook.dingtalk_sign_enabled)
        # 加载飞书签名配置
        self.feishu_sign_check.setChecked(self.webhook.feishu_sign_enabled)
        self.feishu_sign_secret_edit.setText(self.webhook.feishu_sign_secret)
        self.feishu_sign_secret_edit.setEnabled(self.webhook.feishu_sign_enabled)
    
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
        # 保存钉钉加签配置
        self.webhook.dingtalk_sign_enabled = self.dingtalk_sign_check.isChecked()
        self.webhook.dingtalk_sign_secret = self.dingtalk_sign_secret_edit.text().strip()
        # 保存飞书签名配置
        self.webhook.feishu_sign_enabled = self.feishu_sign_check.isChecked()
        self.webhook.feishu_sign_secret = self.feishu_sign_secret_edit.text().strip()

        self.accept()
    
    def get_webhook(self) -> WebhookConfig:
        """获取 Webhook 对象"""
        return self.webhook

