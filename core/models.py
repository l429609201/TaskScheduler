# -*- coding: utf-8 -*-
"""
任务数据模型定义
"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime
import os


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待执行
    RUNNING = "running"      # 正在执行
    SUCCESS = "success"      # 执行成功
    FAILED = "failed"        # 执行失败
    DISABLED = "disabled"    # 已禁用


class TaskType(Enum):
    """任务类型枚举"""
    COMMAND = "command"      # 命令任务（原有功能）
    SYNC = "sync"            # 文件同步任务


class ConnectionType(Enum):
    """连接类型枚举"""
    LOCAL = "local"          # 本地文件系统
    FTP = "ftp"              # FTP 连接
    SFTP = "sftp"            # SFTP/SSH 连接


class SyncMode(Enum):
    """同步模式枚举"""
    MIRROR = "mirror"        # 镜像同步：源→目标，删除目标多余文件
    UPDATE = "update"        # 更新同步：只复制新文件和更新的文件
    TWO_WAY = "two_way"      # 双向同步：双向合并，保留两边的更新
    BACKUP = "backup"        # 备份模式：只复制，不删除


class CompareMethod(Enum):
    """文件比较方式枚举"""
    TIME = "time"            # 按修改时间比较
    SIZE = "size"            # 按文件大小比较
    TIME_SIZE = "time_size"  # 按时间和大小比较
    HASH = "hash"            # 按内容哈希比较（MD5）


@dataclass
class ConnectionConfig:
    """连接配置"""
    type: ConnectionType = ConnectionType.LOCAL
    # 本地路径或远程路径
    path: str = ""
    # FTP/SFTP 配置
    host: str = ""
    port: int = 21           # FTP: 21, SFTP: 22
    username: str = ""
    password: str = ""       # 注意：生产环境应加密存储
    # SFTP 私钥路径（可选）
    private_key_path: str = ""
    # 连接超时（秒）
    timeout: int = 30
    # 被动模式（FTP）
    passive_mode: bool = True

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['type'] = self.type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConnectionConfig':
        data = data.copy()
        data['type'] = ConnectionType(data.get('type', 'local'))
        return cls(**data)

    def get_display_name(self) -> str:
        """获取显示名称"""
        if self.type == ConnectionType.LOCAL:
            return f"本地: {self.path}"
        elif self.type == ConnectionType.FTP:
            return f"FTP: {self.username}@{self.host}:{self.port}{self.path}"
        elif self.type == ConnectionType.SFTP:
            return f"SFTP: {self.username}@{self.host}:{self.port}{self.path}"
        return self.path


@dataclass
class SyncFilterRule:
    """同步过滤规则"""
    # 包含的文件模式（如 *.txt, *.py）
    include_patterns: List[str] = field(default_factory=list)
    # 排除的文件模式
    exclude_patterns: List[str] = field(default_factory=list)
    # 排除的目录
    exclude_dirs: List[str] = field(default_factory=lambda: ['.git', '__pycache__', 'node_modules', '.svn'])
    # 最小文件大小（字节，0表示不限制）
    min_size: int = 0
    # 最大文件大小（字节，0表示不限制）
    max_size: int = 0
    # 是否同步隐藏文件
    include_hidden: bool = False
    # 时间过滤类型: none, today, yesterday, days_3, days_7, days_30, custom
    time_filter_type: str = "none"
    # 自定义时间范围 - 开始时间 (ISO格式字符串，如 "2024-01-01T00:00:00")
    time_filter_start: Optional[str] = None
    # 自定义时间范围 - 结束时间
    time_filter_end: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SyncFilterRule':
        return cls(**data)

    def get_time_range(self) -> tuple:
        """获取时间过滤范围，返回 (start_datetime, end_datetime) 或 (None, None)"""
        from datetime import datetime, timedelta

        if self.time_filter_type == "none":
            return (None, None)

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self.time_filter_type == "today":
            return (today_start, now)
        elif self.time_filter_type == "yesterday":
            yesterday_start = today_start - timedelta(days=1)
            return (yesterday_start, today_start)
        elif self.time_filter_type == "days_3":
            return (today_start - timedelta(days=3), now)
        elif self.time_filter_type == "days_7":
            return (today_start - timedelta(days=7), now)
        elif self.time_filter_type == "days_30":
            return (today_start - timedelta(days=30), now)
        elif self.time_filter_type == "custom":
            start = datetime.fromisoformat(self.time_filter_start) if self.time_filter_start else None
            end = datetime.fromisoformat(self.time_filter_end) if self.time_filter_end else None
            return (start, end)

        return (None, None)


@dataclass
class SyncConfig:
    """同步任务配置"""
    # 源端配置
    source: ConnectionConfig = field(default_factory=ConnectionConfig)
    # 目标端配置
    target: ConnectionConfig = field(default_factory=ConnectionConfig)
    # 同步模式
    sync_mode: SyncMode = SyncMode.UPDATE
    # 比较方式
    compare_method: CompareMethod = CompareMethod.TIME_SIZE
    # 过滤规则
    filter_rule: SyncFilterRule = field(default_factory=SyncFilterRule)
    # 是否删除目标端多余文件（仅 MIRROR 模式有效）
    delete_extra: bool = False
    # 同步前是否先比较（显示差异）
    preview_before_sync: bool = True
    # 是否保留目录结构
    preserve_structure: bool = True
    # 冲突处理策略: "source" 源优先, "target" 目标优先, "newer" 较新优先, "skip" 跳过
    conflict_resolution: str = "newer"
    # 失败后是否继续
    continue_on_error: bool = True
    # 最大并发传输数（默认 2，提高稳定性）
    max_concurrent: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source.to_dict(),
            'target': self.target.to_dict(),
            'sync_mode': self.sync_mode.value,
            'compare_method': self.compare_method.value,
            'filter_rule': self.filter_rule.to_dict(),
            'delete_extra': self.delete_extra,
            'preview_before_sync': self.preview_before_sync,
            'preserve_structure': self.preserve_structure,
            'conflict_resolution': self.conflict_resolution,
            'continue_on_error': self.continue_on_error,
            'max_concurrent': self.max_concurrent
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SyncConfig':
        data = data.copy()
        data['source'] = ConnectionConfig.from_dict(data.get('source', {}))
        data['target'] = ConnectionConfig.from_dict(data.get('target', {}))
        data['sync_mode'] = SyncMode(data.get('sync_mode', 'update'))
        data['compare_method'] = CompareMethod(data.get('compare_method', 'time_size'))
        data['filter_rule'] = SyncFilterRule.from_dict(data.get('filter_rule', {}))
        return cls(**data)


@dataclass
class AppSettings:
    """应用程序设置"""
    # 日志设置
    log_enabled: bool = True
    log_dir: str = "logs"
    log_retention_days: int = 30  # 日志保留天数
    # 关闭行为: "minimize" 最小化到托盘, "exit" 直接退出
    close_action: str = "minimize"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppSettings':
        return cls(**data)


class SettingsStorage:
    """设置存储管理"""

    def __init__(self, config_path: str = "config/settings.json"):
        self.config_path = config_path
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)

    def load(self) -> AppSettings:
        """加载设置"""
        if not os.path.exists(self.config_path):
            return AppSettings()
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return AppSettings.from_dict(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载设置失败: {e}")
            return AppSettings()

    def save(self, settings: AppSettings) -> bool:
        """保存设置"""
        try:
            self._ensure_config_dir()
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"保存设置失败: {e}")
            return False


@dataclass
class OutputParser:
    """输出解析规则"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""              # 解析器名称（用于全局模板）
    var_name: str = ""          # 变量名（生成 {var_xxx}）
    parser_type: str = "regex"  # regex, jsonpath, xpath, line, split
    expression: str = ""        # 解析表达式
    default_value: str = ""     # 匹配失败时的默认值
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OutputParser':
        return cls(**data)


