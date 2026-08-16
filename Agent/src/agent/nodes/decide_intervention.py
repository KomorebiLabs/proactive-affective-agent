"""
婉情AI - decide_intervention LangGraph 节点
===========================================
职责：基于融合后的多模态情感向量和当前环境上下文，进行主动关怀干预决策。

执行流程：
  1. 通过规则层过滤极不合适的打扰情况（极高专注度、低情绪强度）。
  2. 计算五大因子的量化分数并加权：
     score = W1*强度 + W2*情感优先级 - W3*打扰成本 + W4*趋势 + W5*置信度
  3. 执行冷却期逻辑校验（Redis 持久化，支持跨 API 调用）。
  4. 根据阈值划分为 SILENT、SUBTLE、INTERVENE 三个动作分级，并附带控制 UI 状态的指令。
"""

import time
from typing import Any

from config import emotion_config, intervention_config
from src.agent.state import AgentState
from src.emotion.perception import get_emotion_trend_from_state
from src.models.schemas import (
    EmotionTrend,
    InterventionAction,
    InterventionDecision,
    InterventionUrgency,
    UIInstruction,
)
from src.utils.logger import logger
from src.utils.redis_client import get_redis


# Redis Key 模板（与 config.py 中 redis_config 保持一致）
_COOLDOWN_KEY_TPL = "cooldown:agent:{session_id}"
_COOLDOWN_TTL_SECONDS = 300  # 冷却状态 Redis TTL = 5分钟（长于 COOLDOWN_BASE_SECONDS=120）


async def decide_intervention_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph干预决策节点

    Args:
        state: 当前Agent状态，必须包含 current_emotion 和 latest_perception

    Returns:
        dict: 更新的 state 字段，包括 intervention_decision，以及如果发生干预则更新 last_intervention_time

    降级策略：任何节点内未捕获的异常均降级为 SILENT（最高优先级静默观察），
              避免因单节点故障导致整个 Agent 崩溃。

decide_intervention_node 是 LangGraph 决策引擎中的干预决策节点，
它基于前序节点融合出的情感向量（current_emotion）和当前环境上下文（专注度、打扰成本等），
计算一个综合干预分数，然后决定采取何种干预动作（静默、轻微暗示、主动干预），
并生成相应的 UI 控制指令（如呼吸光晕的颜色和频率）。

