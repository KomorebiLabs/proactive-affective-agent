from __future__ import annotations

"""
婉情AI - 核心数据模型（Pydantic Schemas）
==========================================
定义系统中所有模块共享的数据结构。
所有 LLM 输出均通过 PydanticOutputParser 解析为这些模型。
"""

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ==============================================================================
# 基础枚举
# ==============================================================================

class EmotionLabel(str, Enum):
    """10类情绪标签枚举（需与前端情绪映射表一致）"""
    ANXIETY = "焦虑"
    DEPRESSION = "沮丧"
    CALM = "平静"
    HAPPY = "开心"
    FATIGUE = "疲惫"
    ANGER = "愤怒"
    FEAR = "恐惧"
    DISGUST = "厌恶"
    SURPRISE = "惊讶"
    NEUTRAL = "中性"


class CognitiveDistortion(str, Enum):
    """认知扭曲类型枚举（CBT标准）"""
    CATASTROPHIZING = "灾难化"
    MIND_READING = "读心术"
    BLACK_WHITE = "非黑即白"
    OVERGENERALIZATION = "过度概括"
    EMOTIONAL_REASONING = "情绪推理"
    LABELING = "贴标签"
    PERSONALIZATION = "个人化"
    SHOULD_STATEMENTS = "应该陈述"


class InterventionAction(str, Enum):
    """干预动作三级枚举"""
    SILENT = "silent"       # 不干预，静默观察
    SUBTLE = "subtle"       # 微干预：仅UI变化，无文本
    INTERVENE = "intervene" # 显式干预：主动发起对话


