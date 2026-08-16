from __future__ import annotations

"""
婉情AI - LangGraph 图整合（完整版）
====================================
职责：
  1. 注册所有节点（感知采集、情感融合、干预决策、记忆管理、回复生成等）
  2. 定义节点间的边连接逻辑（含条件边路由）
  3. 编译生成可执行的 CompiledStateGraph
  4. 导出全局单例图实例，供 FastAPI 服务入口调用

架构说明（为什么不用 ToolNode）：
  本 Agent 是确定性管道（deterministic pipeline），而非 ReAct 自主决策 Agent。
  流程由图结构控制，不由 LLM 自主选择工具：
    collect_perception → fuse_emotion → decide_intervention
      → [route] → (retrieve_knowledge → generate_reply)
                  → log_session → return_result
  各节点直接调用外部服务（Redis / DeepSeek / ChromaDB / MySQL），
  等价于"节点内部封装了工具"，无需 ToolNode 的 LLM 路由开销。

节点注册（按执行顺序）：
  collect_perception    从 Redis 读取最新感知数据，写入 state.latest_perception
  fuse_emotion          融合感知数据 + Qwen 分析 + 历史情感，调用 LLM 输出 EmotionVector
  decide_intervention   综合强度/类型/打扰成本/趋势/置信度，输出 InterventionDecision
  retrieve_knowledge    基于情感类型和认知扭曲，检索 ChromaDB 心理学卡片
  generate_reply        结合情感向量 + 知识卡片，调用 LLM 生成关怀回复
  log_session           异步写入 MySQL 会话日志 + 触发短期记忆整理
  return_result         封装最终响应（所有路径汇聚点）

参考文档：
  - context-docs/01-emotion-recognition/1.1.md（感知数据采集）
  - context-docs/01-emotion-recognition/1.2.md（情感融合 + OCC 归因）
  - context-docs/02-intervention-decision/01.md（干预决策五因子）
  - context-docs/03-memory-system/01.md（记忆系统三层架构）
  - context-docs/03-memory-system/02.md（写入/检索/遗忘机制）
  - context-docs/04-rag-knowledge/01.md（RAG 知识库）
"""

import asyncio
from typing import Any

from langgraph.graph import END, StateGraph

from src.agent.state import AgentState
from src.agent.nodes.collect_perception import collect_perception_node
from src.agent.nodes.fuse_emotion import fuse_emotion_node
from src.agent.nodes.decide_intervention import decide_intervention_node
from src.agent.nodes.generate_reply import generate_reply_node
from src.rag.retriever import retrieve_knowledge_cards
from src.memory.short_term import append_conversation_turn
from src.memory.structured import export_session_log
from src.memory.callback import call_java_conversation_log
from src.memory.long_term import retrieve_relevant_memories, store_long_term_memory
from src.models.schemas import MemoryType
from src.utils.logger import logger


# ==============================================================================
# 辅助节点
# ==============================================================================

