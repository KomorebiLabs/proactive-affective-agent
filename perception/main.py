"""
perception/main.py
婉情AI Python 感知服务主入口
================================
运行端口：8000

职责：
  1. 摄像头视频采集 + MediaPipe 感知提取 → WebSocket 广播到前端
  2. 音频特征提取（openSMILE）→ Redis 实时写入
  3. POST /internal/v1/agent/invoke → 优先转发到 Agent 端口（默认本服务，
     通过 AGENT_BASE_URL 环境变量配置），Agent 不可用时使用本地规则引擎降级响应
  4. POST /internal/v1/session/update → 切换感知引擎 session_id
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 解决 Windows PowerShell 中文编码问题（必须在任何 print/log 之前执行）
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

# 路径修复
_backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _backend_dir)

from socket_manager import manager, MessagePriority
from services.monitor_service import monitor_service
from api.websocket import handle_websocket
from ai_assistant.core.perception_engine import get_perception_engine


# ==============================================================================
# 请求模型
# ==============================================================================

class SessionUpdateReq(BaseModel):
    session_id: str
    user_id: str = ""


class AgentInvokeReq(BaseModel):
    session_id: str
    user_message: str = ""
    emotion_history: list = []
    user_id: str = ""
    task_phase: str = "experiment_task"


# ==============================================================================
# Lifespan（必须在 app 实例化之前定义）
# ==============================================================================

AGENT_BASE_URL: str = os.getenv("AGENT_BASE_URL", "http://localhost:8001")
_AGENT_AVAILABLE: bool = True   # 首次请求后确定


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan 上下文管理器"""
    # startup
    print("=" * 60)
    print("婉情AI 感知服务启动中（端口 8000）...")
    print("=" * 60)
    loop = asyncio.get_running_loop()
    manager.start_sender_workers()
    monitor_service.start(loop)
    print("[OK] 感知服务就绪")
    print(f"   Agent 服务地址: {AGENT_BASE_URL}")
    print(f"   WebSocket 端点: ws://0.0.0.0:8000/ws")
    print(f"   Agent 推理端点: POST /internal/v1/agent/invoke")
    print("=" * 60)
    yield
    # shutdown
    print("[!] 感知服务关闭中...")
    engine = get_perception_engine()
    if engine:
        engine.stop()
    print("[OK] 感知服务已关闭")


# ==============================================================================
# FastAPI 应用实例（必须在所有 @app.* 装饰器之前创建）
# ==============================================================================