class InterventionUrgency(str, Enum):
    """干预紧迫程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EmotionTrend(str, Enum):
    """情绪历史趋势"""
    RISING = "上升"
    FALLING = "下降"
    STABLE = "平稳"


class MemoryType(str, Enum):
    """长期记忆类型"""
    CONVERSATION_SUMMARY = "conversation_summary"  # 对话摘要
    SESSION_INSIGHT = "session_insight"             # 会话洞察
    LONG_PATTERN = "compressed_pattern"             # 压缩后的长期模式


# ==============================================================================
# 感知数据模型
# ==============================================================================

class HeadPose(BaseModel):
    """头部姿态欧拉角（度）"""
    pitch: float = Field(0.0, description="俯仰角：负值=低头")
    yaw: float = Field(0.0, description="偏航角：左右偏转")
    roll: float = Field(0.0, description="翻滚角")


class AUIntensities(BaseModel):
    """面部动作单元强度（0~1）"""
    AU1: float = Field(0.0, ge=0.0, le=1.0, description="内眉上扬")
    AU2: float = Field(0.0, ge=0.0, le=1.0, description="外眉上扬")
    AU4: float = Field(0.0, ge=0.0, le=1.0, description="皱眉")
    AU5: float = Field(0.0, ge=0.0, le=1.0, description="瞪眼")
    AU6: float = Field(0.0, ge=0.0, le=1.0, description="颧骨上提")
    AU12: float = Field(0.0, ge=0.0, le=1.0, description="嘴角上扬（微笑）")
    AU15: float = Field(0.0, ge=0.0, le=1.0, description="嘴角下垂")
    AU17: float = Field(0.0, ge=0.0, le=1.0, description="下颌抬起")
    primary_emotion: str = Field("neutral", description="AU模型推断的基础情绪（英文）")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="AU模型置信度")


class AudioFeatures(BaseModel):
    """音频特征（openSMILE eGeMAPS）"""
    pitch: float = Field(0.0, description="基频F0（Hz）")
    loudness: float = Field(0.0, description="响度（归一化，0~1）")
    mfcc: list[float] = Field(default_factory=list, description="MFCC系数")
    speaking: bool = Field(False, description="是否正在说话（VAD）")


class PerceptionData(BaseModel):
    """
    多模态感知数据快照
    由感知微服务以10Hz频率写入 Redis（emotion:realtime:{session_id}）
    """
    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000),
        description="Unix毫秒时间戳"
    )
    session_id: str = Field(..., description="会话ID")
    head_pose: HeadPose = Field(default_factory=HeadPose)
    blink_rate: float = Field(0.0, description="眨眼频率（次/分钟）")
    au: AUIntensities = Field(default_factory=AUIntensities)
    audio: AudioFeatures = Field(default_factory=AudioFeatures)
    focus_level: float = Field(0.5, ge=0.0, le=1.0, description="专注度估计（0~1）")


# ==============================================================================
# 情感分析模型
# ==============================================================================

class ValenceArousal(BaseModel):
    """效价-唤醒度（PAD情感空间子集）"""
    valence: float = Field(0.0, ge=-1.0, le=1.0, description="效价：-1负面 ~ +1正面")
    arousal: float = Field(0.0, ge=0.0, le=1.0, description="唤醒度：0平静 ~ 1激动")
    dominance: float = Field(0.5, ge=0.0, le=1.0, description="优势度（可选）")


class QwenAnalysis(BaseModel):
    """
    Qwen-VL-Max 多模态分析输出
    由 analyze_scene 工具调用后解析得到
    """
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    primary_emotion: str = Field("中性", description="主要情绪（中文）")
    emotion_intensity: float = Field(0.0, ge=0.0, le=1.0)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    facial_cues: list[str] = Field(default_factory=list, description="面部线索描述")
    cognitive_distortions: list[str] = Field(default_factory=list)
    scene_description: str = Field("", description="场景自然语言描述")
    valence_arousal: ValenceArousal = Field(default_factory=ValenceArousal)
    raw_response: str = Field("", description="模型原始输出（调试用）")


class EmotionVector(BaseModel):
    """
    情感向量（fuse_emotion 节点的最终输出）
    融合了多模态客观证据与主观分析
    """
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    session_id: str = Field(..., description="会话ID")

    # 核心情绪字段
    primary_emotion: EmotionLabel = Field(EmotionLabel.NEUTRAL, description="主要情绪")
    secondary_emotion: EmotionLabel | None = Field(None, description="次要情绪（如有）")
    intensity: float = Field(0.0, ge=0.0, le=1.0, description="情绪强度")

    # PAD情感空间
    valence: float = Field(0.0, ge=-1.0, le=1.0)
    arousal: float = Field(0.0, ge=0.0, le=1.0)
    dominance: float = Field(0.5, ge=0.0, le=1.0)

    # 认知分析
    cognitive_distortions: list[CognitiveDistortion] = Field(
        default_factory=list,
        description="识别出的认知扭曲列表"
    )

    # 可信度
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="综合置信度")
    reasoning: str = Field("", description="LLM推理过程（调试用）")

    # 证据摘要（可选）
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="支持判断的证据摘要，如 {'au': {'AU4': 0.9}, 'qwen': '焦虑'}"
    )

    # 历史上下文
    history_context: dict[str, Any] = Field(
        default_factory=dict,
        description="历史情感上下文，如 {'recent_trend': '上升', 'baseline_deviation': 0.2}"
    )


# ==============================================================================
# 干预决策模型
# ==============================================================================

class UIInstruction(BaseModel):
    """前端 UI 控制指令"""
    color: str = Field("neutral", description="光晕颜色: blue/orange/green/purple/neutral")
    pulse: str = Field("slow", description="脉冲频率: slow/medium/fast/very_fast")


class InterventionDecision(BaseModel):
    """
    干预决策结果（decide_intervention 节点输出）
    """
    needed: bool = Field(False, description="是否需要任何形式的干预")
    urgency: InterventionUrgency = Field(InterventionUrgency.LOW)
    suggested_action: InterventionAction = Field(InterventionAction.SILENT)
    ui_instruction: UIInstruction = Field(default_factory=UIInstruction)
    recommended_strategy: str | None = Field(None, description="推荐的干预策略，如'5-4-3-2-1着陆技术'")
    reply: str = Field("", description="若需要显式干预，生成的回复文本")

    # 决策过程数据（供日志记录）
    intervention_score: float = Field(0.0, description="干预倾向分数")
    interrupt_cost: float = Field(0.0, description="打扰成本")
    trend: EmotionTrend = Field(EmotionTrend.STABLE, description="情绪历史趋势")


# ==============================================================================
# 记忆模型
# ==============================================================================

class ConversationMessage(BaseModel):
    """单条对话消息（存于Redis短期记忆）"""
    role: str = Field(..., description="角色: user / ai")
    content: str = Field(..., description="消息内容")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class SessionLogEntry(BaseModel):
    """会话日志条目（写入MySQL session_logs表）"""
    session_id: str
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    user_message: str = Field("", description="用户输入（如有）")
    perception_snapshot: dict[str, Any] = Field(default_factory=dict)
    emotion_vector: dict[str, Any] = Field(default_factory=dict)
    intervention_decision: dict[str, Any] = Field(default_factory=dict)
    ai_reply: str = Field("")
    retrieved_knowledge: list[Any] = Field(default_factory=list, description="RAG 检索结果（仅 intervene 路径有值）")


class LongTermMemory(BaseModel):
    """长期语义记忆条目（存于Chroma向量数据库）"""
    id: str = Field(..., description="唯一ID，格式 {user_id}_{timestamp}")
    user_id: str
    content: str = Field(..., description="反思文本（由LLM生成）")
    type: MemoryType = Field(MemoryType.CONVERSATION_SUMMARY)
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_cold: bool = Field(False, description="是否已归档到冷存储")
    cold_url: str = Field("", description="冷存储OSS URL（is_cold=True时使用）")


# ==============================================================================
# RAG 知识卡片模型
# ==============================================================================

class KnowledgeCard(BaseModel):
    """
    心理学知识卡片（从 Markdown 文件解析）
    YAML frontmatter 对应 metadata 字段
    """
    card_id: str = Field(..., description="卡片ID，如 CBT-ANX-001")
    title: str = Field(..., description="卡片标题")
    emotions: list[str] = Field(default_factory=list, description="适用情绪列表")
    cognitive_distortions: list[str] = Field(default_factory=list, description="适用认知扭曲列表")
    scenario: list[str] = Field(default_factory=list, description="适用场景")
    goal: str = Field("", description="干预目标")
    difficulty: str = Field("中等", description="难度评估")
    duration: str = Field("", description="预计时长")
    tags: list[str] = Field(default_factory=list)
    content: str = Field(..., description="卡片正文（Markdown）")


# ==============================================================================
# LLM 输出解析模型
# ==============================================================================

class EmotionAssessmentLLM(BaseModel):
    """
    DeepSeek 输出的 emotion_assessment 字段（原始格式）
    直接对应 Prompt 中要求的 JSON 结构，由 PydanticOutputParser 解析。
    解析成功后再映射为 EmotionVector。
    """
    primary_emotion: str = Field(..., description="主要情绪标签")
    intensity: float = Field(..., ge=0.0, le=1.0)
    valence: float = Field(0.0, ge=-1.0, le=1.0)
    arousal: float = Field(0.0, ge=0.0, le=1.0)
    dominance: float = Field(0.5, ge=0.0, le=1.0)
    cognitive_distortions: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    secondary_emotion: str | None = Field(None)

    # OCC 八维归因向量（文档 01-emotion-recognition/1.2.md）
    # OCC (Ortony-Clore-Collins) 情感归因模型，六个基础情感强度 0~1
    occ_joy: float = Field(0.0, ge=0.0, le=1.0, description="喜悦强度")
    occ_sadness: float = Field(0.0, ge=0.0, le=1.0, description="悲伤强度")
    occ_anger: float = Field(0.0, ge=0.0, le=1.0, description="愤怒强度")
    occ_fear: float = Field(0.0, ge=0.0, le=1.0, description="恐惧强度")
    occ_disgust: float = Field(0.0, ge=0.0, le=1.0, description="厌恶强度")
    occ_surprise: float = Field(0.0, ge=0.0, le=1.0, description="惊讶强度")
    occ_well_grounding: float = Field(0.0, ge=0.0, le=1.0, description="踏实感/安定感强度")
    occ_anticipation: float = Field(0.0, ge=0.0, le=1.0, description="期待感/焦虑倾向强度")

    reasoning: str = Field("", description="LLM推理过程（调试用）")


class FuseEmotionLLMOutput(BaseModel):
    """
    fuse_emotion 节点调用 DeepSeek 的完整输出容器。
    按计划只解析 emotion_assessment，不在此节点处理干预决策。
    """
    emotion_assessment: EmotionAssessmentLLM
