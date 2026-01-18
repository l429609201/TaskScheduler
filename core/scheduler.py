# -*- coding: utf-8 -*-
"""
任务调度器模块
"""
import logging
from typing import Dict, Callable, Optional, List
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from .models import Task, TaskStatus, TaskStorage, AppSettings, SettingsStorage, TaskType, WebhookStorage
from .executor import BatchExecutor, ExecutionResult
from .webhook import WebhookNotifier
from .logger import TaskLogger

logger = logging.getLogger(__name__)


class TaskScheduler:
    """任务调度器"""

    def __init__(self, storage: TaskStorage = None, settings_storage: SettingsStorage = None,
                 webhook_storage: WebhookStorage = None):
        """
        初始化调度器

        Args:
            storage: 任务存储实例
            settings_storage: 设置存储实例
            webhook_storage: Webhook 存储实例
        """
        self.storage = storage or TaskStorage()
        self.settings_storage = settings_storage or SettingsStorage()
        self.webhook_storage = webhook_storage or WebhookStorage()
        self.executor = BatchExecutor()
        self.notifier = WebhookNotifier()

        # 初始化日志记录器
        settings = self.settings_storage.load()
        self.task_logger = TaskLogger(
            log_dir=settings.log_dir,
            enabled=settings.log_enabled
        )
        
        # 配置 APScheduler
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': ThreadPoolExecutor(10)
        }
        job_defaults = {
            'coalesce': True,  # 合并错过的执行
            'max_instances': 1,  # 同一任务最多同时运行1个实例
            'misfire_grace_time': 60  # 错过执行的宽限时间
        }
        
        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults
        )
        
        # 任务执行回调
        self._on_task_start: Optional[Callable[[Task], None]] = None
        self._on_task_complete: Optional[Callable[[Task, ExecutionResult], None]] = None
    
    def set_callbacks(self, on_start: Callable = None, on_complete: Callable = None):
        """设置任务执行回调"""
        self._on_task_start = on_start
        self._on_task_complete = on_complete
    
    def _parse_cron(self, cron_expr: str) -> Dict:
        """解析 cron 表达式"""
        parts = cron_expr.strip().split()
        if len(parts) == 5:
            # 标准 5 段格式: 分 时 日 月 周
            return {
                'minute': parts[0],
                'hour': parts[1],
                'day': parts[2],
                'month': parts[3],
                'day_of_week': parts[4]
            }
        elif len(parts) == 6:
            # 6 段格式: 秒 分 时 日 月 周
            return {
                'second': parts[0],
                'minute': parts[1],
                'hour': parts[2],
                'day': parts[3],
                'month': parts[4],
                'day_of_week': parts[5]
            }
        else:
            raise ValueError(f"Invalid cron expression: {cron_expr}")
    
    def _execute_task(self, task_id: str):
        """执行任务"""
        task = self.storage.get_task(task_id)
        if not task or not task.enabled:
            return

        logger.info(f"开始执行任务: {task.name} (类型: {task.task_type.value})")

        # 更新任务状态
        task.status = TaskStatus.RUNNING
        self.storage.update_task(task)

        # 触发开始回调
        if self._on_task_start:
            try:
                self._on_task_start(task)
            except Exception as e:
                logger.error(f"Task start callback error: {e}")

        # 根据任务类型执行
        if task.task_type == TaskType.SYNC:
            # 同步任务
            result = self._execute_sync_task(task)
        else:
            # 命令任务
            result = self.executor.execute(
                command=task.command,
                working_dir=task.working_dir,
                task_id=task.id,
                kill_previous=getattr(task, 'kill_previous', False)
            )

        # 更新任务状态
        task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
        task.last_run = datetime.now().isoformat()
        task.last_result = f"Exit code: {result.exit_code}"
        self.storage.update_task(task)

        logger.info(f"任务执行完成: {task.name}, 状态: {task.status.value}")

        # 使用输出解析器解析控制台输出（命令任务和同步任务都支持）
        parsed_vars = {}
        if task.output_parsers:
            from core.output_parser import OutputParserEngine
            # 合并 stdout 和 stderr 作为完整的控制台输出
            full_output = (result.stdout or "") + "\n" + (result.stderr or "")
            parsed_vars = OutputParserEngine.parse_all(full_output, task.output_parsers)
            if parsed_vars:
                logger.info(f"解析器提取到 {len(parsed_vars)} 个变量: {list(parsed_vars.keys())}")

        # 记录执行日志
        if task.task_type == TaskType.COMMAND:
            log_file = self.task_logger.log_execution(
                task_id=task.id,
                task_name=task.name,
                command=task.command,
                working_dir=task.working_dir,
                result=result,
                parsed_vars=parsed_vars
            )
        else:
            # 同步任务日志
            log_file = self.task_logger.log_sync_execution(
                task_id=task.id,
                task_name=task.name,
                sync_config=task.sync_config,
                result=result,
                parsed_vars=parsed_vars
            )
        if log_file:
            logger.info(f"执行日志已保存: {log_file}")

        # 触发完成回调
        if self._on_task_complete:
            try:
                self._on_task_complete(task, result)
            except Exception as e:
                logger.error(f"Task complete callback error: {e}")

        # 发送 webhook 通知（命令任务和同步任务都支持）
        # 从全局配置中获取实际的 webhook 配置
        webhooks = task.get_webhooks(self.webhook_storage)
        logger.info(f"任务 '{task.name}' webhook 数量: {len(webhooks)} (IDs: {task.webhook_ids})")

        if webhooks:
            for i, wh in enumerate(webhooks):
                logger.info(f"  Webhook[{i}]: name='{wh.name}', enabled={wh.enabled}, url={wh.url[:50]}...")

            # 构建通知参数
            if task.task_type == TaskType.SYNC:
                # 同步任务的通知参数
                params = self._build_sync_notification_params(task, result)
            else:
                params = result.to_notification_params(task.name)
            # 合并解析器提取的变量
            params.update(parsed_vars)

            # 记录 webhook 推送日志（同步写入，确保在日志文件创建后）
            logger.info(f"准备写入 webhook 日志到: {log_file}")
            self._log_webhook_params(log_file, params)

            # 异步发送 webhook，完成后记录结果
            # 使用闭包捕获 log_file 的值
            current_log_file = log_file
            self.notifier.notify_async(webhooks, params,
                callback=lambda results, lf=current_log_file: self._log_webhook_results(lf, results))
        else:
            if task.webhook_ids:
                logger.warning(f"任务 '{task.name}' 配置的 webhook IDs {task.webhook_ids} 在全局配置中未找到")
            else:
                logger.info(f"任务 '{task.name}' 没有配置 webhook，跳过推送")

    def _execute_sync_task(self, task) -> 'ExecutionResult':
        """执行同步任务"""
        from core.sync_engine import SyncEngine
        from core.executor import ExecutionResult

        if not task.sync_config:
            return ExecutionResult(
                success=False,
                exit_code=1,
                stdout="",
                stderr="同步配置为空",
                start_time=datetime.now(),
                end_time=datetime.now()
            )

        start_time = datetime.now()
        stdout_lines = []
        stderr_lines = []

        try:
            # 创建同步引擎
            engine = SyncEngine(task.sync_config, thread_count=4)

            # 设置进度回调
            def on_progress(msg, current, total):
                stdout_lines.append(f"[{current}/{total}] {msg}")

            engine.set_progress_callback(on_progress)

            # 执行同步
            stdout_lines.append(f"开始同步...")
            stdout_lines.append(f"源端: {task.sync_config.source.path}")
            stdout_lines.append(f"目标端: {task.sync_config.target.path}")
            stdout_lines.append(f"同步模式: {task.sync_config.sync_mode.value}")
            stdout_lines.append("")

            sync_result = engine.sync()

            # 记录结果
            stdout_lines.append("")
            stdout_lines.append("=" * 50)
            stdout_lines.append("同步完成")
            stdout_lines.append(f"复制文件: {sync_result.copied_files}")
            stdout_lines.append(f"更新文件: {sync_result.updated_files}")
            stdout_lines.append(f"删除文件: {sync_result.deleted_files}")
            stdout_lines.append(f"跳过文件: {sync_result.skipped_files}")
            stdout_lines.append(f"失败文件: {sync_result.failed_files}")
            stdout_lines.append(f"传输字节: {sync_result.transferred_bytes}")
            stdout_lines.append(f"耗时: {sync_result.duration:.2f} 秒")
            stdout_lines.append(f"详情记录数: {len(sync_result.details)}")

            # 记录文件列表详情
            if sync_result.details:
                stdout_lines.append("")
                stdout_lines.append("文件列表:")
                for action, file_path, success, _ in sync_result.details:
                    status = "✓" if success else "✗"
                    stdout_lines.append(f"  [{action}] {status} {file_path}")
            else:
                stdout_lines.append("")
                stdout_lines.append("文件列表: (无记录)")

            if sync_result.errors:
                stderr_lines.append("错误信息:")
                for err in sync_result.errors:
                    stderr_lines.append(f"  - {err}")

            return ExecutionResult(
                success=sync_result.success,
                exit_code=0 if sync_result.success else 1,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
                start_time=start_time,
                end_time=datetime.now(),
                # 附加同步结果详情供 Webhook 使用
                extra_data={'sync_details': sync_result.details}
            )

        except Exception as e:
            import traceback
            stderr_lines.append(f"同步执行异常: {str(e)}")
            stderr_lines.append(traceback.format_exc())

            return ExecutionResult(
                success=False,
                exit_code=1,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
                start_time=start_time,
                end_time=datetime.now()
            )
    
    def add_task(self, task: Task) -> bool:
        """添加任务到调度器"""
        if not task.enabled:
            logger.info(f"任务 {task.name} 未启用，跳过添加到调度器")
            return True

        try:
            cron_params = self._parse_cron(task.cron_expression)
            trigger = CronTrigger(**cron_params)

            self._scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                args=[task.id],
                id=task.id,
                name=task.name,
                replace_existing=True
            )

            # 获取下次执行时间
            job = self._scheduler.get_job(task.id)
            next_run = job.next_run_time if job else None
            logger.info(f"✓ 任务已添加到调度器: {task.name}")
            logger.info(f"  - Cron 表达式: {task.cron_expression}")
            logger.info(f"  - Cron 参数: {cron_params}")
            logger.info(f"  - 下次执行时间: {next_run}")
            return True
        except Exception as e:
            logger.error(f"✗ 添加任务失败: {task.name}, 错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def remove_task(self, task_id: str) -> bool:
        """从调度器移除任务"""
        try:
            self._scheduler.remove_job(task_id)
            return True
        except Exception:
            return False
    
    def update_task(self, task: Task) -> bool:
        """更新调度器中的任务"""
        self.remove_task(task.id)
        if task.enabled:
            return self.add_task(task)
        return True
    
    def run_task_now(self, task_id: str):
        """立即执行任务"""
        import threading
        thread = threading.Thread(target=self._execute_task, args=(task_id,))
        thread.daemon = True
        thread.start()
    
    def load_all_tasks(self):
        """加载所有任务到调度器"""
        tasks = self.storage.load_tasks()
        for task in tasks:
            if task.enabled:
                self.add_task(task)
        logger.info(f"已加载 {len(tasks)} 个任务")
    
    def start(self):
        """启动调度器"""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("调度器已启动")
    
    def stop(self):
        """停止调度器"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self.notifier.shutdown()
            logger.info("调度器已停止")
    
    def get_next_run_time(self, task_id: str) -> Optional[datetime]:
        """获取任务下次执行时间"""
        job = self._scheduler.get_job(task_id)
        if job:
            return job.next_run_time
        return None

    def update_log_settings(self, enabled: bool, log_dir: str):
        """更新日志设置"""
        self.task_logger.enabled = enabled
        self.task_logger.log_dir = log_dir

    def _build_sync_notification_params(self, task, result) -> dict:
        """构建同步任务的通知参数"""
        # 解析同步结果
        copied = 0
        updated = 0
        deleted = 0
        skipped = 0
        failed = 0
        transferred = 0

        # 从 stdout 中解析统计信息
        if result.stdout:
            import re
            for line in result.stdout.split('\n'):
                # 支持两种格式：
                # 1. "复制: 0  更新: 26  删除: 0" (后台任务格式)
                # 2. "复制文件: 0" (调度器格式)

                # 尝试匹配后台任务格式（一行包含多个统计）
                match = re.search(r'复制:\s*(\d+)\s+更新:\s*(\d+)\s+删除:\s*(\d+)', line)
                if match:
                    copied = int(match.group(1))
                    updated = int(match.group(2))
                    deleted = int(match.group(3))
                    continue

                match = re.search(r'失败:\s*(\d+)\s+跳过:\s*(\d+)', line)
                if match:
                    failed = int(match.group(1))
                    skipped = int(match.group(2))
                    continue

                # 尝试匹配调度器格式（每行一个统计）
                if '复制文件:' in line or '复制:' in line:
                    match = re.search(r'复制(?:文件)?:\s*(\d+)', line)
                    if match:
                        copied = int(match.group(1))
                elif '更新文件:' in line or '更新:' in line:
                    match = re.search(r'更新(?:文件)?:\s*(\d+)', line)
                    if match:
                        updated = int(match.group(1))
                elif '删除文件:' in line or '删除:' in line:
                    match = re.search(r'删除(?:文件)?:\s*(\d+)', line)
                    if match:
                        deleted = int(match.group(1))
                elif '跳过文件:' in line or '跳过:' in line:
                    match = re.search(r'跳过(?:文件)?:\s*(\d+)', line)
                    if match:
                        skipped = int(match.group(1))
                elif '失败文件:' in line or '失败:' in line:
                    match = re.search(r'失败(?:文件)?:\s*(\d+)', line)
                    if match:
                        failed = int(match.group(1))
                elif '传输字节:' in line:
                    match = re.search(r'传输字节:\s*(\d+)', line)
                    if match:
                        transferred = int(match.group(1))

        # 格式化传输大小
        def format_size(size):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024:
                    return f"{size:.1f} {unit}"
                size /= 1024
            return f"{size:.1f} TB"

        # 构建参数
        source_path = task.sync_config.source.path if task.sync_config else "未知"
        target_path = task.sync_config.target.path if task.sync_config else "未知"
        sync_mode = task.sync_config.sync_mode.value if task.sync_config else "未知"

        # 构建源服务器地址
        source_server = "本地"
        if task.sync_config and task.sync_config.source:
            src = task.sync_config.source
            if src.type.value == 'sftp':
                source_server = f"{src.username}@{src.host}:{src.port}" if src.username else f"{src.host}:{src.port}"
            elif src.type.value == 'ftp':
                source_server = f"{src.username}@{src.host}:{src.port}" if src.username else f"{src.host}:{src.port}"
            elif src.type.value == 'local':
                source_server = "本地"

        # 构建目标服务器地址
        target_server = "本地"
        if task.sync_config and task.sync_config.target:
            tgt = task.sync_config.target
            if tgt.type.value == 'sftp':
                target_server = f"{tgt.username}@{tgt.host}:{tgt.port}" if tgt.username else f"{tgt.host}:{tgt.port}"
            elif tgt.type.value == 'ftp':
                target_server = f"{tgt.username}@{tgt.host}:{tgt.port}" if tgt.username else f"{tgt.host}:{tgt.port}"
            elif tgt.type.value == 'local':
                target_server = "本地"

        # 从 extra_data 中获取文件列表详情
        sync_details = getattr(result, 'extra_data', {}).get('sync_details', [])

        # 按操作类型分类文件列表
        copied_list = []
        updated_list = []
        deleted_list = []
        failed_list = []
        unchanged_list = []  # 相同/跳过的文件
        all_files = []

        for action, file_path, success, _ in sync_details:
            all_files.append(file_path)
            if not success:
                failed_list.append(file_path)
            elif action == '复制':
                copied_list.append(file_path)
            elif action == '更新':
                updated_list.append(file_path)
            elif action == '删除':
                deleted_list.append(file_path)
            elif action in ('已同步', '跳过'):
                unchanged_list.append(file_path)

        # 格式化文件列表（限制长度，带状态标记）
        def format_file_list(files, max_count=50, with_action=False):
            if not files:
                return '(无)'
            if with_action:
                # files 是 (action, file_path, success) 的列表
                lines = []
                for item in files[:max_count]:
                    if len(item) >= 3:
                        action, file_path, success = item[0], item[1], item[2]
                        status_icon = '✓' if success else '✗'
                        lines.append(f'{status_icon} [{action}] {file_path}')
                    else:
                        lines.append(f'• {item}')
                result_str = '\n'.join(lines)
                if len(files) > max_count:
                    result_str += f'\n... 还有 {len(files) - max_count} 个文件'
                return result_str
            else:
                if len(files) <= max_count:
                    return '\n'.join(f'• {f}' for f in files)
                return '\n'.join(f'• {f}' for f in files[:max_count]) + f'\n... 还有 {len(files) - max_count} 个文件'

        # 格式化文件列表（带状态图标，换行格式）
        # 钉钉 markdown 需要用两个换行符才能真正换行显示
        def format_file_list_markdown(details, max_count=20):
            # 即使没有变更，也要显示所有检查过的文件
            if not details:
                return '(无文件)'
            lines = []
            for item in details[:max_count]:
                if len(item) >= 3:
                    action, file_path, success = item[0], item[1], item[2]
                    status_icon = '✓' if success else '✗'
                    lines.append(f'{status_icon} [{action}] {file_path}')
                else:
                    lines.append(str(item))
            # 使用两个换行符，钉钉 markdown 才会真正换行
            result_str = '\n\n'.join(lines)
            if len(details) > max_count:
                result_str += f'\n\n... 还有 {len(details) - max_count} 个文件'
            return result_str

        # 生成同步消息（检查情况说明）
        total_processed = copied + updated + deleted
        if total_processed == 0 and failed == 0:
            sync_message = '所有文件已是最新，无需同步'
        elif failed > 0:
            sync_message = f'同步完成，但有 {failed} 个文件失败'
        else:
            sync_message = f'同步完成: 复制 {copied} 个, 更新 {updated} 个, 删除 {deleted} 个'

        # 生成状态图标
        if not result.success:
            status_icon = '❌'
            status_text = '失败'
        elif failed > 0:
            status_icon = '⚠️'
            status_text = '部分失败'
        elif total_processed == 0:
            status_icon = '✅'
            status_text = '无变更'
        else:
            status_icon = '✅'
            status_text = '成功'

        return {
            'task_name': task.name,
            'task_type': '文件同步',
            'status': status_text,
            'status_cn': status_text,
            'status_icon': status_icon,
            'success': result.success,
            'exit_code': result.exit_code,
            'start_time': result.start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'start_time_fmt': result.start_time.strftime('%Y-%m-%d %H:%M:%S'),  # 添加格式化的开始时间
            'end_time': result.end_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time_fmt': result.end_time.strftime('%Y-%m-%d %H:%M:%S'),  # 添加格式化的结束时间
            'duration': f"{result.duration:.2f}",
            'duration_str': f"{result.duration:.1f}秒",
            'duration_seconds': result.duration,
            # 同步特有参数
            'source_path': source_path,
            'target_path': target_path,
            'source_server': source_server,
            'target_server': target_server,
            'sync_mode': sync_mode,
            'copied_files': copied,
            'updated_files': updated,
            'deleted_files': deleted,
            'skipped_files': skipped,
            'failed_files': failed,
            'transferred_bytes': transferred,
            'transferred_size': format_size(transferred),
            'total_processed': total_processed,
            'total_files': len(all_files),
            'unchanged_files': len(unchanged_list),
            # 同步消息（检查情况说明）
            'sync_message': sync_message,
            # 文件列表（带状态）
            'file_list': format_file_list_markdown(sync_details),
            'file_list_short': format_file_list_markdown(sync_details, max_count=10),
            'file_list_full': format_file_list(sync_details, max_count=100, with_action=True),
            'copied_file_list': format_file_list(copied_list),
            'updated_file_list': format_file_list(updated_list),
            'deleted_file_list': format_file_list(deleted_list),
            'failed_file_list': format_file_list(failed_list),
            'unchanged_file_list': format_file_list(unchanged_list),
            # 摘要信息
            'summary': f"复制:{copied} 更新:{updated} 删除:{deleted} 失败:{failed}",
            'stdout': result.stdout or '',
            'stderr': result.stderr or '',
        }

    def _log_webhook_params(self, log_file: str, params: dict):
        """记录 webhook 推送参数到日志文件"""
        if not log_file:
            logger.warning("webhook 日志文件路径为空，跳过写入")
            return

        import os
        if not os.path.exists(log_file):
            logger.warning(f"webhook 日志文件不存在: {log_file}")
            return

        log_lines = []
        log_lines.append("")
        log_lines.append("=" * 60)
        log_lines.append("[Webhook 推送参数]")
        log_lines.append("=" * 60)

        # 按字母顺序排列参数
        for key in sorted(params.keys()):
            value = params[key]
            # 截断过长的值
            value_str = str(value)
            if len(value_str) > 500:
                value_str = value_str[:500] + "...(截断)"
            log_lines.append(f"  {{{key}}} = {value_str}")

        log_lines.append("")
        log_lines.append(f"共 {len(params)} 个参数")
        log_lines.append("=" * 60)

        # 直接追加到日志文件
        try:
            content = "\n" + "\n".join(log_lines)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"webhook 参数已写入日志: {log_file}")
        except Exception as e:
            logger.error(f"写入 webhook 参数日志失败: {e}")

    def _log_webhook_results(self, log_file: str, results: list):
        """记录 webhook 推送结果到日志文件"""
        if not log_file:
            return

        log_lines = []
        log_lines.append("")
        log_lines.append("[Webhook 推送结果]")

        for r in results:
            status = "✓ 成功" if r.success else "✗ 失败"
            log_lines.append(f"  {r.webhook_name}: {status}")
            if r.status_code:
                log_lines.append(f"    状态码: {r.status_code}")
            if r.response:
                resp_str = r.response[:200] + "..." if len(r.response) > 200 else r.response
                log_lines.append(f"    响应: {resp_str}")
            if r.error:
                log_lines.append(f"    错误: {r.error}")

        log_lines.append("=" * 60)

        # 直接追加到日志文件
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write("\n" + "\n".join(log_lines))
        except Exception as e:
            logger.error(f"写入 webhook 结果日志失败: {e}")

