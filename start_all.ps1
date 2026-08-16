# ==============================================================================
# 婉情AI - 统一启动脚本（Windows PowerShell）
# ==============================================================================
# 架构：Agent(8001) → 感知服务(8000) → Java(8080) → Vue(5173)
# 启动步骤（共 8 步）：
#   1. 检查 Python / Node.js 环境
#   2. 检查 Redis（可选）
#   3. 检查 Agent / 感知服务配置文件
#   4. 检查 / 安装 Agent Python 依赖
#   5. 检查 / 安装感知服务 Python 依赖
#   6. 检查 / 安装前端 npm 依赖
#   7. 启动 Python 服务（Agent + 感知服务）
#   8. 启动 Java 后端 + Vue 前端
# 特性：
#   - 自动检测并安装依赖
#   - 统一健康检查端点 /health
#   - 详细的日志和错误报告
#   - 服务依赖降级（某个服务失败不影响其他服务）
# ==============================================================================

$ErrorActionPreference = "Continue"

# ─────────────────────────────────────────────────────────────────────────────
# 全局变量
# ─────────────────────────────────────────────────────────────────────────────
$Global:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Global:AgentDir = Join-Path $Global:ProjectRoot "Agent"
$Global:BackendDir = Join-Path $Global:ProjectRoot "backend"
$Global:PerceptionDir = Join-Path $Global:ProjectRoot "perception"
$Global:FrontendDir = Join-Path $Global:ProjectRoot "frontend"

$Global:LogDir = Join-Path $Global:ProjectRoot "logs"

# 日志文件路径（供函数使用）
$AgentLog = Join-Path $Global:LogDir "agent.log"
$PerceptionLog = Join-Path $Global:LogDir "perception.log"
$JavaLog = Join-Path $Global:LogDir "java.log"
$FrontendLog = Join-Path $Global:LogDir "frontend.log"

# 健康检查配置
$HealthEndpoints = @{
    "Agent" = "http://localhost:8001/health"
    "感知服务" = "http://localhost:8000/health"
    "Java" = "http://localhost:8080/health"
    "Vue" = "http://localhost:5173"
}

# 启动超时配置（秒）
$Timeouts = @{
    "Agent" = 60
    "感知服务" = 30
    "Java" = 120
    "Vue" = 30
}

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────
function Write-Header {
    param($Title, $Subtitle = "")
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  $Title" -ForegroundColor Cyan
    if ($Subtitle) {
        Write-Host "║  $Subtitle" -ForegroundColor Gray
    }
    Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param($Num, $Total, $Msg)
    Write-Host ""
    Write-Host "─── [$Num/$Total] $Msg ───" -ForegroundColor Cyan
}

function Write-Status {
    param($OK, $Msg)
    if ($OK) {
        Write-Host "[OK]   $Msg" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Msg" -ForegroundColor Red
    }
}

function Write-Info {
    param($Msg)
    Write-Host "[INFO] $Msg" -ForegroundColor Gray
}

function Write-Warn {
    param($Msg)
    Write-Host "[WARN] $Msg" -ForegroundColor Yellow
}

function Write-Err {
    param($Msg)
    Write-Host "[ERROR] $Msg" -ForegroundColor Red
}

function Write-Success {
    param($Msg)
    Write-Host "[OK]   $Msg" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────────────────────
# 日志工具
# ─────────────────────────────────────────────────────────────────────────────
function Start-Logging {
    if (-not (Test-Path $Global:LogDir)) {
        New-Item -ItemType Directory -Path $Global:LogDir -Force | Out-Null
    }
    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $Global:CurrentLogFile = Join-Path $Global:LogDir "startup_$timestamp.log"
}

function Log-ToFile {
    param($Level, $Msg)
    $entry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Msg"
    Add-Content -Path $Global:CurrentLogFile -Value $entry -Encoding UTF8
}

# ─────────────────────────────────────────────────────────────────────────────
# 健康检查函数
# ─────────────────────────────────────────────────────────────────────────────
function Test-ServiceHealth {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 30,
        [switch]$Silent
    )

    Log-ToFile "INFO" "检查 $Name 服务: $Url"

    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                if (-not $Silent) {
                    Write-Success "$Name 服务就绪（耗时 $($i + 1) 秒）"
                }
                Log-ToFile "INFO" "$Name 服务就绪"
                return $true
            }
        } catch {
            # 连接被拒绝或超时，继续等待
        }

        if (-not $Silent) {
            Write-Host "." -NoNewline
        }
        Start-Sleep 1
    }

    if (-not $Silent) {
        Write-Host ""
        Write-Err "$Name 服务超时（${TimeoutSeconds}秒内未响应）"
    }
    Log-ToFile "WARN" "$Name 服务超时"
    return $false
}

