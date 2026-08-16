#!/bin/bash
# ==============================================================================
# Wanqing AI - 主启动脚本（Linux/macOS）
# ==============================================================================
# 定位：Windows 用户请使用根目录 start_all.ps1
#       Linux/macOS 用户使用本脚本 start_all.sh
# 架构：Agent(8001) → 感知服务(8000) → Java(8080) → Vue(5173)
# 启动步骤：检查环境 → 安装依赖 → 启动 Python 服务 → 启动 Java → 启动 Vue
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

# 确保日志目录存在
mkdir -p "$LOG_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  [$1/$2] $3${NC}"
    echo -e "${CYAN}============================================================${NC}"
}

TOTAL_STEPS=6

echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  Wanqing AI - One-Click Startup (Linux/macOS)${NC}"
echo -e "${CYAN}  Architecture: Percept(8000) + Agent(8001) + Java(8080) + Vue(5173)${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# ================================================================
# 1. 检查 Python 环境
# ================================================================
log_step 1 $TOTAL_STEPS "Checking Python environment"
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 not found. Please install Python 3.10+."
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
log_info "Detected Python $PYTHON_VERSION"

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
    log_warn "Python 3.10+ recommended."
fi

# ================================================================
# 2. 检查/启动 Redis
# ================================================================
log_step 2 $TOTAL_STEPS "Checking Redis"
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &> /dev/null; then
        log_info "Redis is online"
    else
        log_warn "Redis not running, attempting to start..."
        if command -v redis-server &> /dev/null; then
            redis-server --daemonize yes --loglevel warning 2>/dev/null || true
            sleep 2
            if redis-cli ping &> /dev/null; then
                log_info "Redis started successfully"
            else
                log_warn "Redis failed to start. Agent will use fallback rule engine."
            fi
        else
            log_warn "redis-server not found. Skipping."
        fi
    fi
else
    log_warn "redis-cli not found. Agent will use fallback rule engine."
fi

# ================================================================
# 3. 启动 Python Agent（端口 8001）
# ================================================================
log_step 3 $TOTAL_STEPS "Starting Python Agent (port 8001)"

AGENT_DIR="$SCRIPT_DIR/Agent"

if curl -s http://localhost:8001/health &> /dev/null; then
    log_warn "Agent already running (port 8001), skipping."
else
    # 安装依赖
    if [[ -f "$AGENT_DIR/requirements.txt" ]]; then
        log_info "Installing Agent dependencies..."
        pip3 install -q -r "$AGENT_DIR/requirements.txt" 2>/dev/null || \
            log_warn "Some dependencies failed to install."
    fi

    # 确定 Python 命令（优先虚拟环境）
    if [[ -f "$AGENT_DIR/venv2.0/bin/python3" ]]; then
        AGENT_PYTHON="$AGENT_DIR/venv2.0/bin/python3"
    elif [[ -f "$AGENT_DIR/venv/bin/python3" ]]; then
        AGENT_PYTHON="$AGENT_DIR/venv/bin/python3"
    else
        AGENT_PYTHON="python3"
    fi

    log_info "Starting Agent (Python: $AGENT_PYTHON)..."
    nohup $AGENT_PYTHON "$AGENT_DIR/main.py" \
        > "$LOG_DIR/agent.log" 2>&1 &
    AGENT_PID=$!
    log_info "Agent process started (PID $AGENT_PID), waiting for service..."

    # 等待就绪（最多 30 秒）
    for i in $(seq 1 30); do
        sleep 1
        if curl -s http://localhost:8001/health &> /dev/null; then
            log_info "Agent service ready (PID $AGENT_PID)"
            break
        fi
        echo -n "."
    done
    echo

    if ! curl -s http://localhost:8001/health &> /dev/null; then
        log_warn "Agent timeout (30s). Check logs: $LOG_DIR/agent.log"
    fi
fi

# ================================================================
# 4. 启动 Python 感知服务（端口 8000）
# ================================================================
log_step 4 $TOTAL_STEPS "Starting Python Perception Service (port 8000)"

BACKEND_DIR="$SCRIPT_DIR/backend"
PERCEPTION_DIR="$SCRIPT_DIR/perception"

if curl -s http://localhost:8000/health &> /dev/null; then
    log_warn "Perception service already running (port 8000), skipping."
