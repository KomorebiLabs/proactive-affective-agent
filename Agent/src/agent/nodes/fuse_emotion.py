from __future__ import annotations

"""
婉情AI - fuse_emotion LangGraph 节点
======================================
职责：情感识别数据流的核心节点，整合多模态感知数据，调用 DeepSeek 输出
      结构化的 EmotionVector，作为后续干预决策的输入。

执行流程：
  1. 从 state 读取最新感知数据（PerceptionData），并行从 Redis 拉取兜底数据
  2. 判断当前是走神/专注模式，决定是否需要完整 LLM 分析
  3. [专注模式] 组装多源数据为结构化自然语言 Prompt
  4. 调用 DeepSeek，_parse_llm_output 解析（含 JSON 清洗），输出 EmotionVector
  5. 计算多模态一致性，修正 LLM 置信度
  6. 更新 state.current_emotion，异步后台记录日志

架构说明：
  - Python 层不直连 MySQL（归 Java 微服务）
  - emotion_history 由 Java 调用 API 时在请求体传入，存入 AgentState
  - 所有耗时 I/O 步骤均为 async，并发操作使用 asyncio.gather

参考文档：
  - context-docs/01-emotion-recognition/1.1.md（走神/专注双模式）
  - context-docs/01-emotion-recognition/1.2.md（Prompt设计、冲突处理）
"""

import asyncio
import json
import re
import time
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from config import emotion_config, intervention_config
from src.agent.state import AgentState
from src.emotion.perception import (
    check_attention_trigger,
    compute_emotion_trend,
    get_emotion_trend_from_state,
    get_latest_perception,
)
from src.models.schemas import (
    CognitiveDistortion,
    EmotionLabel,
    EmotionTrend,
    EmotionVector,
    FuseEmotionLLMOutput,
    PerceptionData,
    QwenAnalysis,
)
from src.utils.logger import logger
from src.utils.llm_common import get_deepseek_client


# ==============================================================================
# Prompt 模板（严格按照文档1.2.md设计）
# ==============================================================================

_SYSTEM_PROMPT = """你是一个专业的心理学情感分析助手，负责综合多源证据判断用户的真实情感状态。

【情绪标签枚举——必须从此列表选取】
焦虑、沮丧、平静、开心、疲惫、愤怒、恐惧、厌恶、惊讶、中性

【认知扭曲枚举——若有，必须从此列表选取】
灾难化、读心术、非黑即白、过度概括、情绪推理、贴标签、个人化、应该陈述

【AU 参数判定表（供推理参考，不要机械套用）】
| 参数 | 典型阈值 | 情感提示 |
|-----|---------|---------|
| AU4（皱眉）| > 0.6 | 高强度负面情绪（愤怒/焦虑/恐惧）|
| AU12（嘴角上扬）| > 0.4 | 积极情绪；AU4也高时可能是苦笑 |
| AU15（嘴角下垂）| > 0.5 | 悲伤/沮丧的典型标志 |
| AU1+AU4 组合 | 同时激活 | 恐惧或悲伤 |
| 低头角度 | > 10° | 疲惫/沮丧/沉思（视其他线索而定）|
| 眨眼频率 | > 25次/分 | 紧张焦虑；< 10次/分可能专注或疲惫 |
| 音调 | > 250Hz | 高唤醒（兴奋/紧张）|
| 能量 | > 0.7 | 高arousal信号 |

【冲突处理规则】
- 客观 AU 参数与主观（Qwen-VL）分析冲突时，优先以多个客观参数的一致性为准
- 如果 AU 数据缺失或置信度 < 0.5，提高对主观分析的信任
- 无法确定时请降低 confidence 字段的值（< 0.5）并在 reasoning 中说明

【OCC 八维情感归因（必须输出）】
基于以下 OCC (Ortony-Clore-Collins) 情感归因模型，对用户情感进行八个维度的量化评估（0~1）：

| 维度 | 说明 | 高值提示 |
|------|------|---------|
| occ_joy | 喜悦 | 用户体验到愉悦、正向反馈、目标达成感 |
| occ_sadness | 悲伤 | 用户表达失落、无助、无望感 |
| occ_anger | 愤怒 | 用户表现出挫败、被冒犯、防御性语言 |
| occ_fear | 恐惧 | 用户表达担忧、不安全感、回避倾向 |
| occ_disgust | 厌恶 | 用户表现出排斥、嫌弃、反感 |
| occ_surprise | 惊讶 | 用户表现出意外、震惊、措手不及 |
| occ_well_grounding | 踏实感/安定感 | 用户感到平静、安全、被支持（高=安定，低=焦虑）|
| occ_anticipation | 期待感/焦虑倾向 | 用户对未来的预期（高=积极期待，低=消极焦虑）|

【系统状态声明】
以下【系统状态确认】中的信息是经过程序验证的真实状态，
请在回复中不要否认或质疑这些已确认的事实：
{system_health_facts}

{format_instructions}"""