@dataclass
class WebhookConfig:
    """Webhook 配置"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    url: str = ""
    method: str = "POST"  # GET, POST, PUT
    headers: Dict[str, str] = field(default_factory=dict)
    # 参数模板，支持变量替换: {task_name}, {status}, {output}, {exit_code}, {start_time}, {end_time}, {duration}
    body_template: str = '{"task": "{task_name}", "status": "{status}", "output": "{output}", "exit_code": {exit_code}}'
    enabled: bool = True
    # 钉钉加签配置
    dingtalk_sign_enabled: bool = False
    dingtalk_sign_secret: str = ""
    # 飞书签名校验配置
    feishu_sign_enabled: bool = False
    feishu_sign_secret: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WebhookConfig':
        # 兼容旧数据
        if 'dingtalk_sign_enabled' not in data:
            data['dingtalk_sign_enabled'] = False
        if 'dingtalk_sign_secret' not in data:
            data['dingtalk_sign_secret'] = ''
        if 'feishu_sign_enabled' not in data:
            data['feishu_sign_enabled'] = False
        if 'feishu_sign_secret' not in data:
            data['feishu_sign_secret'] = ''
        return cls(**data)


@dataclass
class Task:
    """任务数据模型"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    # 任务类型
    task_type: TaskType = TaskType.COMMAND
    # ===== 命令任务配置 =====
    # 批处理命令或脚本路径
    command: str = ""
    # 工作目录
    working_dir: str = ""
    # 手动执行时是否显示窗口
    show_window: bool = True
    # 执行前终止上次实例（如果还在运行）
    kill_previous: bool = False
    # ===== 同步任务配置 =====
    # 同步配置（仅当 task_type == SYNC 时使用）
    sync_config: Optional[SyncConfig] = None
    # ===== 通用配置 =====
    # Cron 表达式 (秒 分 时 日 月 周)
    cron_expression: str = "0 0 * * * *"
    # 是否启用
    enabled: bool = True
    # Webhook ID 列表（引用全局配置）
    webhook_ids: List[str] = field(default_factory=list)
    # 兼容旧版：完整的 Webhook 配置列表（已废弃，仅用于迁移）
    webhooks: List[WebhookConfig] = field(default_factory=list)
    # 输出解析器列表
    output_parsers: List[OutputParser] = field(default_factory=list)
    # 任务状态
    status: TaskStatus = TaskStatus.PENDING
    # 上次执行时间
    last_run: Optional[str] = None
    # 上次执行结果
    last_result: Optional[str] = None
    # 创建时间
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['task_type'] = self.task_type.value
        data['status'] = self.status.value
        # 只保存 webhook_ids，不再保存完整的 webhooks
        data['webhook_ids'] = self.webhook_ids
        # 清空旧的 webhooks 字段（迁移后不再需要）
        data['webhooks'] = []
        data['output_parsers'] = [p.to_dict() if isinstance(p, OutputParser) else p for p in self.output_parsers]
        if self.sync_config:
            data['sync_config'] = self.sync_config.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        data = data.copy()
        data['task_type'] = TaskType(data.get('task_type', 'command'))
        data['status'] = TaskStatus(data.get('status', 'pending'))

        # 兼容旧数据：如果有 webhooks 但没有 webhook_ids，进行迁移
        old_webhooks = data.get('webhooks', [])
        webhook_ids = data.get('webhook_ids', [])

        if old_webhooks and not webhook_ids:
            # 从旧的 webhooks 中提取 ID
            for w in old_webhooks:
                if isinstance(w, dict) and 'id' in w:
                    webhook_ids.append(w['id'])
                elif isinstance(w, WebhookConfig):
                    webhook_ids.append(w.id)

        data['webhook_ids'] = webhook_ids
        data['webhooks'] = []  # 清空旧字段

        data['output_parsers'] = [OutputParser.from_dict(p) if isinstance(p, dict) else p for p in data.get('output_parsers', [])]
        if data.get('sync_config'):
            data['sync_config'] = SyncConfig.from_dict(data['sync_config'])
        return cls(**data)

    def get_type_display(self) -> str:
        """获取任务类型显示名称"""
        type_names = {
            TaskType.COMMAND: "命令任务",
            TaskType.SYNC: "同步任务"
        }
        return type_names.get(self.task_type, "未知")

    def get_webhooks(self, webhook_storage: 'WebhookStorage') -> List[WebhookConfig]:
        """
        根据 webhook_ids 从全局配置中获取实际的 Webhook 配置

        Args:
            webhook_storage: Webhook 存储管理器

        Returns:
            List[WebhookConfig]: 实际的 Webhook 配置列表
        """
        if not self.webhook_ids:
            return []

        # 加载所有全局 webhook
        all_webhooks = webhook_storage.load_webhooks()
        webhook_map = {w.id: w for w in all_webhooks}

        # 根据 ID 获取配置
        result = []
        for wid in self.webhook_ids:
            if wid in webhook_map:
                result.append(webhook_map[wid])

        return result