else
    # 安装依赖
    if [[ -f "$PERCEPTION_DIR/requirements.txt" ]]; then
        log_info "Installing Perception dependencies..."
        pip3 install -q -r "$PERCEPTION_DIR/requirements.txt" 2>/dev/null || \
            log_warn "Some dependencies failed to install."
    fi

    # 确定 Python 命令（优先虚拟环境）
    if [[ -f "$PERCEPTION_DIR/venv/bin/python3" ]]; then
        PERCEPTION_PYTHON="$PERCEPTION_DIR/venv/bin/python3"
    else
        PERCEPTION_PYTHON="python3"
    fi

    log_info "Starting Perception Service (Python: $PERCEPTION_PYTHON)..."
    nohup $PERCEPTION_PYTHON "$PERCEPTION_DIR/main.py" \
        > "$LOG_DIR/perception.log" 2>&1 &
    PERCEPTION_PID=$!
    log_info "Perception process started (PID $PERCEPTION_PID)..."
    sleep 3

    if curl -s http://localhost:8000/health &> /dev/null; then
        log_info "Perception service ready (PID $PERCEPTION_PID)"
    else
        log_warn "Perception may not be ready. Check: $LOG_DIR/perception.log"
    fi
fi

# ================================================================
# 5. 启动 Java Spring Boot（端口 8080）
# ================================================================
log_step 5 $TOTAL_STEPS "Starting Java Spring Boot (port 8080)"

if curl -s http://localhost:8080/health &> /dev/null; then
    log_warn "Java already running (port 8080), skipping."
else
    log_info "Starting Java Spring Boot (takes 30~120 seconds)..."

    if command -v mvn &> /dev/null; then
        MVN_CMD="mvn"
    elif [[ -f "$BACKEND_DIR/mvnw" ]]; then
        MVN_CMD="$BACKEND_DIR/mvnw"
        chmod +x "$BACKEND_DIR/mvnw"
    else
        log_error "Maven (mvn) not found and mvnw missing."
        log_info "Download: https://maven.apache.org/install.html"
        exit 1
    fi

    nohup $MVN_CMD spring-boot:run \
        -f "$BACKEND_DIR/pom.xml" \
        > "$LOG_DIR/java.log" 2>&1 &
    JAVA_PID=$!
    log_info "Java process started (PID $JAVA_PID, takes 30~120 seconds)."
    log_info "Java log: $LOG_DIR/java.log"
fi

# ================================================================
# 6. 启动 Vue 前端（端口 5173）
# ================================================================
log_step 6 $TOTAL_STEPS "Starting Vue Frontend (port 5173)"

FRONTEND_DIR="$SCRIPT_DIR/frontend"

if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
    log_warn "Frontend source not found at $FRONTEND_DIR, skipping."
else
    if ! command -v npm &> /dev/null; then
        log_error "npm not found. Please install Node.js."
    else
        if curl -s http://localhost:5173 &> /dev/null; then
            log_warn "Vue frontend already running (port 5173), skipping."
        else
            log_info "Starting Vue Frontend..."
            nohup npm run dev -- --host \
                > "$LOG_DIR/frontend.log" 2>&1 &
            FRONTEND_PID=$!
            log_info "Frontend started (PID $FRONTEND_PID)..."
            sleep 5
        fi
    fi
fi

# ================================================================
# 完成提示
# ================================================================
echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  All services startup complete!${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""
echo "  Service Status:"
echo ""
echo "  - Python Perception (8000): http://localhost:8000"
echo "  - Python Agent (8001):       http://localhost:8001/health"
echo "  - Java Spring Boot (8080):   http://localhost:8080"
echo "  - Vue Frontend (5173):       http://localhost:5173"
echo ""
echo -e "  Access frontend: ${GREEN}http://localhost:5173${NC}"
echo ""
echo "  Notes:"
echo "  1. Java takes 30~120 seconds on first run (downloading dependencies)."
echo "  2. Agent requires DEEPSEEK_API_KEY in Agent/.env"
echo "  3. Perception needs camera permission (falls back gracefully without)."
echo "  4. If Agent is unavailable, backend falls back to rule engine."
echo ""
  echo "  Log files:"
  echo "  - Agent:       $LOG_DIR/agent.log"
  echo "  - Perception:  $LOG_DIR/perception.log"
  echo "  - Java:        $LOG_DIR/java.log"
  echo "  - Frontend:    $LOG_DIR/frontend.log"
  echo ""
