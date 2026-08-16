from __future__ import annotations

"""
婉情AI 智能体 - FastAPI 服务主入口
====================================
启动 Agent 服务，监听来自 Java 业务层的请求。

接口（遵循 API_Contract.md 第四章）：
  POST /internal/v1/agent/invoke  — Java 请求 → Agent 决策 → SSE 流式响应

SSE 响应格式（符合前端 WebSocket 协议）：
  data: {"chunk": "我", "is_end": false}
  data: {"chunk": "...", "is_end": true, "ui_action": {...}, "reply": "...", "strategy": "..."}

环境变量：
    所有配置通过 .env 文件或系统环境变量提供（参见 config.py）
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import llm_config, redis_config, mysql_config
from src.agent.graph import get_graph
from src.agent.state import AgentState
from src.rag.retriever import sync_knowledge_base
from src.utils.logger import logger


# ==============================================================================
# FastAPI 应用
# ==============================================================================

app = FastAPI(title="Wanqing AI Agent", version="1.0.0")


# ==============================================================================
# 请求/响应模型
# ==============================================================================

class AgentInvokeRequest(BaseModel):
    """Java 业务层调用 Agent 的请求体"""
    session_id: str = Field(..., description="会话 ID")
    user_message: str = Field(default="", description="用户输入文本（可为空，主动关怀场景）")
    emotion_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="近期情感历史，每条含 timestamp/intensity/primary_emotion"
    )
    # 【新增】对话历史：由 Java 在调用前写入 Redis，Agent 读取后传入
    conversation_history: list[str] = Field(
        default_factory=list,
        description="对话历史 JSON 字符串列表，每条含 role 和 content"
    )
    user_id: str = Field(default="", description="用户 ID")
    task_phase: str = Field(default="unknown", description="任务阶段")
    # 用户拒绝惩罚系数：来自 Java 统计的历史接受/拒绝率
    # Python 用此系数调整 interrupt_cost = interrupt_cost * penalty
    # 范围 [0.5, 1.5]，越大越保守干预
    user_rejection_penalty: float = Field(default=1.0, description="用户拒绝惩罚系数")


class AgentInvokeResponse(BaseModel):
    """非流式响应格式（兼容无 SSE 能力的调用方）"""
    code: int = 200
    message: str = "success"
    data: dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# 配置检查
# ==============================================================================

def check_config() -> bool:
    """启动前检查必要配置项是否已设置"""
    errors = []

    if not llm_config.API_KEY:
        errors.append("DEEPSEEK_API_KEY 未配置")

    if errors:
        for err in errors:
            logger.error(f"配置缺失: {err}")
        return False

    logger.info("配置检查通过")
    logger.info(f"DeepSeek BaseURL: {llm_config.BASE_URL}")
    logger.info(f"Redis: {redis_config.HOST}:{redis_config.PORT}")
    logger.info(f"MySQL: {mysql_config.HOST}:{mysql_config.PORT}/{mysql_config.DATABASE}")
    return True


# ==============================================================================
# SSE 流式生成器
# ==============================================================================

async def _stream_reply(
    reply_text: str,
    ui_action: dict[str, str],
    emotion_vector: dict[str, float] | None = None,
    urgency: str = "low",
    action: str = "subtle",
    strategy: str | None = None,
    session_id: str = "",
    trace_id: str = "",
    intervention_score: float = 0.0,
) -> Any:
    """
    将完整 reply 按字切分，通过 SSE 流式推送给前端。

    Args:
        reply_text: 完整关怀回复文本
        ui_action:   {"color": "...", "pulse": "..."}
        emotion_vector: OCC 八维情感向量 dict，供前端 EmotionRadar 渲染
        urgency: 干预紧迫程度：low / medium / high
        action: 干预决策动作：silent / subtle / intervene（透传给 Java）
        strategy: 干预策略名称（如"5-4-3-2-1着陆技术"），透传给 Java
        session_id: 会话 ID，用于追踪
        trace_id: 本次调用唯一追踪 ID
        intervention_score: 干预紧迫度评分（0.0 ~ 1.0）
    """
    import time as _time
    emotion_vector = emotion_vector or {}
    _timestamp_ms = int(_time.time() * 1000)

    # 流式推送每个字
    for i, char in enumerate(reply_text):
        is_end = (i == len(reply_text) - 1)
        payload = {
            "chunk": char,
            "is_end": is_end,
        }
        if is_end:
            payload["ui_action"] = ui_action
            payload["reply"] = reply_text
            payload["vector"] = emotion_vector
            payload["urgency"] = urgency
            payload["action"] = action
            payload["intervention_score"] = intervention_score
            if strategy:
                payload["strategy"] = strategy
            # 【Plan1-A】补充统一字段
            payload["session_id"] = session_id
            payload["trace_id"] = trace_id
            payload["timestamp_ms"] = _timestamp_ms
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        # 【诊断】最后一个字发送时记录时间
        if is_end:
            logger.info(f"[SSE Stream] 完成发送，最终帧时间戳: {_time.time():.3f}")
        await asyncio.sleep(0.03)  # 约 30ms/字，控制播报速度

    # 立即发送 ui_only 帧（无 reply 时仍需推送 UI 指令）
    if not reply_text:
        payload = {
            "chunk": "",
            "is_end": True,
            "ui_action": ui_action,
            "reply": "",
            "vector": emotion_vector,
            "urgency": urgency,
            "action": action,
            "intervention_score": intervention_score,
        }
        if strategy:
            payload["strategy"] = strategy
        # 【Plan1-A】补充统一字段
        payload["session_id"] = session_id
        payload["trace_id"] = trace_id
        payload["timestamp_ms"] = _timestamp_ms
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ==============================================================================
# Agent 调用核心
# ==============================================================================

async def _run_agent_graph(request: AgentInvokeRequest) -> dict[str, Any]:
    """
    构造 AgentState 并调用 LangGraph，返回最终响应结构。

    Args:
        request: Java 请求体

    Returns:
        dict，包含 action, emotion, intensity, ui_instruction, reply, strategy
    """
    # 0. 执行系统健康检查（防止 LLM 捏造系统状态信息）
    from src.agent.tools.system_health import check_system_health
    health = await check_system_health(session_id=request.session_id)

    # 0.1 获取对话历史（优先级：Java传入 > Redis读取 > 空）
    # 对话历史存储在 Redis List 中，key = session:{session_id}:history
    # Java 在调用 Agent 前会先把用户消息写入 Redis 并通过 conversation_history 字段传入
    conversation_history_list = []

    # 优先使用 Java 传入的对话历史（已完成时间正序排列）
    if request.conversation_history:
        for json_str in request.conversation_history:
            try:
                import json as _json
                msg_data = _json.loads(json_str)
                conversation_history_list.append({
                    "role": msg_data.get("role", "user"),
                    "content": msg_data.get("content", "")
                })
            except Exception:
                pass
        logger.info(f"[AgentInvoke] 使用 Java 传入的对话历史: {len(request.conversation_history)} 条")
        # 【修复】Java 传入的历史已包含当前用户消息，不要重复追加

    # 如果 Java 没有传入，尝试从 Redis 读取
    elif not conversation_history_list:
        try:
            from src.memory.short_term import get_recent_history
            history_messages = await get_recent_history(request.session_id, limit=10)
            for msg in history_messages:
                conversation_history_list.append({
                    "role": msg.role,
                    "content": msg.content
                })
            logger.info(f"[AgentInvoke] 从 Redis 加载 {len(history_messages)} 条对话历史")
        except Exception as e:
            logger.warning(f"[AgentInvoke] 从 Redis 读取对话历史失败，使用空历史: {e}")

    # 【修复】使用自定义字段 conversation_history 而非 messages
    # 避免与 LangGraph MessagesState 的消息处理机制冲突

    # 1. 构造初始状态
    initial_state: dict[str, Any] = {
        "session_id": request.session_id,
        "user_id": request.user_id,
        "user_input": request.user_message,
        "task_phase": request.task_phase,
        "emotion_history": request.emotion_history,
        "user_rejection_penalty": request.user_rejection_penalty,
        # 【修复】使用 conversation_history 字段存储对话历史，避免与 LangGraph MessagesState 冲突
        "conversation_history": conversation_history_list,
        # 注入真实系统健康状态，供 Prompt 引用，防止 LLM 幻觉
        "system_health": health.to_dict(),
    }

    # 2. 调用 LangGraph（try-except 双重兜底：节点级降级 + 图级崩溃兜底）
    graph = get_graph()
    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"[AgentInvoke] LangGraph 图执行崩溃，降级为 subtle + 默认回复: {e}")
        return {
            "action": "subtle",
            "emotion": "中性",
            "intensity": 0.0,
            "ui_instruction": {"color": "neutral", "pulse": "slow"},
            "reply": "我在这里陪着你，有什么想说的吗？",
            "strategy": None,
            "urgency": "low",
            "intervention_score": 0.0,
        }

    # 3. 提取结果（final_response 由 return_result_node 封装）
    result = final_state.get("final_response", {})

    if not result:
        logger.warning("[AgentInvoke] LangGraph 返回结果为空，使用默认响应")
        result = {
            "action": "subtle",
            "emotion": "中性",
            "intensity": 0.0,
            "ui_instruction": {"color": "neutral", "pulse": "slow"},
            "reply": "我在这里陪着你，有什么想说的吗？",
            "strategy": None,
            "urgency": "low",
            "intervention_score": 0.0,
        }

    logger.info(
        f"[AgentInvoke] 执行完成 | session={request.session_id}, "
        f"action={result.get('action')}, emotion={result.get('emotion')}, "
        f"score={result.get('intervention_score', 0.0):.3f}"
    )

    # 注：TTS 已在 generate_reply_node 中触发（并行执行，减少延迟）

    return result


# ==============================================================================
# API 路由
# ==============================================================================

@app.post("/internal/v1/agent/invoke")
async def invoke_agent(request: AgentInvokeRequest):
    """
    Agent 决策主入口。

    Java 业务层通过此接口向 Agent 请求决策。
    当 suggested_action 为 SILENT 时，返回即时 UI 指令；
    当为 SUBTLE 或 INTERVENE 时，以 SSE 流式返回关怀回复。

    请求体（来自 Java）：
        {
          "session_id": "sess_123456",
          "user_message": "我今天真的好难受",
          "emotion_history": [...],
          "user_id": "user_001",
          "task_phase": "experiment_task"
        }

    SSE 响应格式：
        data: {"chunk": "我", "is_end": false}
        data: {"chunk": "在这里", "is_end": false, "ui_action": {...}, "reply": "...", "strategy": "..."}
    """
    # 【Plan1-A】生成 trace_id 用于全链路追踪
    import uuid as _uuid
    _trace_id = _uuid.uuid4().hex[:16]
    _session_id = request.session_id

    logger.info(
        f"[API] /internal/v1/agent/invoke | trace_id={_trace_id}, session={_session_id}, "
        f"user_message={request.user_message[:30]!r}, "
        f"emotion_history={len(request.emotion_history)}条"
    )

    # 1. 调用 LangGraph（等待完整结果）
    try:
        result = await _run_agent_graph(request)
    except Exception as e:
        logger.error(f"[API] Agent 执行异常 (trace_id={_trace_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {e}")

    action = result.get("action", "silent")
    reply = result.get("reply", "")
    ui_action = result.get("ui_instruction", {"color": "neutral", "pulse": "slow"})
    emotion_vector = result.get("vector", {})
    urgency = result.get("urgency", "low")
    strategy = result.get("strategy")  # 干预策略名称（可为 None）

    # 【Plan1-A】透传 trace_id 和 session_id 到 SSE 流
    stream_kwargs = {
        "session_id": _session_id,
        "trace_id": _trace_id,
        "intervention_score": result.get("intervention_score", 0.0),
    }

    # 2. 根据 action 决定响应方式
    if action in ("silent", "subtle") and not reply:
        # SILENT（无回复）或 SUBTLE 但未生成 reply → 仅推送 UI 指令
        return StreamingResponse(
            _stream_reply("", ui_action, emotion_vector, urgency, action, strategy, **stream_kwargs),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        # INTERVENE 或 SUBTLE（有 reply）→ SSE 流式返回回复文本
        return StreamingResponse(
            _stream_reply(reply, ui_action, emotion_vector, urgency, action, strategy, **stream_kwargs),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )


@app.post("/internal/v1/rag/upload")
async def rag_upload(file: UploadFile = File(...), category: str = Form("")):
    """
    接收 Java 后端转发的知识库文件，上传到 Python Agent 并触发 RAG 向量化重建。

    请求格式：multipart/form-data
        - file: 待上传的 Markdown/PDF 文件
        - category: 知识库分类标签（可空）

    处理流程：
        1. 保存文件到 knowledge_cards/ 目录
        2. 追加调用 sync_knowledge_base() 重建向量库
        3. 返回结果

    响应格式：
        {"file_name": "...", "chunks_inserted": N}
    """
    import os
    from pathlib import Path

    # 安全检查：仅接受 .md / .txt 文件
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in (".md", ".txt"):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，仅支持 .md 和 .txt")

    # 保存到 knowledge_cards 目录
    cards_dir = Path(__file__).parent / "knowledge_cards"
    cards_dir.mkdir(exist_ok=True)
    save_path = cards_dir / filename

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    logger.info(f"[RAG Upload] 文件已保存: {save_path}, 大小: {len(content)} bytes")

    # 追加向量化（同步新增卡片到 ChromaDB）
    chunks_count = 0
    try:
        from src.rag.knowledge_loader import load_all_knowledge_cards
        from src.rag.retriever import _get_rag_collection

        cards = load_all_knowledge_cards()
        collection = _get_rag_collection()

        # 获取当前已有数量，增量计算
        before_count = collection.count()
        sync_knowledge_base()
        after_count = collection.count()
        chunks_count = after_count - before_count
        if chunks_count < 0:
            chunks_count = after_count  # 全量重建

        logger.info(f"[RAG Upload] 向量化完成: 新增 {chunks_count} 个 chunk")
    except Exception as e:
        logger.error(f"[RAG Upload] 向量化失败: {e}")
        raise HTTPException(status_code=500, detail=f"RAG 向量化失败: {e}")

    return {
        "file_name": filename,
        "chunks_inserted": chunks_count,
        "category": category or "default"
    }


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "online", "service": "wanqing-agent"}


# ==============================================================================
# 启动 / 关闭事件
# ==============================================================================

@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    logger.info("=" * 60)
    logger.info("婉情AI 智能体启动中...")
    logger.info("=" * 60)

    if not check_config():
        logger.error("配置检查失败，Agent 将无法正常运行")
        return

    # 同步 RAG 知识库（首次启动时加载所有心理学卡片）
    try:
        logger.info("[Startup] 正在同步 RAG 知识库...")
        sync_knowledge_base()
        logger.info("[Startup] RAG 知识库同步完毕")
    except Exception as e:
        logger.warning(f"[Startup] RAG 知识库同步失败（知识检索将降级）: {e}")

    # 预热 LangGraph（提前编译图，避免首次请求延迟）
    try:
        logger.info("[Startup] 预热 LangGraph 状态机...")
        graph = get_graph()
        logger.info(f"[Startup] LangGraph 预热完成: {len(graph.nodes)} 个节点")
    except Exception as e:
        logger.warning(f"[Startup] LangGraph 预热失败: {e}")

    logger.info("婉情AI 智能体就绪，监听 /internal/v1/agent/invoke")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理"""
    logger.info("婉情AI 智能体关闭中...")


# ==============================================================================
# 直接运行（开发调试用）
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