async def _async_store_emotion_vector(
    user_id: str,
    session_id: str,
    emotion,
    decision,
) -> None:
    """
    将 EmotionVector（含 history_context）异步写入 ChromaDB 个人长期记忆。

    文档要求（P1 优化点）：
      - history_context 应作为 emotion_vector 的一部分存入向量库
      - 这样未来检索个人记忆时，可以直接获取历史趋势信息
    """
    import time

    # 将 EmotionVector 序列化为自然语言文本，作为向量检索的文档内容
    history_ctx = emotion.history_context or {}

    trend_str = history_ctx.get("recent_trend", "未知")
    deviation = history_ctx.get("baseline_deviation", 0.0)
    baseline = history_ctx.get("baseline_mean", 0.0)

    content_lines = [
        f"[情感记录] 主要情绪: {emotion.primary_emotion.value}，强度: {emotion.intensity:.2f}",
        f"效价-唤醒度: valence={emotion.valence:.2f}, arousal={emotion.arousal:.2f}",
        f"历史趋势: {trend_str}，基线偏差: {deviation:+.3f}（基线均值: {baseline:.3f}）",
    ]

    # 认知扭曲
    if emotion.cognitive_distortions:
        distortions_str = "、".join(d.value for d in emotion.cognitive_distortions)
        content_lines.append(f"认知扭曲: {distortions_str}")

    # OCC 八维
    occ = emotion.evidence.get("occ", {}) if isinstance(emotion.evidence, dict) else {}
    if occ:
        occ_parts = [f"{k}:{v:.2f}" for k, v in occ.items() if v > 0.1]
        if occ_parts:
            content_lines.append(f"OCC归因: {', '.join(occ_parts)}")

    # 干预结果
    if decision:
        content_lines.append(f"干预决策: {decision.suggested_action.value}（分数={decision.intervention_score:.3f}）")
        if decision.reply:
            content_lines.append(f"AI回复摘要: {decision.reply[:50]}...")

    content = "\n".join(content_lines)

    try:
        await store_long_term_memory(
            user_id=user_id,
            content=content,
            memory_type=MemoryType.CONVERSATION_SUMMARY,
            metadata={
                "session_id": session_id,
                "primary_emotion": emotion.primary_emotion.value,
                "intensity": emotion.intensity,
                "trend": trend_str,
                "deviation": deviation,
            },
        )
        logger.debug(f"[log_session] EmotionVector 已存入 ChromaDB: emotion={emotion.primary_emotion.value}")
    except Exception as e:
        logger.warning(f"[log_session] ChromaDB 写入 EmotionVector 失败: {e}")

async def retrieve_knowledge_node(state: AgentState) -> dict[str, Any]:
    """
    RAG 检索节点：从心理学知识库 + ChromaDB 长期记忆双路检索。

    【优化 v2】根据干预强度动态调整检索参数：
      - SUBTLE（轻度干预）：检索 TOP-1 张卡片，轻量知识参考
      - INTERVENE（深度干预）：检索 TOP-3~5 张卡片，完整知识参考

    文档要求（03-memory-system/02.md）：
      "深度干预前必须先检索 ChromaDB 长期记忆，结果注入 Prompt"
    本节点执行双路检索：
      1. 心理学知识库（rag_config.RAG_COLLECTION）→ retrieved_knowledge_cards
      2. ChromaDB 个人长期记忆（chroma_config.LONG_TERM_COLLECTION）→ retrieved_memories

    数据流：
      输入 state  ←  emotion_vector, user_input, user_id, intervention_decision
      输出 state  →  retrieved_knowledge_cards: list[str],
                       retrieved_knowledge_cards_with_meta: list[dict]（★任务1新增）,
                       retrieved_memories: list[str]
    """
    session_id = state.get("session_id", "unknown")
    user_id = state.get("user_id", "")
    logger.info(f"[retrieve_knowledge] === 开始双路 RAG 检索: session={session_id} ===")

    emotion = state.get("current_emotion")
    user_input = state.get("user_input", "")
    decision = state.get("intervention_decision")

    if emotion is None:
        logger.warning("[retrieve_knowledge] 无情感数据，跳过 RAG 检索")
        return {
            "retrieved_knowledge_cards": [],
            "retrieved_knowledge_cards_with_meta": [],
            "retrieved_memories": [],
        }

    # 【优化 v2】根据干预强度决定检索深度
    is_subtle = (decision and decision.suggested_action.value == "subtle")
    top_k = 1 if is_subtle else 3  # SUBTLE 只检索 1 张，INTERVENE 检索 3 张

    logger.info(f"[retrieve_knowledge] 干预模式: {'SUBTLE' if is_subtle else 'INTERVENE'}，检索 TOP-{top_k} 张卡片")

    # 双路并发检索（心理学卡片 + 个人历史记忆）
    cards_task = retrieve_knowledge_cards(emotion, user_input, top_k=top_k)

    memories = []
    if user_id:
        # ChromaDB 个人长期记忆检索（文档 03-memory-system/02.md）
        memories = await retrieve_relevant_memories(
            user_id=user_id,
            query_text=f"用户情绪: {emotion.primary_emotion.value}，最近表达: {user_input}",
            k=3,
        )

    cards, cards_with_meta = await cards_task

    # 格式化长期记忆为可读文本
    formatted_memories = []
    for mem in memories:
        type_label = {
            "conversation_summary": "对话摘要",
            "session_insight": "会话洞察",
            "compressed_pattern": "长期模式"
        }.get(mem.type.value, "记忆")
        formatted_memories.append(
            f"【历史记忆 - {type_label}】{mem.content}（时间戳: {mem.timestamp}）"
        )

    logger.info(
        f"[retrieve_knowledge] 检索完成 | 心理学卡片: {len(cards)} 张, "
        f"个人长期记忆: {len(formatted_memories)} 条"
    )
    return {
        "retrieved_knowledge_cards": cards,
        "retrieved_knowledge_cards_with_meta": cards_with_meta,  # list[dict] 含 meta，供任务1提取 recommended_strategy
        "retrieved_long_term_memories": formatted_memories,
    }


