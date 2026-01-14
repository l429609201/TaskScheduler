# -*- coding: utf-8 -*-
"""
AI 视觉自动化模块
通过 AI 分析屏幕截图，智能执行点击、输入等操作
"""
import os
import sys
import time
import json
import base64
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

# GUI 自动化
try:
    import pyautogui
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

try:
    import win32gui
    import win32con
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    win32gui = None
    win32con = None
    win32api = None

# 图像处理
try:
    from PIL import Image, ImageDraw, ImageFont
    import io
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class ActionType(Enum):
    """操作类型"""
    CLICK = "click"           # 点击
    DOUBLE_CLICK = "double_click"  # 双击
    RIGHT_CLICK = "right_click"    # 右键
    INPUT = "input"           # 输入文字
    SCROLL = "scroll"         # 滚动
    DRAG = "drag"             # 拖拽
    WAIT = "wait"             # 等待
    HOTKEY = "hotkey"         # 快捷键
    DONE = "done"             # 任务完成
    FAILED = "failed"         # 任务失败


@dataclass
class Action:
    """操作指令"""
    type: ActionType
    x: int = 0                # X 坐标（相对于窗口）
    y: int = 0                # Y 坐标（相对于窗口）
    text: str = ""            # 输入的文字
    keys: List[str] = field(default_factory=list)  # 快捷键
    scroll_amount: int = 0    # 滚动量
    description: str = ""     # 操作描述
    confidence: float = 1.0   # 置信度


@dataclass
class WindowInfo:
    """窗口信息"""
    hwnd: int
    title: str
    class_name: str
    rect: Tuple[int, int, int, int]  # left, top, right, bottom
    
    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]
    
    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


class WindowSelector:
    """窗口选择器"""

    @staticmethod
    def list_windows() -> List[WindowInfo]:
        """列出所有可见窗口"""
        if not HAS_WIN32:
            return []

        windows = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:  # 只要有标题的窗口
                    class_name = win32gui.GetClassName(hwnd)
                    rect = win32gui.GetWindowRect(hwnd)
                    windows.append(WindowInfo(hwnd, title, class_name, rect))
            return True

        win32gui.EnumWindows(callback, None)
        return windows
    
    @staticmethod
    def find_window(title: str = None, class_name: str = None) -> Optional[WindowInfo]:
        """根据标题或类名查找窗口"""
        windows = WindowSelector.list_windows()
        
        for win in windows:
            if title and title.lower() in win.title.lower():
                return win
            if class_name and class_name == win.class_name:
                return win
        
        return None
    
    @staticmethod
    def get_window_at_cursor() -> Optional[WindowInfo]:
        """获取鼠标位置的窗口"""
        pos = win32api.GetCursorPos()
        hwnd = win32gui.WindowFromPoint(pos)
        
        # 获取顶层窗口
        hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        
        if hwnd:
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            return WindowInfo(hwnd, title, class_name, rect)
        
        return None
    
    @staticmethod
    def focus_window(window: WindowInfo) -> bool:
        """激活窗口"""
        try:
            win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(window.hwnd)
            time.sleep(0.3)
            return True
        except:
            return False


