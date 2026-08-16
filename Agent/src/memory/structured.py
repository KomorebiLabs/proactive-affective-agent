"""
婉情AI - 结构化情景记忆 (Structured Episodic Memory)
=====================================================
架构说明（重要防呆）：
 - 为保障微服务架构的数据唯一归属权，Python AI 服务【不直接】连接 MySQL。
 - 用户画像、会话日志等数据统一存储在 Java Spring Boot 侧。
 - 本模块提供：
   1. 将 Python 的结构化决策数据（EmotionVector、InterventionDecision等）序列化，
      转为 Java ConversationController /internal/conversation/log 期望的字段格式。
   2. 基于 AgentState 提取 Java 传来的静态画像并供节点使用的方法。
"""

from typing import Any

from src.agent.state import AgentState
from src.models.schemas import SessionLogEntry


def export_session_log(state: AgentState) -> dict[str, Any]:
    """
    当 LangGraph 每次决策完毕时，提取关键状态供 Java 后端记录到 MySQL session_logs 表。

    返回字典的字段与 Java ConversationController POST /internal/conversation/log 完全对齐：
      session_id, user_message, ai_reply,
      intervention_action, intervention_urgency, intervention_score,
      perception_snapshot, emotion_vector, decision_detail, retrieved_knowledge

    Returns:
        序列化安全的字典（可直接作为 HTTP JSON Body 发送给 Java）
    """
    perception = state.get("latest_perception")
    emotion = state.get("current_emotion")
    decision = state.get("intervention_decision")
    user_input = state.get("user_input", "")
    retrieved_knowledge = state.get("retrieved_knowledge_cards") or []

    # 展开 decision 对象，过滤掉顶层已提取的字段
    decision_dict = decision.model_dump() if decision else {}
    decision_detail = {
        k: v
        for k, v in decision_dict.items()
        if k not in ("suggested_action", "urgency", "intervention_score")
    }

    # 与 Java DTO (SessionLog) 的字段完全对齐
    log_dict = {
        "session_id": state.get("session_id", ""),
        "user_message": user_input,
        "ai_reply": getattr(decision, "reply", "") if decision else "",
        # Java 顶层字段
        "intervention_action": decision_dict.get("suggested_action", ""),
        "intervention_urgency": decision_dict.get("urgency", ""),
        "intervention_score": decision_dict.get("intervention_score", 0.0),
        # JSON 字段
        "perception_snapshot": perception.model_dump() if perception else {},
        "emotion_vector": emotion.model_dump() if emotion else {},
        "decision_detail": decision_detail,
        "retrieved_knowledge": retrieved_knowledge,
    }

    return log_dict


def get_user_profile_context(state: AgentState) -> str:
    """
    提取并格式化用户画像数据，准备注入到 DeepSeek 的 System Prompt 中。
    （这些数据是 Java 侧发起请求时一并塞带来的结构化数据）
    """
    profile = state.user_profile
    if not profile:
        return ""

    lines = ["[用户画像]"]
    if "name" in profile:
        lines.append(f"- 称呼: {profile['name']}")
    if "age" in profile:
        lines.append(f"- 年龄: {profile['age']}")
    if "experiment_group" in profile:
        lines.append(f"- 分组: {profile['experiment_group']}")
    if "preferences" in profile:
        lines.append(f"- 偏好: {profile['preferences']}")

    return "\n".join(lines)