class TaskStorage:
    """任务存储管理"""
    
    def __init__(self, config_path: str = "config/tasks.json"):
        self.config_path = config_path
        self._ensure_config_dir()
    
    def _ensure_config_dir(self):
        """确保配置目录存在"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)
    
    def load_tasks(self) -> List[Task]:
        """加载所有任务"""
        if not os.path.exists(self.config_path):
            return []
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [Task.from_dict(t) for t in data.get('tasks', [])]
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载任务配置失败: {e}")
            return []
    
    def save_tasks(self, tasks: List[Task]) -> bool:
        """保存所有任务"""
        try:
            self._ensure_config_dir()
            with open(self.config_path, 'w', encoding='utf-8') as f:
                data = {'tasks': [t.to_dict() for t in tasks]}
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"保存任务配置失败: {e}")
            return False
    
    def add_task(self, task: Task) -> bool:
        """添加任务"""
        tasks = self.load_tasks()
        tasks.append(task)
        return self.save_tasks(tasks)
    
    def update_task(self, task: Task) -> bool:
        """更新任务"""
        tasks = self.load_tasks()
        for i, t in enumerate(tasks):
            if t.id == task.id:
                tasks[i] = task
                return self.save_tasks(tasks)
        return False
    
    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        tasks = self.load_tasks()
        tasks = [t for t in tasks if t.id != task_id]
        return self.save_tasks(tasks)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取单个任务"""
        tasks = self.load_tasks()
        for t in tasks:
            if t.id == task_id:
                return t
        return None


