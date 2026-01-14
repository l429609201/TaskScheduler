@echo off
chcp 65001 >nul
echo ========================================
echo   任务调度器 - 打包脚本
echo ========================================
echo.

:: 检查 Python 环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python
    pause
    exit /b 1
)

:: 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 PyInstaller...
    pip install pyinstaller
)

echo.
echo [1/3] 清理旧的构建文件...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo.
echo [2/3] 开始打包...
echo.

:: 方式1: 使用 spec 文件打包（推荐）
pyinstaller build.spec

:: 方式2: 直接命令行打包（备选）
:: pyinstaller --noconfirm --onefile --windowed --name "TaskScheduler" main.py

echo.
if exist "dist\TaskScheduler.exe" (
    echo [3/3] 打包完成！
    echo.
    echo 输出文件: dist\TaskScheduler.exe
    echo.
    echo 提示: 运行程序前，确保 config 目录存在
    explorer dist
) else (
    echo [错误] 打包失败，请检查错误信息
)

echo.
pause

