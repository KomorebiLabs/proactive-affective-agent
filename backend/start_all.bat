@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ================================================================
echo   Wanqing AI - Windows 全栈备用启动脚本
echo   位置：backend/start_all.bat
echo   用途：主入口 start_all.ps1 的 Windows 备用
echo ================================================================
echo.

:: ================================================================
:: 0. 配置路径变量
:: ================================================================
set "PROJECT_ROOT=%~dp0.."
set "AGENT_DIR=%PROJECT_ROOT%\Agent"
set "BACKEND_DIR=%~dp0"
set "PERCEPTION_DIR=%PROJECT_ROOT%\perception"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"

:: ================================================================
:: 1. 检查 Python 环境
:: ================================================================
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

python --version | findstr /C:"3.10" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    python --version | findstr /C:"3.11" >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        python --version | findstr /C:"3.12" >nul 2>&1
        if %ERRORLEVEL% neq 0 (
            echo [WARN] Python 3.10+ recommended. Current version:
            python --version
        )
    )
)

:: ================================================================
:: 2. 启动 Redis（后台）
:: ================================================================
echo [1/5] Checking Redis...
where redis-server >nul 2>&1
if %ERRORLEVEL% equ 0 (
    redis-cli ping >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo      Starting Redis (persistent mode)...
        if exist "%PROJECT_ROOT%\redis.persist.conf" (
            start /B redis-server "%PROJECT_ROOT%\redis.persist.conf" >nul 2>&1
        ) else (
            start /B redis-server >nul 2>&1
        )
        timeout /t 2 /nobreak >nul
    ) else (
        echo      Redis is online
    )
) else (
    echo [WARN] redis-server not found. Skipping (Agent will use fallback rule engine).
)

:: ================================================================
:: 3. 启动 Python Agent（端口 8001）
:: ================================================================
echo [2/5] Starting Python Agent (LangGraph, port 8001)...
if not exist "%AGENT_DIR%\main.py" (
    echo [ERROR] Agent/main.py not found.
    pause
    exit /b 1
)

:: 检查端口是否已被占用
netstat -ano | findstr :8001 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo      Agent is already running (port 8001), skipping.
    goto :start_perception
)

:: 优先使用 venv2.0 中的 Python
set "AGENT_PYTHON="
if exist "%AGENT_DIR%\venv2.0\Scripts\python.exe" (
    set "AGENT_PYTHON=%AGENT_DIR%\venv2.0\Scripts\python.exe"
) else (
    set "AGENT_PYTHON=python"
)

start /B cmd /c "title Python Agent^(8001^) && "!AGENT_PYTHON!" "%AGENT_DIR%\main.py" 2^>^&1"
echo      Agent started in background (port 8001).
timeout /t 3 /nobreak >nul

:start_perception

:: ================================================================
:: 4. 启动 Python 感知服务（端口 8000）
:: ================================================================
echo [3/5] Starting Python Perception Service (port 8000)...
if not exist "%PERCEPTION_DIR%\main.py" (
    echo [ERROR] perception/main.py not found.
    pause
    exit /b 1
)

netstat -ano | findstr :8000 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo      Perception service is already running (port 8000), skipping.
    goto :start_java
)

:: 优先使用 venv 中的 Python
set "PERCEPTION_PYTHON="
if exist "%PERCEPTION_DIR%\venv\Scripts\python.exe" (
    set "PERCEPTION_PYTHON=%PERCEPTION_DIR%\venv\Scripts\python.exe"
) else (
    set "PERCEPTION_PYTHON=python"
)

start /B cmd /c "title Perception^(8000^) && "!PERCEPTION_PYTHON!" "%PERCEPTION_DIR%\main.py" 2^>^&1"
echo      Perception service started in background (port 8000).
timeout /t 3 /nobreak >nul

:start_java

:: ================================================================
:: 5. 启动 Java Spring Boot（端口 8080）
:: ================================================================
echo [4/5] Starting Java Spring Boot (port 8080)...
if not exist "%BACKEND_DIR%\src\main\java" (
    echo [WARN] Java source not found. Skipping (please import into IDE manually).
    goto :start_frontend
)

:: 确定 Maven 命令
set "MVN_CMD="
if exist "%BACKEND_DIR%\mvnw.cmd" (
    set "MVN_CMD=%BACKEND_DIR%\mvnw.cmd"
) else (
    where mvn >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "MVN_CMD=mvn"
    )
)

if "%MVN_CMD%"=="" (
    echo [WARN] Maven not found. Skipping Java startup.
    goto :start_frontend
)

netstat -ano | findstr :8080 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo      Java is already running (port 8080), skipping.
    goto :start_frontend
)

:: 启动 Java（使用 mvnw.cmd 或 mvn）
start /B cmd /c "title Java Spring Boot^(8080^) && chcp 65001 >nul 2>&1 && set MAVEN_OPTS=-Dfile.encoding=UTF-8 && cd /d "%BACKEND_DIR%" && "%MVN_CMD%" spring-boot:run 2^>^&1"
echo      Java started in background (port 8080, takes 30~120 seconds to ready).
timeout /t 5 /nobreak >nul

:start_frontend

:: ================================================================
:: 6. 启动 Vue 前端（端口 5173）
:: ================================================================
echo [5/5] Starting Vue Frontend (port 5173)...
if not exist "%FRONTEND_DIR%\package.json" (
    echo [WARN] Frontend source not found, skipping.
    goto :done
)

where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARN] npm not found. Please install Node.js.
    goto :done
)

netstat -ano | findstr :5173 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo      Vue is already running (port 5173), skipping.
    goto :done
)

start /B cmd /c "title Vue Frontend^(5173^) && cd /d "%FRONTEND_DIR%" && npm run dev 2^>^&1"
echo      Frontend started in background (port 5173).
timeout /t 5 /nobreak >nul

:done
echo.
echo ================================================================
echo   All services startup complete!
echo ================================================================
echo.
echo   Service Status:
echo.
echo   - Python Perception (8000): http://localhost:8000
echo   - Python Agent (8001):       http://localhost:8001/health
echo   - Java Spring Boot (8080):   http://localhost:8080
echo   - Vue Frontend (5173):        http://localhost:5173
echo.
echo   Notes:
echo   1. Java takes 30~120 seconds to start on first run.
echo   2. Agent requires DEEPSEEK_API_KEY in Agent/.env
echo   3. Perception service needs camera permission.
echo   4. If Agent is unavailable, backend falls back to rule engine.
echo.
echo   Access frontend: http://localhost:5173
echo ================================================================
pause