async def log_session_node(state: AgentState) -> dict[str, Any]:
    """
    记忆写入节点：将本轮交互结果写入 MySQL 会话日志 + 触发短期记忆整理。

    触发时机（文档 03-memory-system/02.md）：
      - 每轮对话结束后写入 session_logs（由 Java 后端落库）
      - 将 EmotionVector（含 history_context）存入 ChromaDB 个人长期记忆
      - 追加对话到 Redis 短期记忆，达到阈值后触发异步摘要

    数据流：
      输入 state  ←  emotion_vector, intervention_decision, perception_snapshot
      输出 state  →  无 state 写入（异步操作，结果丢弃）
    """
    session_id = state.get("session_id", "unknown")
    user_id = state.get("user_id", "")
    logger.info(f"[log_session] === 写入会话日志: session={session_id} ===")

    emotion = state.get("current_emotion")
    decision = state.get("intervention_decision")
    user_input = state.get("user_input", "")

    # 1. 导出结构化会话日志，调用 Java 后端写入 MySQL session_logs
    # （架构约定：Python Agent 不直连 MySQL，由 Java 层负责落库）
    if emotion or decision:
        try:
            session_log = export_session_log(state)
            logger.debug(f"[log_session] 导出 session_log: {session_log.get('session_id')}")
            # 异步回调 Java（不阻塞主对话流程）
            asyncio.create_task(
                call_java_conversation_log(session_log)
            )
        except Exception as e:
            logger.warning(f"[log_session] 导出 session_log 失败: {e}")

    # 2. 将 EmotionVector（含 history_context）存入 ChromaDB 个人长期记忆
    #    文档要求：history_context 应随情感向量一起存入向量库
    if emotion and user_id:
        try:
            _store_emotion_memory_task = asyncio.create_task(
                _async_store_emotion_vector(
                    user_id=user_id,
                    session_id=session_id,
                    emotion=emotion,
                    decision=decision,
                )
            )
        except Exception as e:
            logger.warning(f"[log_session] ChromaDB 写入失败: {e}")

    # 3. 写入 Redis 短期记忆（追加对话历史）
    # 【修复】由于 Java 在调用 Agent 前已经写入了用户消息，
    # 这里只需要写入 AI 回复，避免用户消息重复
    try:
        # AI 回复追加（如果有）
        if decision and decision.reply:
            asyncio.create_task(
                append_conversation_turn(
                    session_id=session_id,
                    role="ai",
                    content=decision.reply,
                )
            )
    except Exception as e:
        logger.warning(f"[log_session] Redis 短期记忆写入失败: {e}")

    # 4. 触发短期记忆摘要检查（异步，不阻塞主流程）
    #    当 Redis 列表超过阈值（默认 20 条）时，触发摘要生成并存入向量库
    if user_id and session_id:
        try:
            from src.memory.short_term import check_and_summarize_history
            asyncio.create_task(
                check_and_summarize_history(session_id=session_id, user_id=user_id)
            )
        except Exception as e:
            logger.warning(f"[log_session] 摘要检查触发失败: {e}")

    logger.info(f"[log_session] 会话日志写入完毕")
    return {}