# ─────────────────────────────────────────────────────────────────────────────
# 服务启动函数
# ─────────────────────────────────────────────────────────────────────────────
function Start-PythonService {
    param(
        [string]$Name,
        [string]$WorkingDir,
        [string]$Script,
        [string]$LogFile,
        [string]$HealthUrl,
        [int]$Timeout = 30,
        [string]$PythonEnv = $null  # 可选：指定虚拟环境
    )

    Write-Host ""
    Write-Info "启动 $Name..."

    # 准备启动命令
    $pythonCmd = if ($PythonEnv) { Join-Path $PythonEnv "Scripts\python.exe" } else { "python" }

    # 正确处理日志文件名（避免路径拼接错误）
    $logFileName = Split-Path $LogFile -Leaf
    $startupLog = Join-Path $Global:LogDir "python_${logFileName}_startup.log"
    $startupErr = Join-Path $Global:LogDir "python_${logFileName}_startup.err"

    # 检查是否已在运行
    try {
        $check = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($check.StatusCode -eq 200) {
            Write-Success "$Name 已在运行，跳过启动"
            return $true
        }
    } catch { }

    # 启动进程
    try {
        # 使用 Start-Process 在后台启动，输出重定向到日志文件
        $env:PYTHONIOENCODING = "utf-8"
        $process = Start-Process -FilePath $pythonCmd `
            -ArgumentList $Script `
            -WorkingDirectory $WorkingDir `
            -RedirectStandardOutput $startupLog `
            -RedirectStandardError $startupErr `
            -NoNewWindow -PassThru

        Write-Info "$Name 进程 PID: $($process.Id)"

        # 等待服务就绪
        $result = Test-ServiceHealth -Name $Name -Url $HealthUrl -TimeoutSeconds $Timeout

        if ($result) {
            return $true
        } else {
            Write-Warn "$Name 可能启动失败，请检查日志: $startupLog"
            return $false
        }
    } catch {
        Write-Err "启动 $Name 失败: $_"
        Log-ToFile "ERROR" "启动 $Name 失败: $_"
        return $false
    }
}

function Start-JavaService {
    param(
        [string]$Name,
        [string]$WorkingDir,
        [string]$HealthUrl,
        [int]$Timeout = 120
    )

    Write-Host ""
    Write-Info "启动 $Name..."

    # 检查是否已在运行
    try {
        $check = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($check.StatusCode -eq 200 -or $check.StatusCode -eq 404) {
            Write-Success "$Name 已在运行，跳过启动"
            return $true
        }
    } catch { }

    # 检查 Maven Wrapper
    $mvnCmd = if (Test-Path (Join-Path $WorkingDir "mvnw.cmd")) {
        Join-Path $WorkingDir "mvnw.cmd"
    } elseif (Get-Command mvn -ErrorAction SilentlyContinue) {
        "mvn"
    } else {
        $null
    }

    if (-not $mvnCmd) {
        Write-Err "未找到 mvn 或 mvnw.cmd，无法启动 Java 服务"
        Log-ToFile "ERROR" "未找到 Maven"
        return $false
    }

    # 准备日志文件
    $javaStartupLog = Join-Path $Global:LogDir "java_startup.log"

    try {
        # 使用 cmd 启动 Maven，设置 UTF-8 编码解决中文乱码问题
        $env:MAVEN_OPTS = "-Dfile.encoding=UTF-8"
        $env:JAVA_TOOL_OPTIONS = "-Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8"

        if ($mvnCmd -like "*mvnw.cmd") {
            $cmd = "cmd"
            $args = "/c chcp 65001 >nul && cd /d `"$WorkingDir`" && `"$mvnCmd`" spring-boot:run 2>&1 | Out-File -FilePath `"$javaStartupLog`" -Encoding UTF8"
        } else {
            $cmd = "cmd"
            $args = "/c chcp 65001 >nul && cd /d `"$WorkingDir`" && mvn spring-boot:run 2>&1 | Out-File -FilePath `"$javaStartupLog`" -Encoding UTF8"
        }

        Start-Process -FilePath $cmd -ArgumentList $args -NoNewWindow

        Write-Info "$Name 正在启动（首次约需 3~5 分钟下载依赖）..."
        Write-Info "Java 启动日志: $javaStartupLog"

        # 等待 Java 启动（带健康检查，最多等待 300 秒）
        $javaReady = $false
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep 5
            try {
                $check = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
                if ($check.StatusCode -eq 200) {
                    Write-Success "$Name 服务就绪（耗时 $(($i + 1) * 5) 秒）"
                    $javaReady = $true
                    break
                }
            } catch { }
            Write-Host "." -NoNewline
        }

        if (-not $javaReady) {
            Write-Warn "$Name 可能启动失败，请检查日志: $javaStartupLog"
        }

        return $true
    } catch {
        Write-Err "启动 $Name 失败: $_"
        Log-ToFile "ERROR" "启动 $Name 失败: $_"
        return $false
    }
}

