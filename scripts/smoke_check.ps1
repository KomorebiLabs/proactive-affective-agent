# ==============================================================================
# 婉情AI - 冒烟检查脚本
# 使用方式：powershell -File scripts/smoke_check.ps1
# ==============================================================================
# 检查范围：
#   1. 服务健康检查（Agent/感知服务/Java/Vue）
#   2. 会话创建
#   3. SSE 对话（发送消息，检查最终帧字段）
# ==============================================================================

$ErrorActionPreference = "Continue"

# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────
$Endpoints = @{
    "Agent (8001)" = "http://localhost:8001/health"
    "感知服务 (8000)" = "http://localhost:8000/health"
    "Java (8080)" = "http://localhost:8080/health"
    "Vue (5173)" = "http://localhost:5173"
}

$JavaApi = "http://localhost:8080"
$SessionApi = "$JavaApi/api/v1/session/start"
$ChatApi = "$JavaApi/api/v1/chat/stream"

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────
function Test-Endpoint {
    param($Name, $Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200 -or $resp.StatusCode -eq 404) {
            Write-Host "[PASS] $Name" -ForegroundColor Green
            return $true
        }
    } catch { }
    Write-Host "[FAIL] $Name" -ForegroundColor Red
    return $false
}

function Write-Section {
    param($Title)
    Write-Host ""
    Write-Host "══ $Title ══" -ForegroundColor Cyan
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. 健康检查
# ─────────────────────────────────────────────────────────────────────────────
Write-Section "1. 服务健康检查"

$healthResults = @()
foreach ($name in $Endpoints.Keys) {
    $url = $Endpoints[$name]
    $result = Test-Endpoint -Name $name -Url $url
    $healthResults += @{ Name = $name; Result = $result }
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. 会话创建
# ─────────────────────────────────────────────────────────────────────────────
Write-Section "2. 会话创建测试"

try {
    $body = @{ subjectName = "冒烟测试"; experimentGroup = "A" } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri $SessionApi -Method Post -Body $body -ContentType "application/json" -TimeoutSec 10
    if ($resp.code -eq 200 -and $resp.data.sessionId) {
        $script::SESSION_ID = $resp.data.sessionId
        Write-Host "[PASS] 会话创建成功: $SESSION_ID" -ForegroundColor Green
        $script:SessionOk = $true
    } else {
        Write-Host "[FAIL] 会话创建失败: $($resp | ConvertTo-Json)" -ForegroundColor Red
        $script:SessionOk = $false
    }
} catch {
    Write-Host "[FAIL] 会话创建异常: $_" -ForegroundColor Red
    $script:SessionOk = $false
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. SSE 对话测试
# ─────────────────────────────────────────────────────────────────────────────
Write-Section "3. SSE 对话测试"

if ($SessionOk -and $SESSION_ID) {
    try {
        $body = @{ message = "测试消息"; sessionId = $SESSION_ID } | ConvertTo-Json
        $headers = @{ Authorization = "Bearer $SESSION_ID" }
        $resp = Invoke-WebRequest -Uri $ChatApi -Method Post -Body $body -ContentType "application/json" -Headers $headers -TimeoutSec 60
        
        # 检查响应内容
        $content = $resp.Content
        $hasIsEnd = $content -match '"is_end"\s*:\s*true'
        $hasAction = $content -match '"action"\s*:\s*"'
        $hasTraceId = $content -match '"trace_id"\s*:\s*"'
        $hasUrgency = $content -match '"urgency"\s*:\s*"'
        
        Write-Host "  帧字段检查:" -ForegroundColor Gray
        if ($hasIsEnd) { Write-Host "    [PASS] is_end=true" -ForegroundColor Green } else { Write-Host "    [FAIL] is_end=true" -ForegroundColor Red }
        if ($hasAction) { Write-Host "    [PASS] action 字段存在" -ForegroundColor Green } else { Write-Host "    [FAIL] action 字段缺失" -ForegroundColor Red }
        if ($hasTraceId) { Write-Host "    [PASS] trace_id 字段存在" -ForegroundColor Green } else { Write-Host "    [FAIL] trace_id 字段缺失" -ForegroundColor Red }
        if ($hasUrgency) { Write-Host "    [PASS] urgency 字段存在" -ForegroundColor Green } else { Write-Host "    [FAIL] urgency 字段缺失" -ForegroundColor Red }
        
        if ($hasIsEnd -and $hasAction -and $hasTraceId -and $hasUrgency) {
            Write-Host "[PASS] SSE 对话正常" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] SSE 帧字段不完整" -ForegroundColor Red
        }
    } catch {
        Write-Host "[FAIL] SSE 对话异常: $_" -ForegroundColor Red
    }
} else {
    Write-Host "[SKIP] 会话创建失败，跳过 SSE 测试" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────────────
# 总结
# ─────────────────────────────────────────────────────────────────────────────
Write-Section "冒烟测试总结"

$allPass = $true
foreach ($r in $healthResults) {
    if (-not $r.Result) { $allPass = $false; break }
}
if (-not $SessionOk) { $allPass = $false }

if ($allPass) {
    Write-Host "✅ 所有检查通过" -ForegroundColor Green
} else {
    Write-Host "❌ 存在失败项，请检查上方日志" -ForegroundColor Red
}

Write-Host ""
