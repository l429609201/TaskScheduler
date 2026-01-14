# 任务调度器 (Task Scheduler)

一个功能强大的自定义任务调度工具，支持定时执行批处理、文件同步、Webhook 通知和 Windows 服务安装。

## 功能特性

- ✅ **定时任务调度**: 支持 Cron 表达式配置，灵活设置执行时间
- ✅ **批处理执行**: 执行任意批处理命令或脚本
- ✅ **文件同步**: 支持本地、SFTP、FTP 之间的文件同步
  - 支持镜像同步、增量同步、仅新增等多种模式
  - 支持文件过滤（包含/排除规则）
  - 支持大文件断点续传
- ✅ **多 Webhook 支持**: 每个任务可配置多个 Webhook 通知
  - 支持钉钉机器人（含加签验证）
  - 支持飞书机器人（含签名验证）
  - 支持自定义 Webhook
- ✅ **输出解析器**: 从脚本输出中提取自定义变量
- ✅ **自定义通知参数**: 执行结果自动转换为通知参数
- ✅ **系统托盘**: 最小化到系统托盘，后台运行
- ✅ **开机自启**: 支持设置开机自动启动
- ✅ **Windows 服务**: 可安装为 Windows 服务，保证稳定运行
- ✅ **执行日志**: 自动记录任务执行日志，支持日志清理

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行程序

```bash
# GUI 模式
python main.py

# 服务模式（无界面）
python main.py --service
```

## Windows 服务管理

```bash
# 安装服务（需要管理员权限）
python main.py --install

# 启动服务
python main.py --start

# 停止服务
python main.py --stop

# 查询状态
python main.py --status

# 卸载服务
python main.py --uninstall
```

## Cron 表达式说明

支持 5 段或 6 段 Cron 表达式：

- 5 段格式: `分 时 日 月 周`
- 6 段格式: `秒 分 时 日 月 周`

### 常用示例

| 表达式 | 说明 |
|--------|------|
| `* * * * *` | 每分钟执行 |
| `*/5 * * * *` | 每 5 分钟执行 |
| `0 * * * *` | 每小时整点执行 |
| `0 0 * * *` | 每天 0 点执行 |
| `0 0 * * 1` | 每周一 0 点执行 |
| `0 9,18 * * *` | 每天 9 点和 18 点执行 |

## Webhook 参数模板

在 Webhook Body 模板中可使用以下变量：

### 基础参数

| 变量 | 说明 | 示例 |
|------|------|------|
| `{task_name}` | 任务名称 | `备份数据库` |
| `{status}` | 执行状态 | `success` / `failed` |
| `{status_cn}` | 执行状态(中文) | `成功` / `失败` |
| `{exit_code}` | 退出码 | `0` |

### 输出参数

| 变量 | 说明 | 示例 |
|------|------|------|
| `{output}` | 标准输出 (前2000字符) | `Hello World...` |
| `{output_full}` | 完整标准输出 | 全部内容 |
| `{output_first_line}` | 输出第一行 | `开始执行...` |
| `{output_last_line}` | 输出最后一行 | `执行完成` |
| `{output_line_count}` | 输出行数 | `15` |
| `{error}` | 错误输出 (前1000字符) | `Error: ...` |
| `{error_full}` | 完整错误输出 | 全部内容 |

### 时间参数

| 变量 | 说明 | 示例 |
|------|------|------|
| `{start_time}` | 开始时间 (ISO) | `2024-01-15T10:30:00` |
| `{end_time}` | 结束时间 (ISO) | `2024-01-15T10:30:05` |
| `{start_time_fmt}` | 开始时间 (格式化) | `2024-01-15 10:30:00` |
| `{end_time_fmt}` | 结束时间 (格式化) | `2024-01-15 10:30:05` |
| `{date}` | 执行日期 | `2024-01-15` |
| `{time}` | 执行时间 | `10:30:00` |
| `{duration}` | 执行时长 (秒) | `5.23` |
| `{duration_ms}` | 执行时长 (毫秒) | `5230` |
| `{duration_str}` | 执行时长 (格式化) | `5.2秒` |

### 环境参数

| 变量 | 说明 | 示例 |
|------|------|------|
| `{hostname}` | 主机名 | `MY-COMPUTER` |
| `{username}` | 当前用户 | `admin` |

### 同步任务参数