_HUMAN_TEMPLATE = """【用户当前状态】

{analysis_input}

请基于以上多源证据，综合分析用户当前的真实情感状态。注意可能存在客观数据与主观分析不一致的情况，请进行推理和权衡，只输出要求格式的 JSON。"""


# ==============================================================================
# 工具函数：数据组装
# ==============================================================================








def assemble_analysis_input(
    perception: PerceptionData,
    qwen_analysis: QwenAnalysis | None,
    emotion_history: list[dict],
    session_id: str,
) -> str:
    """
    将多源数据组装为结构化自然语言描述，注入 Prompt。
    格式参考文档 1.2.md 的"整合后的输入 JSON"和"自然语言描述"章节。

    Returns:
        str：适合注入 Prompt 的自然语言描述文本
    """
    lines = []

    # --- 客观感知数据 ---
    au = perception.au
    lines.append("**面部动作单元（AU）**：")
    lines.append(f"  - AU4（皱眉）：{au.AU4:.2f}")
    lines.append(f"  - AU12（嘴角上扬）：{au.AU12:.2f}")
    lines.append(f"  - AU15（嘴角下垂）：{au.AU15:.2f}")
    lines.append(f"  - AU1（内眉上扬）：{au.AU1:.2f}")
    lines.append(f"  - AU5（瞪眼）：{au.AU5:.2f}")
    lines.append(f"  - AU 模型初判：{au.primary_emotion}（置信度={au.confidence:.2f}）")

    lines.append(f"\n**头部姿态**：俯仰角 {perception.head_pose.pitch:.1f}°，偏航角 {perception.head_pose.yaw:.1f}°")
    lines.append(f"**眨眼频率**：{perception.blink_rate:.1f} 次/分钟")
    lines.append(f"**专注度**：{perception.focus_level:.2f}")

    audio = perception.audio
    lines.append(f"\n**音频特征**：")
    lines.append(f"  - 音调：{audio.pitch:.1f} Hz")
    lines.append(f"  - 响度：{audio.loudness:.2f}")
    lines.append(f"  - 是否说话：{'是' if audio.speaking else '否'}")








    # --- 主观分析（Qwen-VL，可能为 None） ---
    if qwen_analysis and qwen_analysis.confidence > 0.3:
        lines.append(f"\n**多模态大模型（Qwen-VL）分析**：")
        lines.append(f"  - 判断情绪：{qwen_analysis.primary_emotion}（强度={qwen_analysis.emotion_intensity:.2f}，置信度={qwen_analysis.confidence:.2f}）")
        if qwen_analysis.facial_cues:
            lines.append(f"  - 面部线索：{', '.join(qwen_analysis.facial_cues)}")
        if qwen_analysis.scene_description:
            lines.append(f"  - 场景描述：{qwen_analysis.scene_description}")
    else:
        lines.append("\n**多模态大模型（Qwen-VL）分析**：未调用或置信度过低，请主要依赖客观证据。")

    # --- 历史情感轨迹 ---
    if emotion_history:
        lines.append(f"\n**近期情感历史**（共 {len(emotion_history)} 条）：")
        for h in emotion_history[-3:]:  # 只展示最近3条
            ts_str = str(h.get("timestamp", ""))[:10]
            lines.append(
                f"  - {ts_str}：{h.get('primary_emotion', '未知')}，强度={h.get('intensity', 0.0):.2f}"
            )
    else:
        lines.append("\n**近期情感历史**：暂无历史数据（首次分析或历史库未初始化）。")

    return "\n".join(lines)