async def return_result_node(state: AgentState) -> dict[str, Any]:
    """
    结果封装节点：所有路径的汇聚点。
    将最终干预决策封装为统一格式，供 FastAPI SSE 流式响应使用。
    """
    decision = state.get("intervention_decision")
    emotion = state.get("current_emotion")
    user_input = state.get("user_input", "")

    if decision:
        try:
            logger.info(
                f"[return_result] 路径汇聚 | action={decision.suggested_action.value}, "
                f"score={decision.intervention_score:.3f}, reply={bool(getattr(decision, 'reply', ''))}"
            )
        except Exception:
            logger.info("[return_result] 路径汇聚 | action=?, score=?")
    else:
        logger.info("[return_result] 路径汇聚 | 无干预决策，使用默认响应")

    # 安全默认值兜底（确保婉晴永远能开口）
    default_reply = "你好呀！我在这里陪着你。有什么想聊的吗？"
    default_action = "subtle"
    default_emotion = "中性"
    default_intensity = 0.1

    # 构建 OCC 八维情感向量（带防护，防止 emotion 对象结构异常）
    emotion_vector = {}
    emotion_primary = default_emotion
    emotion_intensity = default_intensity

    try:
        occ = {}
        if emotion is not None:
            raw_evidence = getattr(emotion, "evidence", None)
            if isinstance(raw_evidence, dict):
                occ = raw_evidence.get("occ", {})
            elif isinstance(raw_evidence, str) and raw_evidence:
                import json as _json
                occ = _json.loads(raw_evidence).get("occ", {})

        occ_to_zh = {
            "joy": "喜悦", "sadness": "悲伤", "anger": "愤怒",
            "fear": "恐惧", "disgust": "厌恶", "surprise": "惊讶",
            "well_grounding": "踏实感", "anticipation": "期待",
        }
        emotion_vector = {occ_to_zh[k]: occ.get(k, 0.0) for k in occ_to_zh}

        if emotion is not None:
            primary_obj = getattr(emotion, "primary_emotion", None)
            emotion_primary = getattr(primary_obj, "value", default_emotion) if primary_obj else default_emotion
            emotion_intensity = getattr(emotion, "intensity", default_intensity)
    except Exception as e:
        logger.warning(f"[return_result] emotion 解析异常，使用默认值: {e}")

    # 确定最终 reply（永远不为空）
    decision_reply = ""
    if decision is not None:
        decision_reply = getattr(decision, "reply", "") or ""
    final_reply = decision_reply if decision_reply else default_reply

    # 确定最终 action（永远不为 silent，确保 SSE 有内容流式传输）
    raw_action = default_action
    if decision is not None:
        try:
            raw_action = getattr(decision.suggested_action, "value", default_action)
        except Exception:
            raw_action = default_action
    final_action = "subtle" if raw_action == "silent" else raw_action

    # UI 指令、urgency、score 兜底
    try:
        ui_color = getattr(decision.ui_instruction, "color", "neutral") if decision else "neutral"
        ui_pulse = getattr(decision.ui_instruction, "pulse", "slow") if decision else "slow"
    except Exception:
        ui_color, ui_pulse = "neutral", "slow"

    try:
        final_urgency = getattr(decision.urgency, "value", "low") if decision else "low"
    except Exception:
        final_urgency = "low"

    try:
        final_score = getattr(decision, "intervention_score", 0.0) if decision else 0.0
    except Exception:
        final_score = 0.0

    final_response = {
        "action": final_action,
        "emotion": emotion_primary,
        "intensity": emotion_intensity,
        "ui_instruction": {"color": ui_color, "pulse": ui_pulse},
        "reply": final_reply,
        "strategy": getattr(decision, "recommended_strategy", None) if decision else None,
        "urgency": final_urgency,
        "intervention_score": final_score,
        "vector": emotion_vector,
    }

    return {"final_response": final_response}