class ScreenCapture:
    """屏幕截图工具"""

    @staticmethod
    def capture_full_screen() -> Optional[Image.Image]:
        """截取全屏"""
        try:
            return pyautogui.screenshot()
        except:
            return None

    @staticmethod
    def capture_window(window: WindowInfo) -> Optional[Image.Image]:
        """截取指定窗口"""
        try:
            # 先激活窗口
            WindowSelector.focus_window(window)
            time.sleep(0.2)

            # 重新获取窗口位置（可能有变化）
            rect = win32gui.GetWindowRect(window.hwnd)

            screenshot = pyautogui.screenshot(region=(
                rect[0], rect[1],
                rect[2] - rect[0],
                rect[3] - rect[1]
            ))
            return screenshot
        except Exception as e:
            print(f"截图失败: {e}")
            return None

    @staticmethod
    def capture_region(x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """截取指定区域"""
        try:
            return pyautogui.screenshot(region=(x, y, width, height))
        except:
            return None

    @staticmethod
    def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
        """图片转 base64"""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @staticmethod
    def add_grid_overlay(image: Image.Image, grid_size: int = 100) -> Image.Image:
        """
        在图片上添加网格和坐标，帮助 AI 定位
        """
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)
        width, height = image.size

        # 尝试加载字体
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()

        # 画网格线和坐标
        for x in range(0, width, grid_size):
            draw.line([(x, 0), (x, height)], fill=(255, 0, 0, 128), width=1)
            draw.text((x + 2, 2), str(x), fill=(255, 0, 0), font=font)

        for y in range(0, height, grid_size):
            draw.line([(0, y), (width, y)], fill=(255, 0, 0, 128), width=1)
            draw.text((2, y + 2), str(y), fill=(255, 0, 0), font=font)

        return img_copy


class AIVisionClient:
    """
    AI 视觉客户端
    支持 OpenAI GPT-4V / Claude / 通义千问等
    """

    # 系统提示词
    SYSTEM_PROMPT = """你是一个专业的 UI 自动化助手。你的任务是分析屏幕截图，并指导用户完成操作。

当用户给你一张截图和任务描述时，你需要：
1. 分析当前界面状态
2. 确定下一步应该执行的操作
3. 返回精确的操作指令

你必须以 JSON 格式返回操作指令，格式如下：
```json
{
    "action": "click|double_click|right_click|input|scroll|drag|hotkey|wait|done|failed",
    "x": 100,           // 点击的 X 坐标（相对于窗口左上角）
    "y": 200,           // 点击的 Y 坐标（相对于窗口左上角）
    "text": "",         // input 操作时要输入的文字
    "keys": [],         // hotkey 操作时的按键组合，如 ["ctrl", "c"]
    "scroll_amount": 0, // scroll 操作时的滚动量，正数向上，负数向下
    "description": "点击登录按钮",  // 操作描述
    "confidence": 0.95  // 置信度 0-1
}
```

重要规则：
1. 坐标必须是整数，基于图片像素位置
2. 如果任务已完成，返回 action: "done"
3. 如果无法完成任务，返回 action: "failed" 并在 description 中说明原因
4. 每次只返回一个操作
5. 只返回 JSON，不要有其他文字"""

    def __init__(self, api_key: str, base_url: str = None, model: str = None):
        """
        初始化 AI 客户端
        :param api_key: API 密钥
        :param base_url: API 地址（默认 OpenAI）
        :param model: 模型名称
        """
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1"
        self.model = model or "gpt-4o"
        self.conversation_history = []

    def analyze_and_act(self, image: Image.Image, task: str, context: str = "") -> Optional[Action]:
        """
        分析截图并返回操作指令
        :param image: 屏幕截图
        :param task: 任务描述
        :param context: 额外上下文（如之前的操作）
        :return: Action 对象
        """
        try:
            import requests

            # 图片转 base64
            image_base64 = ScreenCapture.image_to_base64(image)

            # 构建消息
            user_message = f"任务：{task}"
            if context:
                user_message += f"\n\n上下文：{context}"
            user_message += "\n\n请分析截图并返回下一步操作的 JSON 指令。"

            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ]

            # 调用 API
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.1  # 低温度，更确定性的输出
            }

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code != 200:
                print(f"API 调用失败: {response.status_code} - {response.text}")
                return None

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # 解析 JSON
            return self._parse_action(content)

        except Exception as e:
            print(f"AI 分析失败: {e}")
            return None

    def _parse_action(self, content: str) -> Optional[Action]:
        """解析 AI 返回的 JSON 为 Action 对象"""
        try:
            # 提取 JSON（可能被 ```json ``` 包裹）
            import re
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if not json_match:
                print(f"未找到 JSON: {content}")
                return None

            data = json.loads(json_match.group())

            action_type = ActionType(data.get("action", "failed"))

            return Action(
                type=action_type,
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                text=data.get("text", ""),
                keys=data.get("keys", []),
                scroll_amount=int(data.get("scroll_amount", 0)),
                description=data.get("description", ""),
                confidence=float(data.get("confidence", 1.0))
            )
        except Exception as e:
            print(f"解析 Action 失败: {e}, 内容: {content}")
            return None