# ==============================================================================
# LLM 输出清洗（修复2：处理 DeepSeek 输出 Markdown 代码块的问题）
# ==============================================================================

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_markdown_block(raw_text: str) -> str:
    """
    清洗 LLM 输出中的 Markdown 代码块标记。

    国内模型（DeepSeek/Qwen）常在 JSON 输出前后添加 ```json ... ``` 标记，
    导致 PydanticOutputParser 直接解析失败。此函数先提取纯 JSON 字符串。

    处理优先级：
      1. 匹配 ```json...``` 或 ```...``` 块，提取其内容
      2. 若无代码块，直接返回原始文本（可能已是纯 JSON）
    """
    match = _JSON_BLOCK_RE.search(raw_text)
    if match:
        cleaned = match.group(1).strip()
        logger.debug(f"[fuse_emotion] 清洗 Markdown 代码块，原长={len(raw_text)}，清洗后长={len(cleaned)}")
        return cleaned
    return raw_text.strip()


def _parse_llm_output(parser: PydanticOutputParser, raw_text: str) -> FuseEmotionLLMOutput:
    """
    带清洗的 LLM 输出解析。先清洗 Markdown 标记再解析，失败时抛出异常由调用方处理。
    """
    cleaned = _strip_markdown_block(raw_text)
    try:
        return parser.parse(cleaned)
    except (ValidationError, Exception) as e:
        # 尝试直接 JSON 解析后手动构建（二次兜底）
        logger.warning(f"[fuse_emotion] PydanticOutputParser 解析失败，尝试 json.loads 兜底: {e}")
        data = json.loads(cleaned)  # 若此处也失败，则抛出由上层处理
        return FuseEmotionLLMOutput.model_validate(data)


# ==============================================================================
# 置信度修正：多模态一致性
# ==============================================================================

def compute_multimodal_consistency(
    llm_emotion: str,
    au_emotion: str,
    qwen_emotion: str | None,
    au_confidence: float,
) -> float:




    """
    计算多模态一致性得分（0~1），用于修正 LLM 的自报置信度。

    一致性定义：LLM 输出情绪与 AU/Qwen 的情绪类别是否对齐
    （考虑到情绪是粗粒度类别，用"情绪极性一致"来近似）

    Returns:
        float [0, 1]，越高表示多模态越一致
    """






    
    # 情绪极性映射：正/中/负
    polarity_map = {
        "开心": "positive", "平静": "neutral",
        "中性": "neutral", "惊讶": "neutral",
        "焦虑": "negative", "沮丧": "negative", "疲惫": "negative",
        "愤怒": "negative", "恐惧": "negative", "厌恶": "negative",
        # AU模型输出（英文）
        "happy": "positive", "neutral": "neutral", "surprise": "neutral",
        "sad": "negative", "angry": "negative", "fear": "negative", "disgust": "negative",
    }

    llm_polarity = polarity_map.get(llm_emotion, "neutral")
    au_polarity = polarity_map.get(au_emotion, "neutral")
    qwen_polarity = polarity_map.get(qwen_emotion or "", "neutral")

    scores = []

    # AU 一致性（加权 au_confidence）
    if au_confidence > 0.4:
        au_consistent = 1.0 if llm_polarity == au_polarity else 0.2
        scores.append(au_consistent * au_confidence)

    # Qwen 一致性
    if qwen_emotion:
        qwen_consistent = 1.0 if llm_polarity == qwen_polarity else 0.3
        scores.append(qwen_consistent)

    if not scores:
        return 0.5  # 无可用对比，返回中性一致性

    return sum(scores) / len(scores)


# ==============================================================================
# 主节点函数
# ==============================================================================