这个节点的设计体现了婉晴AI的核心理念：
在合适的时间、以合适的强度、用合适的方式介入，避免成为打扰，而是在用户真正需要时提供支持。



    """
    session_id = state.get("session_id", "unknown")
    logger.info(f"[decide_intervention] === 开始干预决策: session={session_id} ===")

    try:
        return await _decide_intervention_impl(state)
    except Exception as e:
        logger.error(f"[decide_intervention] 节点执行异常，降级为 SILENT: {e}")
        return {"intervention_decision": _create_silent_decision()}


async def _decide_intervention_impl(state: AgentState) -> dict[str, Any]:
    """decide_intervention 的核心逻辑（由节点函数 try-except 包裹实现降级）"""

    current_emotion = state.get("current_emotion")
    if current_emotion is None:
        logger.warning("[decide_intervention] 缺失 current_emotion 数据，默认 SILENT。")
        return {"intervention_decision": _create_silent_decision()}

    perception = state.get("latest_perception")
    session_id = state.get("session_id", "unknown")
    cooldown_key = _COOLDOWN_KEY_TPL.format(session_id=session_id)

    # =============================================================================
    # 【优先级最高】用户主动发消息 → 跳过所有规则拦截，直接触发对话
    # =============================================================================
    # 只要用户发送了任何文字，就无条件让婉晴回复。
    # 理由：用户主动开口是对话系统最基本的需求，感知关怀的打扰成本/冷却期等
    # 规则仅适用于婉晴自发发起的关怀，不应拦截用户主动发起的对话。
    user_input = state.get("user_input", "")
    is_user_initiated = bool(user_input and user_input.strip())
    if is_user_initiated:
        logger.info(
            f"[decide_intervention] ★ 用户主动发消息（{user_input[:30]!r}），"
            f"跳过打扰成本/冷却期/最低强度规则，直接进入对话模式。"
        )

    # =============================================================================
    # 计算打扰成本 (Interrupt Cost)
    # =============================================================================
    if perception:
        focus_level = perception.focus_level
    else:
        focus_level = 0.5  # 缺失感知数据时默认中性专注

    arousal = current_emotion.arousal
    interrupt_cost = focus_level * (1.0 - arousal)

    # 用户拒绝惩罚系数（来自 Java 统计的历史接受/拒绝率）
    # 系数范围 [0.5, 1.5]：用户越拒绝干预，系统越保守
    penalty = state.get("user_rejection_penalty", 1.0)
    if penalty != 1.0:
        logger.info(f"[decide_intervention] 应用用户拒绝惩罚系数: penalty={penalty:.2f}")
        interrupt_cost = interrupt_cost * penalty

    # 提取情绪优先级
    primary_emotion_str = current_emotion.primary_emotion.value
    emotion_priority = emotion_config.EMOTION_PRIORITY.get(primary_emotion_str, 0.0)

    # 提取历史趋势
    emotion_history = state.get("emotion_history", [])
    trend = get_emotion_trend_from_state(emotion_history)
    trend_factor = _get_trend_factor(trend)

    # 计算综合干预分数（即使 is_user_initiated 也计算，用于日志和调试）
    cfg = intervention_config
    intensity = current_emotion.intensity
    confidence = current_emotion.confidence

    score = (
        cfg.WEIGHT_INTENSITY * intensity
        + cfg.WEIGHT_EMOTION_PRIORITY * emotion_priority
        - cfg.WEIGHT_INTERRUPT_COST * interrupt_cost
        + cfg.WEIGHT_TREND * trend_factor
        + cfg.WEIGHT_CONFIDENCE * confidence
    )
    logger.debug(
        f"[decide_intervention] 核心指标 -> intensity={intensity:.2f}, priority={emotion_priority:.2f}, "
        f"interrupt_cost={interrupt_cost:.2f}, trend={trend_factor:.2f}, confidence={confidence:.2f}"
    )
    logger.info(f"[decide_intervention] 计算干预分数: {score:.3f} | 用户主动: {is_user_initiated}")

    # =============================================================================
    # 规则拦截层（仅对婉晴自发发起的关怀生效，不拦截用户主动对话）
    # =============================================================================
    is_emergency = (intensity >= cfg.EMERGENCY_INTENSITY_THRESHOLD and emotion_priority >= 0.8)

    if not is_emergency and not is_user_initiated:
        # A. 情绪强度过低 → SILENT（但用户主动说话时跳过）
        if intensity < cfg.MIN_INTENSITY_FOR_INTERVENTION:
            logger.info(f"[decide_intervention] 情绪强度 ({intensity:.2f}) < 最低干预线 -> SILENT")
            return {"intervention_decision": _create_silent_decision(score=score, cost=interrupt_cost, trend=trend)}

        # B. 打扰成本过高 → SILENT（但用户主动说话时跳过）
        if interrupt_cost > cfg.HIGH_INTERRUPT_COST:
            logger.info(f"[decide_intervention] 打扰成本 ({interrupt_cost:.2f}) > 阈值 -> SILENT")
            return {"intervention_decision": _create_silent_decision(score=score, cost=interrupt_cost, trend=trend)}

        # C. 冷却期检查 → SILENT（但用户主动说话时跳过）
        # Q7: 先查 Redis（跨请求持久化），无则降级用 state 中的值（进程内存兜底）
        current_time_ms = int(time.time() * 1000)
        redis = await get_redis()
        redis_last_ts = await redis.get(cooldown_key)
        if redis_last_ts is not None:
            last_intervention_time = int(redis_last_ts)
        else:
            last_intervention_time = state.get("last_intervention_time", 0)
        time_since_last_sec = (current_time_ms - last_intervention_time) / 1000.0
        if time_since_last_sec < cfg.COOLDOWN_BASE_SECONDS:
            logger.info(f"[decide_intervention] 冷却期内 ({time_since_last_sec:.1f}s < {cfg.COOLDOWN_BASE_SECONDS}s) -> SILENT")
            return {"intervention_decision": _create_silent_decision(score=score, cost=interrupt_cost, trend=trend)}
    elif is_emergency:
        logger.warning("[decide_intervention] 🚨 检测到高强度情绪危急状态！跳过所有规则限制。")

    # =============================================================================
    # 阈值决策层
    # 用户主动发消息：
    #   - intensity >= HIGH_INTENSITY_THRESHOLD_FOR_USER_INITIATED → INTERVENE（深度 RAG 干预）
    #   - intensity < HIGH_INTENSITY_THRESHOLD_FOR_USER_INITIATED → SUBTLE（轻量回复，跳过 RAG）
    # =============================================================================
    if is_user_initiated:
        if current_emotion.intensity >= cfg.HIGH_INTENSITY_THRESHOLD_FOR_USER_INITIATED:
            action = InterventionAction.INTERVENE
            urgency = InterventionUrgency.MEDIUM
            logger.info(
                f"[decide_intervention] ★ 用户主动倾诉 + 高情绪强度 "
                f"(intensity={current_emotion.intensity:.2f} >= {cfg.HIGH_INTENSITY_THRESHOLD_FOR_USER_INITIATED}) "
                f"→ INTERVENE（启用 RAG 深度干预）"
            )
        else:
            action = InterventionAction.SUBTLE
            urgency = InterventionUrgency.LOW
            logger.info(
                f"[decide_intervention] ★ 用户主动对话 → SUBTLE "
                f"(intensity={current_emotion.intensity:.2f} < {cfg.HIGH_INTENSITY_THRESHOLD_FOR_USER_INITIATED})"
            )
    elif score >= cfg.INTERVENE_THRESHOLD or is_emergency:
        action = InterventionAction.INTERVENE
        urgency = InterventionUrgency.HIGH if is_emergency else InterventionUrgency.MEDIUM
    elif score >= cfg.SUBTLE_THRESHOLD:
        action = InterventionAction.SUBTLE
        urgency = InterventionUrgency.LOW
    else:
        action = InterventionAction.SILENT
        urgency = InterventionUrgency.LOW

    logger.info(f"[decide_intervention] 最终决策: {action.value}, urgency={urgency.value}")

    # =============================================================================
    # UI 指令与状态封装
    # =============================================================================
    ui_cmd = _get_ui_instruction(action, current_emotion.primary_emotion.name.lower())

    decision = InterventionDecision(
        needed=(action != InterventionAction.SILENT),
        urgency=urgency,
        suggested_action=action,
        ui_instruction=ui_cmd,
        recommended_strategy=None,
        reply="",
        intervention_score=score,
        interrupt_cost=interrupt_cost,
        trend=trend
    )

    result_state = {"intervention_decision": decision}
    if decision.needed:
        new_ts = int(time.time() * 1000)
        result_state["last_intervention_time"] = new_ts
        # Q7: 同步写入 Redis，TTL=300s（5分钟），支持跨请求持久化
        try:
            redis = await get_redis()
            await redis.set(cooldown_key, str(new_ts), ex=_COOLDOWN_TTL_SECONDS)
        except Exception as redis_err:
            logger.warning(f"[decide_intervention] Redis 写入冷却时间失败，降级为进程内存: {redis_err}")

    return result_state


# ==============================================================================
# 辅助函数
# ==============================================================================

def _get_trend_factor(trend: EmotionTrend) -> float:
    if trend == EmotionTrend.RISING:
        return intervention_config.TREND_RISING_FACTOR
    elif trend == EmotionTrend.FALLING:
        return intervention_config.TREND_FALLING_FACTOR
    else:
        return intervention_config.TREND_STABLE_FACTOR


def _create_silent_decision(score: float = 0.0, cost: float = 0.0, trend: EmotionTrend = EmotionTrend.STABLE) -> InterventionDecision:
    return InterventionDecision(
        needed=False,
        urgency=InterventionUrgency.LOW,
        suggested_action=InterventionAction.SILENT,
        ui_instruction=UIInstruction(
            **intervention_config.UI_INSTRUCTION_MAP["silent"]
        ),
        intervention_score=score,
        interrupt_cost=cost,
        trend=trend
    )


def _get_ui_instruction(action: InterventionAction, emotion_eng_key: str) -> UIInstruction:
    """根据动作和情绪分配不同的UI动画效果"""
    if action == InterventionAction.SILENT:
        cmd_dict = intervention_config.UI_INSTRUCTION_MAP["silent"]
    elif action == InterventionAction.SUBTLE:
        cmd_dict = intervention_config.UI_INSTRUCTION_MAP["subtle"]
    else:
        # INTERVENE 模式根据情绪区分 UI
        map_key = f"intervene_{emotion_eng_key}"
        if map_key in intervention_config.UI_INSTRUCTION_MAP:
            cmd_dict = intervention_config.UI_INSTRUCTION_MAP[map_key]
        else:
            cmd_dict = intervention_config.UI_INSTRUCTION_MAP["intervene_default"]
            
    return UIInstruction(**cmd_dict)
