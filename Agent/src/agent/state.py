from __future__ import annotations

"""
婉情AI - LangGraph AgentState 定义
====================================
AgentState 是贯穿整个 LangGraph 图的共享状态容器。
所有节点（Node）通过读写 state 进行数据传递。

设计原则：
- 字段设为 Optional 并提供默认值，避免节点因字段缺失报错
- 时间戳统一使用 Unix 毫秒（int）
- 复杂对象使用 Pydantic 模型，简单标量直接使用 Python 原生类型
"""

import time
from typing import Annotated, Any

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field

from src.models.schemas import (
    EmotionVector,
    InterventionDecision,
    PerceptionData,
    QwenAnalysis,
)


class AgentState(MessagesState):
    """
    婉情AI 全局状态机状态

    继承 MessagesState 以自动支持 LangGraph 的消息管理。
    额外字段按模块分区定义。
    """

    # ------------------------------------------------------------------
    # 会话标识
    # ------------------------------------------------------------------
    session_id: str = Field(default="", description="当前会话ID")
    user_id: str = Field(default="", description="用户ID")

    # ------------------------------------------------------------------
    # 对话历史（由 Java 传入或从 Redis 读取，供 generate_reply 使用）
    # 使用独立字段而非 messages，避免与 LangGraph MessagesState 冲突
    # ------------------------------------------------------------------
    conversation_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="对话历史列表，每条含 role 和 content"
    )

    # ------------------------------------------------------------------
    # 感知数据（由感知微服务填充，或从Redis读取）
    # ------------------------------------------------------------------
    # 最新的感知数据快照
    latest_perception: PerceptionData | None = Field(
        default=None,
        description="最新一帧感知数据（MediaPipe + openSMILE + HuggingFace AU）"
    )
    # Qwen-VL-Max 分析结果（按需调用后存入）
    qwen_analysis: QwenAnalysis | None = Field(
        default=None,
        description="多模态大模型分析结果（高开销，按需触发）"
    )
    # 走神/专注模式标志
    is_focused_mode: bool = Field(
        default=False,
        description="True=专注模式（启动全量分析），False=走神模式（轻量监控）"
    )

    # ------------------------------------------------------------------
    # 情感识别（fuse_emotion 节点输出）
    # ------------------------------------------------------------------
    current_emotion: EmotionVector | None = Field(
        default=None,
        description="当前融合后的情感向量（fuse_emotion 节点输出）"
    )
    # 最近N条情感历史（用于趋势分析），从记忆库查询后存入
    emotion_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="最近30分钟情感记录列表，用于趋势计算"
    )

    # ------------------------------------------------------------------
    # 干预决策（decide_intervention 节点输出）
    # ------------------------------------------------------------------
    intervention_decision: InterventionDecision | None = Field(
        default=None,
        description="当前轮次的干预决策结果"
    )
    # 上次实际执行干预的时间戳（毫秒），用于冷却期判断
    last_intervention_time: int = Field(
        default=0,
        description="上次执行干预（intervene或subtle）的Unix毫秒时间戳"
    )
    # 用户拒绝惩罚系数（来自 Java 统计历史反馈，范围 [0.5, 1.5]）
    # 越大表示用户越倾向于拒绝干预，系统应更保守
    user_rejection_penalty: float = Field(
        default=1.0,
        description="用户拒绝惩罚系数，由 Java 根据历史反馈统计计算"
    )

    # ------------------------------------------------------------------
    # 记忆上下文（由记忆管理模块填充）
    # ------------------------------------------------------------------
    # 用户画像（会话启动时从MySQL加载）
    user_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="用户画像：姓名、年龄、实验分组、偏好等"
    )
    # 从向量库检索到的长期记忆片段（深度干预前检索）
    retrieved_long_term_memories: list[str] = Field(
        default_factory=list,
        description="与当前情境相关的长期记忆文本片段"
    )

    # ------------------------------------------------------------------
    # RAG 知识库（generate_reply 节点使用）
    # ------------------------------------------------------------------
    # 从 RAG 知识库检索到的心理学卡片内容
    retrieved_knowledge_cards: list[str] = Field(
        default_factory=list,
        description="检索到的心理学知识卡片内容，用于注入回复生成 Prompt"
    )
    # 检索结果（含 metadata 元数据），供 generate_reply 提取 recommended_strategy（任务1）
    retrieved_knowledge_cards_with_meta: list[dict[str, Any]] = Field(
        default_factory=list,
        description="检索到的心理学卡片，含 card_str/goal/meta 等，供 recommended_strategy 填充"
    )

    # ------------------------------------------------------------------
    # 任务上下文（可由外部注入）
    # ------------------------------------------------------------------
    task_phase: str = Field(
        default="unknown",
        description="任务阶段：experiment_task / idle / post_task 等"
    )
    # 当前用户输入的文本（可能为空，主动关怀场景下无需用户先说话）
    user_input: str = Field(
        default="",
        description="本轮用户输入的文本（可为空）"
    )

    # ------------------------------------------------------------------
    # 系统健康状态（由系统健康检查工具填充）
    # 用于防止 LLM 捏造系统状态信息（如"Java后端没启动"等幻觉）
    # ------------------------------------------------------------------
    system_health: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "多层系统健康状态（确定性事实）。包含："
            "java_backend_online, perception_service_online, redis_connected, "
            "emotion_model_loaded, has_realtime_perception"
        )
    )

    # ------------------------------------------------------------------
    # 路由控制（用于 LangGraph 条件边）
    # ------------------------------------------------------------------
    # 下一步执行的节点名称（由路由函数设置）
    next_node: str = Field(
        default="",
        description="路由标志，指示下一个执行节点"
    )

    # ------------------------------------------------------------------
    # 最终响应（return_result_node 写入，main.py 读取）
    # 必须是 AgentState 字段，LangGraph 才能在图执行后从 final_state 中提取
    # ------------------------------------------------------------------
    final_response: dict[str, Any] = Field(
        default_factory=dict,
        description="return_result_node 封装的最终响应，含 action/emotion/reply 等字段"
    )