class ActionExecutor:
    """操作执行器"""

    def __init__(self, window: WindowInfo = None):
        """
        初始化执行器
        :param window: 目标窗口（如果为 None，则使用绝对坐标）
        """
        self.window = window
        self.action_delay = 0.3  # 操作间隔

    def execute(self, action: Action) -> bool:
        """
        执行操作
        :param action: Action 对象
        :return: 是否成功
        """
        print(f"执行操作: {action.type.value} - {action.description}")

        # 计算绝对坐标
        abs_x, abs_y = self._to_absolute(action.x, action.y)

        try:
            if action.type == ActionType.CLICK:
                pyautogui.click(abs_x, abs_y)

            elif action.type == ActionType.DOUBLE_CLICK:
                pyautogui.doubleClick(abs_x, abs_y)

            elif action.type == ActionType.RIGHT_CLICK:
                pyautogui.rightClick(abs_x, abs_y)

            elif action.type == ActionType.INPUT:
                # 先点击目标位置
                pyautogui.click(abs_x, abs_y)
                time.sleep(0.2)
                # 清空现有内容
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)
                # 输入文字
                pyautogui.typewrite(action.text, interval=0.02)

            elif action.type == ActionType.SCROLL:
                pyautogui.moveTo(abs_x, abs_y)
                pyautogui.scroll(action.scroll_amount)

            elif action.type == ActionType.DRAG:
                # TODO: 实现拖拽
                pass

            elif action.type == ActionType.HOTKEY:
                pyautogui.hotkey(*action.keys)

            elif action.type == ActionType.WAIT:
                time.sleep(1)

            elif action.type in (ActionType.DONE, ActionType.FAILED):
                return True

            time.sleep(self.action_delay)
            return True

        except Exception as e:
            print(f"执行操作失败: {e}")
            return False

    def _to_absolute(self, x: int, y: int) -> Tuple[int, int]:
        """将窗口相对坐标转为屏幕绝对坐标"""
        if self.window:
            return (self.window.rect[0] + x, self.window.rect[1] + y)
        return (x, y)