async def fuse_emotion_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph fuse_emotion 节点：情感融合分析。

    Args:
        state: 当前 AgentState（包含 latest_perception, qwen_analysis 等）

    Returns:
        dict，包含以下更新字段：
          - current_emotion: EmotionVector（本次融合结果）
          - is_focused_mode: bool（更新后的模式状态）
          - emotion_history: list（从记忆库更新的历史）
    """
    session_id = state.get("session_id", "unknown")
    logger.info(f"[fuse_emotion] === 开始情感融合分析: session={session_id} ===")

    # ------------------------------------------------------------------
    # Step 1：获取感知数据
    # ------------------------------------------------------------------
    perception = state.get("latest_perception")
    if perception is None:
        # 尝试从 Redis 实时读取
        perception = await get_latest_perception(session_id)

    if perception is None:
        logger.warning(f"[fuse_emotion] 无感知数据，返回中性默认情绪")
        return {"current_emotion": _default_neutral_emotion(session_id)}

    # ------------------------------------------------------------------
    # Step 2：走神/专注模式判断
    # 【注意】专注模式判断已移至 collect_perception_node（统一入口）
    # collect_perception_node 负责：
    #   - 调用 check_attention_trigger
    #   - 调用 Qwen-VL（仅专注模式）
    #   - 将结果写入 state["is_focused_mode"] 和 state["qwen_analysis"]
    # 本节点直接读取 state，避免重复判断
    # ------------------------------------------------------------------
    is_focused = state.get("is_focused_mode", False)

    # 兼容兜底：如果 state 中没有 is_focused_mode（首次调用），使用规则判断
    if is_focused is None:
        triggered, trigger_reason = check_attention_trigger(perception)
        is_focused = triggered
        if is_focused:
            logger.info(f"[fuse_emotion] 兜底判断触发专注模式: {trigger_reason}")

    if is_focused:
        logger.info(f"[fuse_emotion] 进入专注模式，使用完整 DeepSeek 分析流程")

    # ------------------------------------------------------------------
    # Step 3：走神模式 → 快速规则判断，不调用 LLM
    # ------------------------------------------------------------------
    if not is_focused:
        emotion_vector = _quick_rule_emotion(perception, session_id)
        logger.info(f"[fuse_emotion] 走神模式快速判断: {emotion_vector.primary_emotion.value}")
        return {
            "current_emotion": emotion_vector,
            "is_focused_mode": False,
        }

    # ------------------------------------------------------------------
    # Step 4：专注模式 → 完整 DeepSeek 分析流程
    # ------------------------------------------------------------------

    # 4a. emotion_history 由 Java API 传入，已在 AgentState 中就绪，直接读取（无 I/O）
    #    当前预留 asyncio.gather 结构，以便未来扩展（如同时查 Redis 摘要缓存）
    async def _get_history_from_state() -> list:
        return state.get("emotion_history", [])

    emotion_history, _ = await asyncio.gather(
        _get_history_from_state(),
        asyncio.sleep(0),  # 占位槽，保留并发扩展点
    )

    # 4b. 组装分析输入文本
    qwen_analysis = state.get("qwen_analysis")
    analysis_input = assemble_analysis_input(
        perception=perception,
        qwen_analysis=qwen_analysis,
        emotion_history=emotion_history,
        session_id=session_id,
    )

    # 4c. 构建 Prompt & 调用 DeepSeek（注入系统健康状态，防止 LLM 幻觉）
    parser = PydanticOutputParser(pydantic_object=FuseEmotionLLMOutput)
    prompt_text = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("human", _HUMAN_TEMPLATE),
    ])

    # 获取系统健康状态（已在 main.py 的 check_system_health 中验证）
    system_health: dict = state.get("system_health", {})
    from src.agent.tools.system_health import SystemHealthStatus
    health_obj = SystemHealthStatus(
        java_backend_online=system_health.get("java_backend_online", False),
        perception_service_online=system_health.get("perception_service_online", False),
        redis_connected=system_health.get("redis_connected", False),
        emotion_model_loaded=system_health.get("emotion_model_loaded", False),
        has_realtime_perception=system_health.get("has_realtime_perception", False),
    )
    system_health_facts = health_obj.to_fact_string()

    logger.info(f"[fuse_emotion] 调用 DeepSeek 进行情感融合分析...")
    try:
        client = get_deepseek_client()
        # 直接调用（不使用链式 | 操作符），以便在 parse 前插入清洗步骤
        messages = await prompt_text.aformat_messages(
            format_instructions=parser.get_format_instructions(),
            analysis_input=analysis_input,
            system_health_facts=system_health_facts,
        )
        response = await client.ainvoke(messages)
        raw_text = response.content
        llm_output: FuseEmotionLLMOutput = _parse_llm_output(parser, raw_text)

        ea = llm_output.emotion_assessment  # EmotionAssessmentLLM

        # 4d. 多模态一致性修正置信度
        qwen_emotion = qwen_analysis.primary_emotion if qwen_analysis else None
        consistency = compute_multimodal_consistency(
            llm_emotion=ea.primary_emotion,
            au_emotion=perception.au.primary_emotion,
            qwen_emotion=qwen_emotion,
            au_confidence=perception.au.confidence,
        )
        alpha = intervention_config.LLM_CONFIDENCE_ALPHA  # 0.6
        final_confidence = alpha * ea.confidence + (1 - alpha) * consistency

        logger.info(
            f"[fuse_emotion] LLM: {ea.primary_emotion}(强度={ea.intensity:.2f}), "
            f"llm_conf={ea.confidence:.2f}, consistency={consistency:.2f}, "
            f"final_conf={final_confidence:.2f}"
        )

        # 4e. 计算历史上下文（trend + baseline_deviation）
        history_context = _build_history_context(emotion_history, ea.intensity)

        # 4f. 映射为 EmotionVector
        emotion_vector = _map_to_emotion_vector(
            ea=ea,
            session_id=session_id,
            perception=perception,
            final_confidence=final_confidence,
            history_context=history_context,
        )

    except Exception as e:
        logger.error(f"[fuse_emotion] DeepSeek 调用失败: {e}")
        # 降级：使用 AU 快速规则
        emotion_vector = _quick_rule_emotion(perception, session_id)
        emotion_vector.confidence = 0.3  # 降低置信度标记为降级结果
        is_focused = False  # 重置模式

    # ------------------------------------------------------------------
    # Step 5：（异步）写入日志（后续记忆模块接入后取消占位）
    # ------------------------------------------------------------------
    asyncio.create_task(
        _async_log_emotion(session_id, perception, emotion_vector)
    )

    return {
        "current_emotion": emotion_vector,
        "is_focused_mode": is_focused,
        "emotion_history": emotion_history,
    }


# ==============================================================================
# 内部辅助函数
# ==============================================================================

def _build_history_context(
    emotion_history: list[dict[str, Any]],
    current_intensity: float,
) -> dict[str, Any]:
    """
    基于情感历史计算 history_context 填充 EmotionVector.history_context。

    包含字段（文档 01-emotion-recognition/1.2.md）：
      - recent_trend：情感强度趋势（上升/下降/平稳）
      - baseline_deviation：当前强度与历史基线的偏差量
      - history_length：用于趋势计算的记录条数
    """
    if not emotion_history:
        return {"recent_trend": "stable", "baseline_deviation": 0.0, "history_length": 0}

    trend = get_emotion_trend_from_state(emotion_history)

    # 计算历史基线：使用最近 N 条强度的均值
    recent = emotion_history[-5:]
    intensities = [h.get("intensity", 0.0) for h in recent]
    baseline = sum(intensities) / len(intensities)

    # 偏差量：当前强度 - 历史基线（正=高于平常，负=低于平常）
    deviation = current_intensity - baseline

    return {
        "recent_trend": trend.value,
        "baseline_deviation": round(deviation, 3),
        "history_length": len(emotion_history),
        "baseline_mean": round(baseline, 3),
    }


def _map_to_emotion_vector(
    ea,  # EmotionAssessmentLLM
    session_id: str,
    perception: PerceptionData,
    final_confidence: float,
    history_context: dict[str, Any] | None = None,
) -> EmotionVector:
    """将 LLM 输出的 EmotionAssessmentLLM 映射为标准 EmotionVector"""

    # 情绪标签验证（不在枚举中则使用中性）
    try:
        primary = EmotionLabel(ea.primary_emotion)
    except ValueError:
        logger.warning(f"[fuse_emotion] LLM 输出未知情绪标签: '{ea.primary_emotion}'，使用中性")
        primary = EmotionLabel.NEUTRAL

    secondary = None
    if ea.secondary_emotion:
        try:
            secondary = EmotionLabel(ea.secondary_emotion)
        except ValueError:
            secondary = None

    # 认知扭曲标签验证
    distortions = []
    for d in ea.cognitive_distortions:
        try:
            distortions.append(CognitiveDistortion(d))
        except ValueError:
            logger.warning(f"[fuse_emotion] 未知认知扭曲标签: '{d}'，忽略")

    return EmotionVector(
        timestamp=int(time.time() * 1000),
        session_id=session_id,
        primary_emotion=primary,
        secondary_emotion=secondary,
        intensity=ea.intensity,
        valence=ea.valence,
        arousal=ea.arousal,
        dominance=ea.dominance,
        cognitive_distortions=distortions,
        confidence=final_confidence,
        reasoning=ea.reasoning,
        evidence={
            # 客观 AU 证据
            "au": {
                "AU4": perception.au.AU4,
                "AU12": perception.au.AU12,
                "AU15": perception.au.AU15,
                "AU1": perception.au.AU1,
            },
            "au_model": perception.au.primary_emotion,
            # OCC 八维归因（文档 01-emotion-recognition/1.2.md）
            "occ": {
                "joy": ea.occ_joy,
                "sadness": ea.occ_sadness,
                "anger": ea.occ_anger,
                "fear": ea.occ_fear,
                "disgust": ea.occ_disgust,
                "surprise": ea.occ_surprise,
                "well_grounding": ea.occ_well_grounding,
                "anticipation": ea.occ_anticipation,
            },
        },
        history_context=history_context or {},
    )


def _quick_rule_emotion(perception: PerceptionData, session_id: str) -> EmotionVector:
    """
    走神模式 / 降级模式下的快速规则判断。
    不调用 LLM，仅基于 AU 阈值做简单推断。
    置信度固定低（0.4），表示不可靠，仅供参考。
    """
    au = perception.au
    # 简单规则：优先使用 AU 模型的初判（已由感知微服务计算）
    au_to_zh = {
        "sad": EmotionLabel.DEPRESSION,
        "angry": EmotionLabel.ANGER,
        "fear": EmotionLabel.FEAR,
        "disgust": EmotionLabel.DISGUST,
        "happy": EmotionLabel.HAPPY,
        "surprise": EmotionLabel.SURPRISE,
        "neutral": EmotionLabel.NEUTRAL,
    }
    primary = au_to_zh.get(au.primary_emotion.lower(), EmotionLabel.NEUTRAL)

    # 如果 AU 模型本身置信度不足，使用阈值规则兜底
    if au.confidence < 0.5:
        if au.AU4 > 0.7 and au.AU15 > 0.5:
            primary = EmotionLabel.DEPRESSION
        elif au.AU4 > 0.7:
            primary = EmotionLabel.ANXIETY
        elif au.AU12 > 0.4:
            primary = EmotionLabel.HAPPY
        else:
            primary = EmotionLabel.NEUTRAL

    return EmotionVector(
        timestamp=int(time.time() * 1000),
        session_id=session_id,
        primary_emotion=primary,
        intensity=min(1.0, (au.AU4 + au.AU15) / 2 + 0.1),
        confidence=0.4,  # 走神模式置信度固定低
        reasoning="[走神模式] 基于AU阈值规则快速判断，未使用LLM推理",
        evidence={"au_model": au.primary_emotion, "au_confidence": au.confidence},
    )


def _default_neutral_emotion(session_id: str) -> EmotionVector:
    """无感知数据时的默认中性情绪（兜底）"""
    return EmotionVector(
        timestamp=int(time.time() * 1000),
        session_id=session_id,
        primary_emotion=EmotionLabel.NEUTRAL,
        intensity=0.1,
        confidence=0.1,
        reasoning="[兜底] 无感知数据，默认中性",
    )


async def _async_log_emotion(
    session_id: str,
    perception: PerceptionData,
    emotion_vector: EmotionVector,
) -> None:
    """
    异步记录情感日志（非阻塞，不影响主流程）。
    当前为占位实现，后续记忆模块完成后替换为真实的 MySQL / Chroma 写入。
    """
    logger.debug(
        f"[fuse_emotion][LOG] session={session_id}, "
        f"emotion={emotion_vector.primary_emotion.value}, "
        f"intensity={emotion_vector.intensity:.2f}, "
        f"confidence={emotion_vector.confidence:.2f}"
    )
    # TODO: 接入 src/memory/structured.py 的 log_interaction()
    # TODO: 接入 src/memory/short_term.py 的情感时序写入