class WebhookStorage:
    """全局 Webhook 配置存储管理"""

    def __init__(self, config_path: str = "config/webhooks.json"):
        self.config_path = config_path
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)

    def load_webhooks(self) -> List[WebhookConfig]:
        """加载所有 Webhook 配置"""
        if not os.path.exists(self.config_path):
            return []
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [WebhookConfig.from_dict(w) for w in data.get('webhooks', [])]
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载 Webhook 配置失败: {e}")
            return []

    def save_webhooks(self, webhooks: List[WebhookConfig]) -> bool:
        """保存所有 Webhook 配置"""
        try:
            self._ensure_config_dir()
            with open(self.config_path, 'w', encoding='utf-8') as f:
                data = {'webhooks': [w.to_dict() for w in webhooks]}
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"保存 Webhook 配置失败: {e}")
            return False

    def add_webhook(self, webhook: WebhookConfig) -> bool:
        """添加 Webhook"""
        webhooks = self.load_webhooks()
        webhooks.append(webhook)
        return self.save_webhooks(webhooks)

    def update_webhook(self, webhook: WebhookConfig) -> bool:
        """更新 Webhook"""
        webhooks = self.load_webhooks()
        for i, w in enumerate(webhooks):
            if w.id == webhook.id:
                webhooks[i] = webhook
                return self.save_webhooks(webhooks)
        return False

    def delete_webhook(self, webhook_id: str) -> bool:
        """删除 Webhook"""
        webhooks = self.load_webhooks()
        webhooks = [w for w in webhooks if w.id != webhook_id]
        return self.save_webhooks(webhooks)

    def get_webhook(self, webhook_id: str) -> Optional[WebhookConfig]:
        """获取单个 Webhook"""
        webhooks = self.load_webhooks()
        for w in webhooks:
            if w.id == webhook_id:
                return w
        return None


class ParserStorage:
    """全局输出解析器存储管理"""

    def __init__(self, config_path: str = "config/parsers.json"):
        self.config_path = config_path
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)

    def load_parsers(self) -> List[OutputParser]:
        """加载所有解析器配置"""
        if not os.path.exists(self.config_path):
            return []
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [OutputParser.from_dict(p) for p in data.get('parsers', [])]
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载解析器配置失败: {e}")
            return []

    def save_parsers(self, parsers: List[OutputParser]) -> bool:
        """保存所有解析器配置"""
        try:
            self._ensure_config_dir()
            with open(self.config_path, 'w', encoding='utf-8') as f:
                data = {'parsers': [p.to_dict() for p in parsers]}
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"保存解析器配置失败: {e}")
            return False

    def add_parser(self, parser: OutputParser) -> bool:
        """添加解析器"""
        parsers = self.load_parsers()
        parsers.append(parser)
        return self.save_parsers(parsers)

    def update_parser(self, parser: OutputParser) -> bool:
        """更新解析器"""
        parsers = self.load_parsers()
        for i, p in enumerate(parsers):
            if p.id == parser.id:
                parsers[i] = parser
                return self.save_parsers(parsers)
        return False

    def delete_parser(self, parser_id: str) -> bool:
        """删除解析器"""
        parsers = self.load_parsers()
        parsers = [p for p in parsers if p.id != parser_id]
        return self.save_parsers(parsers)

    def get_parser(self, parser_id: str) -> Optional[OutputParser]:
        """获取单个解析器"""
        parsers = self.load_parsers()
        for p in parsers:
            if p.id == parser_id:
                return p
        return None