function Start-VueService {
    param(
        [string]$Name,
        [string]$WorkingDir,
        [string]$LogFile,
        [string]$HealthUrl,
        [int]$Timeout = 30
    )

    Write-Host ""
    Write-Info "启动 $Name..."

    # 检查是否已在运行
    try {
        $check = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($check.StatusCode -eq 200) {
            Write-Success "$Name 已在运行，跳过启动"
            return $true
        }
    } catch { }

    try {
        # 正确处理日志文件名
        $logFileName = Split-Path $LogFile -Leaf
        $startupLog = Join-Path $Global:LogDir "vue_${logFileName}_startup.log"

        Start-Process -FilePath "npm" `
            -ArgumentList "run dev -- --host" `
            -WorkingDirectory $WorkingDir `
            -RedirectStandardOutput $startupLog `
            -NoNewWindow

        $result = Test-ServiceHealth -Name $Name -Url $HealthUrl -TimeoutSeconds $Timeout

        if ($result) {
            return $true
        } else {
            Write-Warn "$Name 可能启动失败，请检查日志: $startupLog"
            return $false
        }
    } catch {
        Write-Err "启动 $Name 失败: $_"
        Log-ToFile "ERROR" "启动 $Name 失败: $_"
        return $false
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────
function Start-All {
    # 初始化日志
    Start-Logging
    Log-ToFile "INFO" "===== 婉情AI 启动脚本开始 ====="

    # 设置环境变量（解决编码问题）
    $env:PYTHONIOENCODING = "utf-8"
    $env:JAVA_TOOL_OPTIONS = "-Dfile.encoding=UTF-8"

    # ─────────────────────────────────────────────────────────────────────────
    # 1. 检查 Python 环境
    # ─────────────────────────────────────────────────────────────────────────
    Write-Header "婉情AI - 一键启动脚本" "架构：Agent(8001) → 感知服务(8000) → Java(8080) → Vue(5173)，共 8 个检查步骤"

    Write-Step 1 7 "检查 Python / Node.js 环境"

    # 1.1 检查 Python
    try {
        $pythonVersion = python --version 2>&1
        Write-Info "Python: $pythonVersion"
        Log-ToFile "INFO" "Python: $pythonVersion"
    } catch {
        Write-Err "未找到 Python 3.10+，请先安装 Python"
        Log-ToFile "ERROR" "Python 未安装"
        return
    }

    # 1.2 检查 Node.js（可选）
    try {
        $nodeVersion = node --version 2>&1
        $npmVersion = npm --version 2>&1
        Write-Info "Node.js: $nodeVersion, npm: $npmVersion"
        Log-ToFile "INFO" "Node.js: $nodeVersion, npm: $npmVersion"
    } catch {
        Write-Warn "Node.js 未安装，Vue 前端将无法启动"
        Log-ToFile "WARN" "Node.js 未安装"
    }

    # 1.3 检查 Redis（未运行则尝试用 redis.persist.conf 拉起）
    Write-Step 2 7 "检查 Redis（可选）"
    try {
        $redisCheck = redis-cli ping 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Redis 已在线"
            Log-ToFile "INFO" "Redis 已在线"
        } elseif (Get-Command redis-server -ErrorAction SilentlyContinue) {
            Write-Warn "Redis 未运行，尝试启动（持久化模式）..."
            $redisConf = Join-Path $Global:ProjectRoot "redis.persist.conf"
            if (Test-Path $redisConf) {
                Start-Process redis-server -ArgumentList "`"$redisConf`"" -WindowStyle Hidden
            } else {
                Start-Process redis-server -WindowStyle Hidden
            }
            Start-Sleep -Seconds 2
            $redisCheck = redis-cli ping 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Redis 已启动"
                Log-ToFile "INFO" "Redis 已由脚本启动"
            } else {
                Write-Warn "Redis 启动失败（Agent 将使用规则引擎降级，不影响核心功能）"
                Log-ToFile "WARN" "Redis 启动失败"
            }
        } else {
            Write-Warn "Redis 未安装（Agent 将使用规则引擎降级，不影响核心功能）"
            Log-ToFile "INFO" "Redis 未安装"
        }
    } catch {
        Write-Warn "Redis 未安装（Agent 将使用规则引擎降级，不影响核心功能）"
        Log-ToFile "INFO" "Redis 未安装"
    }

    # 1.4 检查关键配置文件
    Write-Step 3 7 "检查配置文件"
    $agentEnvPath = Join-Path $Global:AgentDir ".env"
    if (Test-Path $agentEnvPath) {
        Write-Success "Agent 配置: $agentEnvPath"
    } else {
        Write-Warn "Agent 配置缺失: $agentEnvPath"
        Write-Warn "请创建 Agent/.env 文件并配置 DEEPSEEK_API_KEY"
    }

    $perceptionEnvPath = Join-Path $Global:PerceptionDir ".env"
    if (Test-Path $perceptionEnvPath) {
        Write-Success "感知服务配置: $perceptionEnvPath"
    } else {
        Write-Warn "感知服务配置缺失: $perceptionEnvPath"
    }

    # 1.5 检查 Python 依赖（Agent）
    Write-Step 4 7 "检查 Agent Python 依赖"
    # Agent 实际 venv 为 venv2.0（sh/bat 脚本同此约定），不存在时回退 venv
    $agentVenv = Join-Path $Global:AgentDir "venv2.0"
    if (-not (Test-Path (Join-Path $agentVenv "Lib\site-packages"))) {
        $agentVenv = Join-Path $Global:AgentDir "venv"
    }
    $agentSitePackages = Join-Path $agentVenv "Lib\site-packages"
    if (Test-Path $agentSitePackages) {
        Write-Success "Agent Python 依赖已安装: $agentSitePackages"
    } else {
        Write-Warn "Agent Python 依赖未安装，尝试安装..."
        try {
            Push-Location $Global:AgentDir
            python -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
            Pop-Location
            Write-Success "Agent Python 依赖安装完成"
        } catch {
            Write-Err "Agent Python 依赖安装失败，请手动运行: cd $Global:AgentDir; pip install -r requirements.txt"
            Log-ToFile "ERROR" "Agent Python 依赖安装失败"
        }
    }

    # 1.6 检查 Python 依赖（感知服务）
    Write-Step 5 7 "检查感知服务 Python 依赖"
    $perceptionSitePackages = Join-Path $Global:PerceptionDir "venv\Lib\site-packages"
    if (Test-Path $perceptionSitePackages) {
        Write-Success "感知服务 Python 依赖已安装: $perceptionSitePackages"
    } else {
        Write-Warn "感知服务 Python 依赖未安装，尝试安装..."
        try {
            Push-Location $Global:PerceptionDir
            python -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
            Pop-Location
            Write-Success "感知服务 Python 依赖安装完成"
        } catch {
            Write-Err "感知服务 Python 依赖安装失败，请手动运行: cd $Global:PerceptionDir; pip install -r requirements.txt"
            Log-ToFile "ERROR" "感知服务 Python 依赖安装失败"
        }
    }

    # 1.7 检查 npm 依赖（前端）
    Write-Step 6 7 "检查前端依赖"
    $frontendNodeModules = Join-Path $Global:FrontendDir "node_modules"
    if (Test-Path $frontendNodeModules) {
        Write-Success "npm 依赖已安装: $frontendNodeModules"
    } else {
        Write-Warn "npm 依赖未安装，尝试安装..."
        try {
            Push-Location $Global:FrontendDir
            npm install 2>&1 | Out-Null
            Pop-Location
            Write-Success "npm 依赖安装完成"
        } catch {
            Write-Err "npm 依赖安装失败，请手动运行: cd $Global:FrontendDir && npm install"
            Log-ToFile "ERROR" "npm 依赖安装失败"
        }
    }

    # ─────────────────────────────────────────────────────────────────────────
    # 5. 启动 Python 服务（Agent → 感知服务）
    # ─────────────────────────────────────────────────────────────────────────
    Write-Step 7 7 "启动 Python 服务"

    # 7.1 启动 Agent（端口 8001）
    Write-Host ""
    Write-Host "─── Agent (8001) ───" -ForegroundColor Yellow

    $agentResult = Start-PythonService `
        -Name "Agent" `
        -WorkingDir $AgentDir `
        -Script "main.py" `
        -LogFile $AgentLog `
        -HealthUrl "http://localhost:8001/health" `
        -Timeout 60

    # 7.2 启动感知服务（端口 8000）
    Write-Host ""
    Write-Host "─── 感知服务 (8000) ───" -ForegroundColor Yellow

    $perceptionResult = Start-PythonService `
        -Name "感知服务" `
        -WorkingDir $PerceptionDir `
        -Script "main.py" `
        -LogFile $PerceptionLog `
        -HealthUrl "http://localhost:8000/health" `
        -Timeout 30

    # ─────────────────────────────────────────────────────────────────────────
    # 7.3 启动 Java 后端 + Vue 前端
    # ─────────────────────────────────────────────────────────────────────────
    Write-Step 8 8 "启动 Java 后端 + Vue 前端"
    Write-Host ""
    Write-Host "─── Java Spring Boot (8080) ───" -ForegroundColor Yellow

    $javaResult = Start-JavaService `
        -Name "Java" `
        -WorkingDir $BackendDir `
        -HealthUrl "http://localhost:8080" `
        -Timeout 120

    # 8.2 启动 Vue 前端（与 Java 并行）
    Write-Host ""
    Write-Host "─── Vue 前端 (5173) ───" -ForegroundColor Yellow

    $vueResult = Start-VueService `
        -Name "Vue" `
        -WorkingDir $FrontendDir `
        -LogFile $FrontendLog `
        -HealthUrl "http://localhost:5173" `
        -Timeout 30

    # ─────────────────────────────────────────────────────────────────────────
    # 8. 最终状态报告
    # ─────────────────────────────────────────────────────────────────────────
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  启动完成 - 服务状态报告" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""

    $services = @(
        @{ Name = "Agent (8001)"; Result = $agentResult; Critical = $false }
        @{ Name = "感知服务 (8000)"; Result = $perceptionResult; Critical = $false }
        @{ Name = "Java (8080)"; Result = $javaResult; Critical = $false }
        @{ Name = "Vue (5173)"; Result = $vueResult; Critical = $false }
    )

    $allCritical = $true
    foreach ($svc in $services) {
        if ($svc.Result) {
            Write-Success "$($svc.Name) 在线"
        } else {
            if ($svc.Critical) {
                Write-Err "$($svc.Name) 离线 [关键]"
                $allCritical = $false
            } else {
                Write-Warn "$($svc.Name) 离线（可能已降级）"
            }
        }
    }

    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  访问地址" -ForegroundColor White
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  前端：http://localhost:5173" -ForegroundColor Green
    Write-Host "  API：  http://localhost:8080" -ForegroundColor Gray
    Write-Host "  Agent：http://localhost:8001/health" -ForegroundColor Gray
    Write-Host "  感知：http://localhost:8000/health" -ForegroundColor Gray
    Write-Host ""

    # 故障排查
    $failedServices = $services | Where-Object { -not $_.Result }
    if ($failedServices) {
        Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Yellow
        Write-Host "  故障排查" -ForegroundColor Yellow
        Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  日志文件位置：" -ForegroundColor White
        Write-Host "    $LogDir" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  常见问题：" -ForegroundColor White
        Write-Host "    1. Agent 启动失败 → 检查 Agent/.env 中的 DEEPSEEK_API_KEY" -ForegroundColor Gray
        Write-Host "    2. 感知服务失败 → 检查摄像头权限或 Python 依赖" -ForegroundColor Gray
        Write-Host "    3. Java 启动慢 → 首次启动需要下载依赖，约 3~5 分钟" -ForegroundColor Gray
        Write-Host ""
    }

    Write-Host "  完整日志：$Global:CurrentLogFile" -ForegroundColor Gray
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan

    Log-ToFile "INFO" "===== 婉情AI 启动脚本完成 ====="
}

# 执行主流程
Start-All
