# -*- coding: utf-8 -*-
"""
Webhook 通知模块
"""
import json
import re
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor
import logging
from dataclasses import dataclass

from .models import WebhookConfig

logger = logging.getLogger(__name__)


@dataclass
class WebhookResult:
    """Webhook 调用结果"""
    webhook_name: str
    success: bool
    status_code: Optional[int] = None
    response: Optional[str] = None
    error: Optional[str] = None


class WebhookNotifier:
    """Webhook 通知器"""

    def __init__(self, max_workers: int = 5, timeout: int = 30):
        """
        初始化通知器

        Args:
            max_workers: 最大并发数
            timeout: 请求超时时间（秒）
        """
        self.max_workers = max_workers
        self.timeout = timeout
        # 使用两个独立的线程池，避免死锁
        # _async_executor: 用于 notify_async 的异步调度
        # _send_executor: 用于实际发送 webhook 请求
        self._async_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="webhook_async")
        self._send_executor = ThreadPoolExecutor(max_workers=max_workers * 2, thread_name_prefix="webhook_send")
    
    def _replace_variables(self, template: str, params: Dict[str, Any]) -> str:
        """
        替换模板中的变量

        支持的变量格式: {variable_name}
        """
        result = template
        for key, value in params.items():
            placeholder = "{" + key + "}"
            # 对于字符串值，需要转义 JSON 特殊字符
            if isinstance(value, str):
                # 转义 JSON 特殊字符
                # 注意：换行符需要转义为 \\n 才能在 JSON 字符串中正确表示
                escaped_value = (value
                    .replace('\\', '\\\\')  # 反斜杠
                    .replace('"', '\\"')     # 双引号
                    .replace('\n', '\\n')    # 换行符 -> JSON 转义
                    .replace('\r', '')       # 移除回车
                    .replace('\t', '    ')   # Tab 转空格
                )
                result = result.replace(placeholder, escaped_value)
            else:
                result = result.replace(placeholder, str(value))
        return result
    
    def _generate_dingtalk_sign(self, secret: str) -> tuple:
        """生成钉钉加签参数"""
        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return timestamp, sign

    def _generate_feishu_sign(self, secret: str) -> tuple:
        """生成飞书签名校验参数"""
        timestamp = str(int(time.time()))
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return timestamp, sign

    def _send_webhook(self, webhook: WebhookConfig, params: Dict[str, Any]) -> WebhookResult:
        """发送单个 webhook"""
        if not webhook.enabled:
            return WebhookResult(
                webhook_name=webhook.name,
                success=False,
                error="Webhook is disabled"
            )

        try:
            # 替换 body 模板中的变量
            body = self._replace_variables(webhook.body_template, params)

            # 调试：记录替换后的 body
            logger.debug(f"Webhook body after variable replacement: {body[:500]}...")

            # 处理 URL 和 body（加签）
            url = webhook.url

            # 钉钉加签
            if webhook.dingtalk_sign_enabled and webhook.dingtalk_sign_secret:
                timestamp, sign = self._generate_dingtalk_sign(webhook.dingtalk_sign_secret)
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}timestamp={timestamp}&sign={sign}"

            # 飞书签名校验
            if webhook.feishu_sign_enabled and webhook.feishu_sign_secret:
                timestamp, sign = self._generate_feishu_sign(webhook.feishu_sign_secret)
                # 飞书需要在 body 中添加 timestamp 和 sign
                try:
                    body_dict = json.loads(body)
                    body_dict['timestamp'] = timestamp
                    body_dict['sign'] = sign
                    body = json.dumps(body_dict, ensure_ascii=False)
                except json.JSONDecodeError:
                    # 如果 body 不是有效 JSON，跳过签名
                    pass

            # 设置默认 headers
            headers = {'Content-Type': 'application/json'}
            headers.update(webhook.headers)

            # 发送请求
            method = webhook.method.upper()
            if method == 'GET':
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=self.timeout
                )
            elif method == 'POST':
                response = requests.post(
                    url,
                    data=body.encode('utf-8'),
                    headers=headers,
                    timeout=self.timeout
                )
            elif method == 'PUT':
                response = requests.put(
                    url,
                    data=body.encode('utf-8'),
                    headers=headers,
                    timeout=self.timeout
                )
            else:
                return WebhookResult(
                    webhook_name=webhook.name,
                    success=False,
                    error=f"Unsupported method: {method}"
                )
            
            success = 200 <= response.status_code < 300
            logger.info(f"Webhook '{webhook.name}' 发送{'成功' if success else '失败'}, 状态码: {response.status_code}")
            return WebhookResult(
                webhook_name=webhook.name,
                success=success,
                status_code=response.status_code,
                response=response.text[:500] if response.text else None
            )
            
        except requests.Timeout:
            return WebhookResult(
                webhook_name=webhook.name,
                success=False,
                error="Request timeout"
            )
        except requests.RequestException as e:
            return WebhookResult(
                webhook_name=webhook.name,
                success=False,
                error=str(e)
            )
        except Exception as e:
            logger.exception(f"Webhook error: {webhook.name}")
            return WebhookResult(
                webhook_name=webhook.name,
                success=False,
                error=str(e)
            )
    
    def notify(self, webhooks: List[WebhookConfig], params: Dict[str, Any]) -> List[WebhookResult]:
        """
        发送多个 webhook 通知

        Args:
            webhooks: webhook 配置列表
            params: 通知参数

        Returns:
            List[WebhookResult]: 调用结果列表
        """
        if not webhooks:
            return []

        # 过滤启用的 webhooks
        enabled_webhooks = [w for w in webhooks if w.enabled]
        if not enabled_webhooks:
            logger.debug(f"没有启用的 webhook，跳过发送")
            return []

        logger.info(f"准备发送 {len(enabled_webhooks)} 个 webhook 通知")

        # 使用 _send_executor 并发发送（避免与 notify_async 的线程池冲突）
        futures = []
        for webhook in enabled_webhooks:
            future = self._send_executor.submit(self._send_webhook, webhook, params)
            futures.append((webhook.name, future))

        # 收集结果
        results = []
        for webhook_name, future in futures:
            try:
                result = future.result(timeout=self.timeout + 5)
                results.append(result)
            except Exception as e:
                logger.error(f"Webhook '{webhook_name}' 发送异常: {e}")
                results.append(WebhookResult(
                    webhook_name=webhook_name,
                    success=False,
                    error=str(e)
                ))

        return results

    def notify_async(self, webhooks: List[WebhookConfig], params: Dict[str, Any],
                     callback: callable = None):
        """
        异步发送 webhook 通知

        Args:
            webhooks: webhook 配置列表
            params: 通知参数
            callback: 完成回调函数，接收 List[WebhookResult] 参数
        """
        def _task():
            results = self.notify(webhooks, params)
            if callback:
                callback(results)

        # 使用 _async_executor 进行异步调度
        self._async_executor.submit(_task)

    def shutdown(self):
        """关闭执行器"""
        self._async_executor.shutdown(wait=False)
        self._send_executor.shutdown(wait=False)