app = FastAPI(
    title="Wanqing AI 感知服务",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Agent SSE 转发 / 降级引擎
# ==============================================================================

async def _fetch_agent_via_http(req: AgentInvokeReq) -> Optional[dict]:
    """
    通过 HTTP POST 将请求转发给独立的 Agent 服务（Agent/main.py，端口 8001）。
    返回 agent 返回的 final_response dict，失败返回 None。

    注意：如果 AGENT_BASE_URL 指向本服务（8000），则此函数会递归调用本地引擎；
    为避免循环，优先使用本地规则引擎作为降级路径。
    """
    global _AGENT_AVAILABLE
    # 如果指向本服务，跳过（避免递归调用）
    if "localhost:8000" in AGENT_BASE_URL or "127.0.0.1:8000" in AGENT_BASE_URL:
        _AGENT_AVAILABLE = False
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{AGENT_BASE_URL}/internal/v1/agent/invoke",
                json={
                    "session_id": req.session_id,
                    "user_message": req.user_message,
                    "emotion_history": req.emotion_history,
                    "user_id": req.user_id,
                    "task_phase": req.task_phase,
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                print(f"[main.py] Agent 返回错误 {resp.status_code}: {resp.text[:200]}")
                _AGENT_AVAILABLE = False
                return None

            # 解析 SSE 流，提取最后一帧（包含 final_response）
            lines = resp.text.split("\n")
            for line in reversed(lines):
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if data.get("is_end") and data.get("reply") is not None:
                            return {
                                "action": data.get("action", "intervene"),
                                "reply": data.get("reply", ""),
                                "ui_instruction": data.get("ui_action", {"color": "neutral", "pulse": "slow"}),
                                "vector": data.get("vector", {}),
                                "urgency": data.get("urgency", "low"),
                                "strategy": data.get("strategy"),
                            }
                    except json.JSONDecodeError:
                        continue
            return None

    except Exception as e:
        print(f"[main.py] 无法连接 Agent 服务（{AGENT_BASE_URL}）: {e}")
        _AGENT_AVAILABLE = False
        return None


# OCC 标签（与前端 EmotionRadar 一致）
_OCC_LABELS = ["喜悦", "悲伤", "愤怒", "恐惧", "厌恶", "惊讶", "踏实感", "期待"]

_EMOTION_OCC_RULES = {
    "开心":   {"喜悦": 0.8, "踏实感": 0.4},
    "高兴":   {"喜悦": 0.7, "踏实感": 0.3},
    "喜悦":   {"喜悦": 0.8, "踏实感": 0.4},
    "悲伤":   {"悲伤": 0.8, "踏实感": 0.05},
    "沮丧":   {"悲伤": 0.8, "踏实感": 0.05},
    "焦虑":   {"期待": 0.3, "踏实感": 0.1, "悲伤": 0.3},
    "恐惧":   {"恐惧": 0.8, "踏实感": 0.0},
    "愤怒":   {"愤怒": 0.9, "踏实感": 0.05},
    "厌恶":   {"厌恶": 0.8},
    "惊讶":   {"惊讶": 0.7},
    "平静":   {"踏实感": 0.7, "喜悦": 0.1},
    "中性":   {"踏实感": 0.4},
}


def _build_local_fallback(req: AgentInvokeReq) -> dict:
    """
    本地规则引擎降级响应（当 Agent 服务不可用时使用）。
    基于 emotion_history 中的最新情感记录推断回复和 OCC 向量。
    """
    if req.emotion_history:
        last = req.emotion_history[-1]
        intensity = float(last.get("intensity", 0.5))
        emotion = str(last.get("primary_emotion", "中性"))
    else:
        intensity = 0.3
        emotion = "中性"

    # 填充完整 OCC 八维向量
    occ = _EMOTION_OCC_RULES.get(emotion, {"踏实感": 0.4})
    emotion_vector = {k: occ.get(k, 0.05) for k in _OCC_LABELS}
    emotion_vector[emotion] = max(emotion_vector.get(emotion, 0.0), 0.6)

    # UI 指令 + 关怀回复
    if intensity > 0.75:
        ui_action = {"color": "purple", "pulse": "fast"}
        reply = "我感受到你现在的情绪波动比较明显……深呼吸一下，慢慢来。我在这里陪着你。"
        urgency = "medium"
        action = "intervene"
    elif intensity > 0.5:
        ui_action = {"color": "blue", "pulse": "medium"}
        reply = "我感觉到你可能有些不太舒服……有什么想说的，我愿意听。"
        urgency = "medium"
        action = "subtle"
    elif intensity > 0.3:
        ui_action = {"color": "blue", "pulse": "slow"}
        reply = "你看起来还好，如果想聊聊的话我在这里。"
        urgency = "low"
        action = "subtle"
    else:
        ui_action = {"color": "neutral", "pulse": "slow"}
        reply = "你好呀！我在这里陪着你，有什么想聊聊的吗？"
        urgency = "low"
        action = "subtle"

    return {
        "action": action,
        "urgency": urgency,
        "reply": reply,
        "ui_instruction": ui_action,
        "vector": emotion_vector,
        "strategy": None,
    }


async def _stream_reply(
    reply_text: str,
    ui_action: dict,
    emotion_vector: dict,
    action: str = "subtle",
    urgency: str = "low",
    strategy: Optional[str] = None,
):
    """将完整回复按字切分为 SSE 帧"""
    for i, char in enumerate(reply_text):
        is_end = (i == len(reply_text) - 1)
        payload = {"chunk": char, "is_end": is_end}
        if is_end:
            payload["ui_action"] = ui_action
            payload["reply"] = reply_text
            payload["vector"] = emotion_vector
            payload["action"] = action
            payload["urgency"] = urgency
            if strategy:
                payload["strategy"] = strategy
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.03)

    if not reply_text:
        payload = {
            "chunk": "",
            "is_end": True,
            "ui_action": ui_action,
            "reply": "",
            "vector": emotion_vector,
            "action": action,
            "urgency": urgency,
        }
        if strategy:
            payload["strategy"] = strategy
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ==============================================================================
# API 端点
# ==============================================================================

@app.post("/internal/v1/agent/invoke")
async def invoke_agent(req: AgentInvokeReq):
    """
    Agent 推理主入口。

    调用链路（优先级从高到低）：
      1. 转发 HTTP POST → 独立 Agent 服务（AGENT_BASE_URL，默认 localhost:8001）
      2. Agent 不可用 → 本地规则引擎降级响应

    SSE 响应格式（严格遵循 Java AgentInvokeResp DTO）：
      非末帧：{"chunk": "字", "is_end": false}
      末帧：  {"chunk": "...", "is_end": true,
                "reply": "...", "ui_action": {...},
                "action": "...", "urgency": "...",
                "vector": {"喜悦": 0.8, ...}}
    """
    print(f"[main.py] /internal/v1/agent/invoke | session={req.session_id}, "
          f"msg={req.user_message[:30]!r}, history={len(req.emotion_history)}条")

    # Step 1: 尝试从外部 Agent 服务获取结果（如果配置了独立 Agent）
    result = None
    if _AGENT_AVAILABLE:
        result = await _fetch_agent_via_http(req)
        if result is None:
            print(f"[main.py] Agent 服务不可用，切换到本地规则引擎")
        else:
            print(f"[main.py] Agent 服务返回成功: action={result.get('action')}")

    # Step 2: Agent 不可用时，使用本地规则引擎降级
    if result is None:
        result = _build_local_fallback(req)
        print(f"[main.py] 使用本地规则引擎降级: intensity={req.emotion_history[-1].get('intensity', 0.5) if req.emotion_history else 0.3}")

    reply = result.get("reply", "")
    ui_action = result.get("ui_instruction", {"color": "neutral", "pulse": "slow"})
    emotion_vector = result.get("vector", {})
    action = result.get("action", "subtle")
    urgency = result.get("urgency", "low")
    strategy = result.get("strategy")

    return StreamingResponse(
        _stream_reply(reply, ui_action, emotion_vector, action, urgency, strategy),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/internal/v1/session/update")
async def update_session(req: SessionUpdateReq):
    """切换感知引擎的 session_id"""
    print(f"[main.py] 收到会话切换请求: session={req.session_id}, user={req.user_id}")
    monitor_service.update_session_id(req.session_id)
    return {"code": 0, "message": "session updated", "session_id": req.session_id}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await handle_websocket(websocket)


@app.get("/")
async def index():
    return {
        "status": "online",
        "service": "wanqing-perception",
        "port": 8000,
        "agent_proxy": AGENT_BASE_URL,
    }


@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "ok", "service": "wanqing-perception"}


@app.get("/model_status")
async def model_status():
    """供 Agent 健康检查调用，返回情绪模型的加载状态"""
    engine = get_perception_engine()
    if engine is None:
        return {
            "model_loaded": False,
            "model_id": "none",
            "message": "感知引擎未初始化"
        }
    try:
        model_wrapper = getattr(engine, "_au_model", None)
        if model_wrapper is not None:
            initialized = getattr(model_wrapper, "_initialized", False)
            model = getattr(model_wrapper, "_model", None)
            return {
                "model_loaded": initialized and model is not None,
                "model_id": "trpakov/vit-face-expression",
                "message": "情绪模型已加载" if (initialized and model is not None) else "模型未加载，使用规则兜底"
            }
        return {"model_loaded": False, "model_id": "unknown", "message": "无法获取模型状态"}
    except Exception as e:
        return {"model_loaded": False, "model_id": "error", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