| 变量 | 说明 | 示例 |
|------|------|------|
| `{source_path}` | 源路径 | `/data/backup` |
| `{target_path}` | 目标路径 | `D:\backup` |
| `{source_server}` | 源服务器 | `user@192.168.1.1:22` |
| `{target_server}` | 目标服务器 | `本地` |
| `{sync_mode}` | 同步模式 | `mirror` |
| `{copied_files}` | 复制文件数 | `5` |
| `{updated_files}` | 更新文件数 | `3` |
| `{deleted_files}` | 删除文件数 | `1` |
| `{failed_files}` | 失败文件数 | `0` |
| `{unchanged_files}` | 未变更文件数 | `10` |
| `{transferred_size}` | 传输大小 | `1.5 MB` |
| `{sync_message}` | 同步消息 | `所有文件已是最新` |
| `{file_list}` | 文件列表 | 带状态的文件列表 |
| `{summary}` | 摘要 | `复制:5 更新:3 删除:1 失败:0` |

### 自定义变量 (从脚本输出解析)

如果你的脚本输出包含 `KEY=VALUE` 格式的行，会自动解析为 `{var_KEY}` 变量：

```batch
@echo off
echo VERSION=1.2.3
echo BUILD_NUMBER=456
echo RESULT=success
```

上面的脚本会自动生成以下变量：
- `{var_VERSION}` → `1.2.3`
- `{var_BUILD_NUMBER}` → `456`
- `{var_RESULT}` → `success`

### 示例模板

**简单通知:**
```json
{
  "task": "{task_name}",
  "status": "{status_cn}",
  "message": "任务在 {end_time_fmt} 执行{status_cn}，耗时 {duration_str}"
}
```

**详细通知 (带自定义变量):**
```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "{status_icon} {task_name} 同步{status}",
    "text": "## {status_icon} {task_name} 同步{status}\n\n**基本信息**\n- 🕐 开始时间: {start_time}\n- ⏱️ 耗时: {duration_str}\n- 🖥️ 源服务器: {source_server}\n- 📂 源路径: {source_path}\n- 📁 目标路径: {target_path}\n- 🔄 同步模式: {sync_mode}\n\n**同步统计**\n- ✅ 复制: {copied_files} 个\n- 🔄 更新: {updated_files} 个\n- 🗑️ 删除: {deleted_files} 个\n- ⏭️ 相同: {unchanged_files} 个\n- ❌ 失败: {failed_files} 个\n- 📊 传输大小: {transferred_size}\n\n**{sync_message}**\n\n**文件列表**\n```\n{file_list}\n```"
  }
}
```

## 项目结构

```
task-scheduler/
├── main.py              # 主程序入口
├── build.spec           # PyInstaller 打包配置
├── requirements.txt     # 依赖列表
├── README.md            # 说明文档
├── logo.ico             # 应用图标
├── config/              # 配置文件目录
│   ├── tasks.json       # 任务配置
│   └── webhooks.json    # Webhook 配置
├── logs/                # 日志目录
├── core/                # 核心模块
│   ├── models.py        # 数据模型
│   ├── executor.py      # 批处理执行器
│   ├── scheduler.py     # 任务调度器
│   ├── sync_engine.py   # 文件同步引擎
│   ├── webhook.py       # Webhook 通知
│   ├── output_parser.py # 输出解析器
│   └── logger.py        # 日志记录器
├── ui/                  # 界面模块
│   ├── main_window.py   # 主窗口
│   ├── task_dialog.py   # 命令任务编辑对话框
│   ├── sync_task_dialog.py  # 同步任务编辑对话框
│   ├── webhook_dialog.py    # Webhook 编辑对话框
│   ├── execution_dialog.py  # 任务执行对话框
│   └── settings_dialog.py   # 设置对话框
└── service/             # 服务模块
    ├── task_service.py  # Windows 服务
    └── installer.py     # 服务安装器
```

## 打包发布

使用 PyInstaller 打包为单文件可执行程序：

```bash
pyinstaller build.spec --noconfirm
```

打包后的程序位于 `dist/TaskScheduler.exe`。

## 注意事项

1. **管理员权限**: 安装/卸载 Windows 服务需要管理员权限
2. **防火墙**: 如果 Webhook 无法发送，请检查防火墙设置
3. **编码问题**: 批处理输出默认使用 UTF-8，如有乱码可尝试 GBK
4. **SFTP 连接**: 首次连接新服务器时会自动添加主机密钥
5. **钉钉 Markdown**: 钉钉 Markdown 消息需要使用双换行符 `\n\n` 才能正确换行

## License

MIT License

