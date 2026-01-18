# -*- coding: utf-8 -*-
"""
清理任务执行器
"""
import os
import logging
import fnmatch
from typing import List, Tuple, Callable, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class CleanupResult:
    """清理结果"""
    success: bool
    initial_size_bytes: int  # 初始大小
    final_size_bytes: int    # 最终大小
    deleted_files: List[str]  # 已删除的文件列表
    deleted_count: int        # 删除的文件数量
    deleted_size_bytes: int   # 删除的总大小
    errors: List[str]         # 错误列表
    skipped: bool = False     # 是否跳过清理（未达到高阈值）

    def __init__(self):
        self.success = False
        self.initial_size_bytes = 0
        self.final_size_bytes = 0
        self.deleted_files = []
        self.deleted_count = 0
        self.deleted_size_bytes = 0
        self.errors = []
        self.skipped = False


class CleanupExecutor:
    """清理任务执行器"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """设置进度回调函数

        Args:
            callback: 回调函数，接收 (message, current, total) 参数
        """
        self._progress_callback = callback

    def _emit_progress(self, message: str, current: int = 0, total: int = 0):
        """发送进度更新"""
        if self._progress_callback:
            try:
                self._progress_callback(message, current, total)
            except Exception as e:
                self.logger.warning(f"进度回调失败: {e}")

    def execute(self, config) -> CleanupResult:
        """执行清理任务

        Args:
            config: CleanupConfig 配置对象

        Returns:
            CleanupResult 清理结果
        """
        from core.models import CleanupConfig

        result = CleanupResult()

        if not isinstance(config, CleanupConfig):
            result.errors.append("配置类型错误")
            return result

        # 验证目标目录
        if not config.target_dir or not os.path.exists(config.target_dir):
            result.errors.append(f"目标目录不存在: {config.target_dir}")
            return result

        if not os.path.isdir(config.target_dir):
            result.errors.append(f"目标路径不是目录: {config.target_dir}")
            return result

        self.logger.info(f"开始清理任务: {config.target_dir}")
        self._emit_progress(f"开始扫描目录: {config.target_dir}", 0, 100)

        try:
            # 1. 计算当前目录大小
            initial_size = self._calculate_directory_size(config.target_dir, config.recursive)
            result.initial_size_bytes = initial_size
            initial_size_gb = initial_size / (1024**3)

            self.logger.info(f"目录大小: {initial_size_gb:.2f} GB")
            self._emit_progress(f"当前大小: {initial_size_gb:.2f} GB", 10, 100)

            # 2. 检查是否需要清理
            if initial_size_gb <= config.high_threshold_gb:
                self.logger.info(f"目录大小 {initial_size_gb:.2f} GB 未超过高阈值 {config.high_threshold_gb} GB，跳过清理")
                result.success = True
                result.final_size_bytes = initial_size
                result.skipped = True
                self._emit_progress(f"未达到清理阈值，跳过清理", 100, 100)
                return result

            self.logger.info(f"目录大小 {initial_size_gb:.2f} GB 超过高阈值 {config.high_threshold_gb} GB，开始清理")
            self._emit_progress(f"需要清理 (超过 {config.high_threshold_gb} GB)", 20, 100)

            # 3. 收集所有文件并按修改时间排序
            files_with_time = self._collect_files(config)
            self.logger.info(f"收集到 {len(files_with_time)} 个文件")
            self._emit_progress(f"找到 {len(files_with_time)} 个文件", 30, 100)

            if not files_with_time:
                self.logger.warning("没有找到可清理的文件")
                result.success = True
                result.final_size_bytes = initial_size
                self._emit_progress("没有可清理的文件", 100, 100)
                return result

            # 按修改时间排序（最早的在前）
            files_with_time.sort(key=lambda x: x[1])

            # 4. 逐个删除文件直到低于低阈值
            low_threshold_bytes = int(config.low_threshold_gb * (1024**3))
            current_size = initial_size
            total_files = len(files_with_time)

            for index, (file_path, mtime) in enumerate(files_with_time):
                # 检查是否已达到目标
                if current_size <= low_threshold_bytes:
                    self.logger.info(f"已达到低阈值 {config.low_threshold_gb} GB，停止清理")
                    break

                try:
                    # 获取文件大小
                    file_size = os.path.getsize(file_path)

                    # 删除文件
                    os.remove(file_path)

                    # 更新统计
                    result.deleted_files.append(file_path)
                    result.deleted_count += 1
                    result.deleted_size_bytes += file_size
                    current_size -= file_size

                    # 更新进度
                    progress = 30 + int((index + 1) / total_files * 60)
                    current_gb = current_size / (1024**3)
                    self._emit_progress(
                        f"删除: {os.path.basename(file_path)} (剩余: {current_gb:.2f} GB)",
                        progress, 100
                    )

                    self.logger.debug(f"已删除: {file_path} ({file_size} 字节)")

                except Exception as e:
                    error_msg = f"删除文件失败 {file_path}: {e}"
                    self.logger.error(error_msg)
                    result.errors.append(error_msg)

            # 5. 清理空目录（如果需要）
            if config.recursive and not config.files_only:
                self._remove_empty_directories(config.target_dir)

            result.final_size_bytes = current_size
            result.success = True

            final_gb = current_size / (1024**3)
            self.logger.info(f"清理完成: 删除 {result.deleted_count} 个文件，"
                           f"释放 {result.deleted_size_bytes / (1024**3):.2f} GB，"
                           f"最终大小: {final_gb:.2f} GB")
            self._emit_progress(f"清理完成: 最终大小 {final_gb:.2f} GB", 100, 100)

        except Exception as e:
            error_msg = f"清理任务执行失败: {e}"
            self.logger.error(error_msg, exc_info=True)
            result.errors.append(error_msg)
            result.final_size_bytes = result.initial_size_bytes

        return result

    def _calculate_directory_size(self, directory: str, recursive: bool = True) -> int:
        """计算目录大小（字节）"""
        total_size = 0

        if not recursive:
            # 只计算顶层文件
            try:
                for entry in os.scandir(directory):
                    if entry.is_file(follow_symlinks=False):
                        total_size += entry.stat().st_size
            except Exception as e:
                self.logger.error(f"计算目录大小失败 {directory}: {e}")
        else:
            # 递归计算所有子目录
            try:
                for root, dirs, files in os.walk(directory):
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            total_size += os.path.getsize(file_path)
                        except OSError:
                            pass
            except Exception as e:
                self.logger.error(f"递归计算目录大小失败 {directory}: {e}")

        return total_size

    def _collect_files(self, config) -> List[Tuple[str, float]]:
        """收集需要清理的文件（返回文件路径和修改时间）"""
        files_with_time = []
        min_age_seconds = config.min_age_days * 86400  # 转换为秒
        current_time = datetime.now().timestamp()

        # 获取文件列表
        if config.recursive:
            # 递归获取所有文件
            for root, dirs, files in os.walk(config.target_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    if self._should_include_file(file_path, config):
                        try:
                            mtime = os.path.getmtime(file_path)
                            # 检查文件年龄
                            if current_time - mtime >= min_age_seconds:
                                files_with_time.append((file_path, mtime))
                        except OSError:
                            pass
        else:
            # 只获取顶层文件
            try:
                for entry in os.scandir(config.target_dir):
                    if entry.is_file(follow_symlinks=False):
                        file_path = entry.path
                        if self._should_include_file(file_path, config):
                            try:
                                mtime = entry.stat().st_mtime
                                # 检查文件年龄
                                if current_time - mtime >= min_age_seconds:
                                    files_with_time.append((file_path, mtime))
                            except OSError:
                                pass
            except Exception as e:
                self.logger.error(f"扫描目录失败 {config.target_dir}: {e}")

        return files_with_time

    def _should_include_file(self, file_path: str, config) -> bool:
        """判断文件是否应该被包含在清理范围内"""
        filename = os.path.basename(file_path)

        # 检查排除模式
        for pattern in config.exclude_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return False

        # 检查文件扩展名
        if config.file_extensions:
            _, ext = os.path.splitext(filename)
            if ext.lower() not in config.file_extensions:
                return False

        return True

    def _remove_empty_directories(self, directory: str):
        """删除空目录"""
        try:
            for root, dirs, files in os.walk(directory, topdown=False):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        # 只删除空目录
                        if not os.listdir(dir_path):
                            os.rmdir(dir_path)
                            self.logger.debug(f"已删除空目录: {dir_path}")
                    except OSError:
                        pass
        except Exception as e:
            self.logger.error(f"删除空目录失败: {e}")