class AIAutomation:
    """
    AI 视觉自动化主类
    整合窗口选择、截图、AI 分析、操作执行
    """

    def __init__(self, api_key: str, base_url: str = None, model: str = None):
        """
        初始化
        :param api_key: AI API 密钥
        :param base_url: API 地址
        :param model: 模型名称
        """
        if not HAS_GUI:
            raise ImportError("请安装依赖: pip install pyautogui pywin32")
        if not HAS_PIL:
            raise ImportError("请安装依赖: pip install pillow")

        self.ai_client = AIVisionClient(api_key, base_url, model)
        self.window: Optional[WindowInfo] = None
        self.executor: Optional[ActionExecutor] = None
        self.max_steps = 20  # 最大操作步数
        self.screenshot_dir = "screenshots"
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def select_window_by_title(self, title: str) -> bool:
        """通过标题选择窗口"""
        self.window = WindowSelector.find_window(title=title)
        if self.window:
            self.executor = ActionExecutor(self.window)
            print(f"已选择窗口: {self.window.title}")
            return True
        print(f"未找到窗口: {title}")
        return False

    def select_window_by_click(self) -> bool:
        """
        通过鼠标点击选择窗口
        用户点击目标窗口后，自动选中该窗口
        """
        print("请在 5 秒内点击目标窗口...")
        time.sleep(5)

        self.window = WindowSelector.get_window_at_cursor()
        if self.window:
            self.executor = ActionExecutor(self.window)
            print(f"已选择窗口: {self.window.title}")
            return True
        print("未能获取窗口")
        return False

    def list_windows(self) -> List[WindowInfo]:
        """列出所有可见窗口"""
        windows = WindowSelector.list_windows()
        print(f"\n找到 {len(windows)} 个窗口:")
        for i, win in enumerate(windows):
            print(f"  {i+1}. {win.title[:50]}")
        return windows

    def select_window_by_index(self, index: int) -> bool:
        """通过索引选择窗口"""
        windows = WindowSelector.list_windows()
        if 0 <= index < len(windows):
            self.window = windows[index]
            self.executor = ActionExecutor(self.window)
            print(f"已选择窗口: {self.window.title}")
            return True
        print(f"无效索引: {index}")
        return False

    def execute_task(self, task: str, verbose: bool = True) -> bool:
        """
        执行自动化任务
        :param task: 任务描述，如 "点击设置按钮，然后找到账号管理"
        :param verbose: 是否打印详细信息
        :return: 是否成功
        """
        if not self.window:
            print("请先选择目标窗口")
            return False

        print(f"\n{'='*60}")
        print(f"开始执行任务: {task}")
        print(f"目标窗口: {self.window.title}")
        print(f"{'='*60}\n")

        # 激活窗口
        WindowSelector.focus_window(self.window)

        context = ""  # 操作上下文
        step = 0

        while step < self.max_steps:
            step += 1
            print(f"\n--- 步骤 {step} ---")

            # 截图
            screenshot = ScreenCapture.capture_window(self.window)
            if not screenshot:
                print("截图失败")
                return False

            # 保存截图（调试用）
            if verbose:
                screenshot_path = os.path.join(
                    self.screenshot_dir,
                    f"step_{step}_{int(time.time())}.png"
                )
                screenshot.save(screenshot_path)
                print(f"截图已保存: {screenshot_path}")

            # AI 分析
            action = self.ai_client.analyze_and_act(screenshot, task, context)

            if not action:
                print("AI 分析失败")
                return False

            print(f"AI 决策: {action.type.value}")
            print(f"描述: {action.description}")
            print(f"置信度: {action.confidence:.2f}")

            # 检查是否完成
            if action.type == ActionType.DONE:
                print(f"\n✓ 任务完成: {action.description}")
                return True

            if action.type == ActionType.FAILED:
                print(f"\n✗ 任务失败: {action.description}")
                return False

            # 执行操作
            if not self.executor.execute(action):
                print("操作执行失败")
                return False

            # 更新上下文
            context += f"\n步骤{step}: {action.description}"

            # 等待界面响应
            time.sleep(0.5)

        print(f"\n✗ 达到最大步数限制 ({self.max_steps})")
        return False

    def single_action(self, instruction: str) -> bool:
        """
        执行单个操作（不循环）
        :param instruction: 操作指令，如 "点击登录按钮"
        """
        if not self.window:
            print("请先选择目标窗口")
            return False

        WindowSelector.focus_window(self.window)
        screenshot = ScreenCapture.capture_window(self.window)

        if not screenshot:
            return False

        action = self.ai_client.analyze_and_act(screenshot, instruction)

        if action and action.type not in (ActionType.DONE, ActionType.FAILED):
            return self.executor.execute(action)

        return False


# ==================== 便捷函数 ====================

def create_automation(api_key: str, base_url: str = None, model: str = None) -> AIAutomation:
    """创建 AI 自动化实例"""
    return AIAutomation(api_key, base_url, model)


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 配置 AI API
    API_KEY = "your-api-key"  # 替换为你的 API Key
    BASE_URL = "https://api.openai.com/v1"  # 或其他兼容 API
    MODEL = "gpt-4o"  # 支持视觉的模型

    # 创建自动化实例
    auto = AIAutomation(API_KEY, BASE_URL, MODEL)

    # 方式1: 列出窗口并选择
    auto.list_windows()
    # auto.select_window_by_index(0)

    # 方式2: 通过标题选择
    # auto.select_window_by_title("记事本")

    # 方式3: 鼠标点击选择
    # auto.select_window_by_click()

    # 执行任务
    # auto.execute_task("点击文件菜单，然后点击新建")