# ==============================================================================
# 条件路由函数
# ==============================================================================

def _intervention_router(state: AgentState) -> str:
    """
    条件边路由：根据干预决策的 suggested_action 确定下一步节点。

    路由规则（严格遵循文档 02-intervention-decision/01.md）：
      - "silent"   → log_session → return_result（静默观察，不打扰用户）
      - "subtle"   → generate_reply → log_session → return_result（微干预，生成轻量回复）
      - "intervene" → retrieve_knowledge → generate_reply → log_session → return_result
    """
    decision = state.get("intervention_decision")
    if decision is None:
        logger.warning("[router] 无干预决策，默认 silent 路径")
        return "silent"

    action = decision.suggested_action.value  # "silent" | "subtle" | "intervene"
    logger.debug(f"[router] 路由决策: {action}")
    return action


# ==============================================================================
# 图构建（延迟初始化 + 单例）
# ==============================================================================

_graph_instance: Any = None  # CompiledStateGraph


def get_graph() -> Any:
    """
    获取全局 LangGraph 编译图单例（延迟初始化）。
    """
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = _build_graph()
    return _graph_instance


def _build_graph() -> Any:
    """
    构建并编译 LangGraph 状态机。

    完整节点图：
      START
        │
        ▼
      collect_perception
        │
        ▼
      fuse_emotion
        │
        ▼
      decide_intervention
        │
        ├─[silent]─────→ log_session ──→ return_result ──→ END
        │
        ├─[subtle]──→ generate_reply ──→ log_session ──→ return_result ──→ END
        │
        └─[intervene]─→ retrieve_knowledge
                              │
                              ▼
                        generate_reply ──→ log_session ──→ return_result ──→ END
    """
    g = StateGraph(AgentState)

    # --- 注册所有节点（按执行顺序） ---
    g.add_node("collect_perception", collect_perception_node)
    g.add_node("fuse_emotion", fuse_emotion_node)
    g.add_node("decide_intervention", decide_intervention_node)
    g.add_node("retrieve_knowledge", retrieve_knowledge_node)
    g.add_node("generate_reply", generate_reply_node)
    g.add_node("log_session", log_session_node)
    g.add_node("return_result", return_result_node)

    # --- 设置入口点 ---
    g.set_entry_point("collect_perception")

    # --- 普通边（固定顺序） ---
    g.add_edge("collect_perception", "fuse_emotion")
    g.add_edge("fuse_emotion", "decide_intervention")

    # --- 条件边（核心路由） ---
    # decide_intervention 的输出决定下一步：
    #   silent   → log_session（跳过回复生成）
    #   subtle   → retrieve_knowledge → generate_reply（★优化：也进行轻量 RAG 检索）
    #   intervene → retrieve_knowledge → generate_reply（深度 RAG 检索）
    g.add_conditional_edges(
        "decide_intervention",
        _intervention_router,
        {
            "silent": "log_session",
            "subtle": "retrieve_knowledge",
            "intervene": "retrieve_knowledge",
        }
    )

    # subtle/intervene 路径：RAG 检索 → 回复生成 → 记录
    g.add_edge("retrieve_knowledge", "generate_reply")
    g.add_edge("generate_reply", "log_session")

    # --- 所有路径汇聚到 log_session（统一记录） ---
    # silent 直接到 log_session，subtle/intervene 经过 generate_reply 后到 log_session

    # --- 汇聚点 → 结束 ---
    g.add_edge("log_session", "return_result")
    g.add_edge("return_result", END)

    compiled = g.compile()

    node_names = [n for n in compiled.nodes.keys()]
    logger.info(
        f"[graph] LangGraph 状态机编译完成 | 节点数: {len(node_names)}, "
        f"节点列表: {' → '.join(node_names)}"
    )

    return compiled
