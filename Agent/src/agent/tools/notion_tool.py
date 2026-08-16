from __future__ import annotations

"""
婉情AI - Notion 情绪日记工具
================================
通过 LangChain @tool 装饰器封装 Notion API，
实现"帮用户在 Notion 中记录情绪日记"的 Tool Calling 能力。

数据库列结构（来源：Notion 真实数据库 schema）：
  标题         title        — 自动生成或用户提供
  日期         date         — 当前时间戳
  情绪         select       — 喜悦 / 平静 / 焦虑 / 悲伤 / 愤怒
  强度         number       — 0 ~ 10
  触发事件     rich_text    — 触发情绪的事件描述
  身体感觉     rich_text    — 用户描述的身体感受
  AI 建议     rich_text    — Agent 根据心理学知识生成的建议
  反思         rich_text    — 用户自我反思（可选）
  应对方式     multi_select — 深呼吸 / 冥想 / 运动 / 写作 / 倾诉 / 休息 / 听音乐 / 散步

.env 配置（由 Java 微服务在启动时写入）：
  NOTION_API_KEY      — Notion Integration Token
  NOTION_DATABASE_ID  — 情绪日记数据库 ID

使用示例（Agent Tool Calling）：
  LLM 判断用户需要记录日记 → 调用 record_mood_diary →
  record_mood_diary(event_description="...", emotion_type="焦虑", intensity=0.7,
                    ai_advice="建议尝试深呼吸...") →
  Notion 页面创建成功，返回 URL
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

from src.utils.logger import logger


# ==============================================================================
# Notion 客户端初始化（延迟加载，复用连接）
# ==============================================================================

_notion_client: Any = None


def _get_notion_client() -> Any:
    """
    获取 Notion 客户端单例。
    从环境变量读取 API Key，按需初始化。
    """
    global _notion_client
    if _notion_client is None:
        api_key = os.getenv("NOTION_API_KEY")
        if not api_key:
            raise ValueError("NOTION_API_KEY 环境变量未配置，请在 .env 中设置")
        import notion_client
        _notion_client = notion_client.Client(auth=api_key)
        logger.info("[Notion] Notion 客户端初始化成功")
    return _notion_client


def _get_database_id() -> str:
    """从环境变量读取情绪日记数据库 ID"""
    db_id = os.getenv("NOTION_DATABASE_ID")
    if not db_id:
        raise ValueError("NOTION_DATABASE_ID 环境变量未配置，请在 .env 中设置")
    return db_id


# ==============================================================================
# 情绪标签标准化映射（EmotionLabel 枚举 → Notion select 选项）
# ==============================================================================

_EMOTION_LABEL_MAP: dict[str, str] = {
    # 中文 EmotionLabel 枚举 → Notion select 选项
    "开心": "喜悦",
    "喜悦": "喜悦",
    "平静": "平静",
    "焦虑": "焦虑",
    "沮丧": "悲伤",
    "悲伤": "悲伤",
    "愤怒": "愤怒",
    "生气": "愤怒",
    "恐惧": "焦虑",
    "厌恶": "焦虑",
    "惊讶": "平静",
    "疲惫": "平静",
    "中性": "平静",
}

# Notion 中可用的 select 选项列表（用于 Tool Description 中告诉 LLM）
_NOTION_EMOTION_OPTIONS = ["喜悦", "平静", "焦虑", "悲伤", "愤怒"]
_NOTION_COPING_OPTIONS = [
    "深呼吸", "冥想", "运动", "写作",
    "倾诉", "休息", "听音乐", "散步",
]


# ==============================================================================
# 核心工具函数
# ==============================================================================

@tool(description=(
    "将用户情绪记录写入 Notion 情绪日记数据库。"
    "当 Agent 判断用户情绪达到一定强度后自动调用，或用户明确要求「帮我记录日记」时调用。"
    " emotion_type 必须从以下选项中选择：喜悦, 平静, 焦虑, 悲伤, 愤怒。"
    " coping_strategy 可从以下选项中选择（逗号分隔多个）：深呼吸, 冥想, 运动, 写作, 倾诉, 休息, 听音乐, 散步。"
))
def record_mood_diary(
    event_description: str,
    emotion_type: str,
    intensity: float,
    ai_advice: str,
    body_sensation: str = "",
    coping_strategy: str = "",
    reflection: str = "",
    custom_title: str = "",
) -> str:
    """
    将用户情绪记录写入 Notion 情绪日记数据库。

    此工具应在 Agent 判断用户情绪达到一定强度后自动调用，
    或在用户明确要求"帮我记录日记"时调用。

    Args:
        event_description:
            触发事件描述（必填）。描述是什么事情引发了当前情绪，
            例如"今天的工作汇报被领导批评了"。

        emotion_type:
            情绪类型（必填）。从以下选项中选择最匹配的：
            {emotion_options}
            如果都不匹配，请选择最接近的，并在 AI 建议中说明判断理由。

        intensity:
            情绪强度（必填）。浮点数，范围 0.0 ~ 1.0。
            0.0 = 完全平静，1.0 = 极度强烈。
            请根据感知数据和对话内容综合评估。
            注意：代码内部会将该值乘以 10，存储到 Notion 数据库的 0~10 列中。

        ai_advice:
            AI 建议（必填）。根据心理学知识和小红书上用户的心理学干预方案，
            给出的简短个性化建议（1-3 句话，30-60 字）。
            语气温暖、支持性，不要过于技术化。

        body_sensation:
            身体感觉（可选）。用户描述的身体感受，
            例如"胸口发闷"、"胃部紧绷"、"太阳穴隐隐作痛"。
            如无信息可留空字符串。

        coping_strategy:
            应对方式（可选）。从以下选项中选择一个或多个（用逗号分隔）：
            {coping_options}
            如无信息可留空字符串。

        reflection:
            自我反思（可选）。用户对本次情绪体验的反思，
            例如"我发现自己每次开会汇报时都会特别紧张"，
            或者由 LLM 代为生成一句引导性反思。
            如无信息可留空字符串。

        custom_title:
            自定义标题（可选）。如不提供，系统自动生成。
            格式建议：情绪标签 + 简短触发事件，如"焦虑 - 工作汇报被批评"。

    Returns:
        JSON 字符串，格式：
        成功时：{{"success": true, "page_id": "...", "page_url": "https://www.notion.so/..."}}
        失败时：{{"success": false, "error": "错误描述"}}

    Example:
        >>> result = record_mood_diary(
        ...     event_description="今天汇报被领导批评了",
        ...     emotion_type="焦虑",
        ...     intensity=0.75,
        ...     ai_advice="被批评后的焦虑很常见，建议先深呼吸 4-7-8 缓解身体紧张，再客观回顾领导的反馈。",
        ...     body_sensation="胸口有点发紧",
        ...     coping_strategy="深呼吸",
        ...     reflection="我发现自己对批评的容忍度很低，需要多练习情绪分离。",
        ...     custom_title="焦虑 - 工作汇报被批评"
        ... )
        >>> print(result)
        {{"success": true, "page_id": "xxx", "page_url": "https://www.notion.so/xxx"}}
    """.format(
        emotion_options=_NOTION_EMOTION_OPTIONS,
        coping_options=_NOTION_COPING_OPTIONS,
    )
    # ─────────────────────────────────────────────────────────────────────
    # 函数实现（tool docstring 结束后执行）
    # ─────────────────────────────────────────────────────────────────────
    try:
        client = _get_notion_client()
        database_id = _get_database_id()

        # 1. 标准化情绪标签
        normalized_emotion = _EMOTION_LABEL_MAP.get(emotion_type, emotion_type)
        if normalized_emotion not in _NOTION_EMOTION_OPTIONS:
            logger.warning(
                f"[Notion] emotion_type='{emotion_type}' 不在 Notion 选项中，"
                f"尝试映射为 '{normalized_emotion}'"
            )

        # 2. 构建页面属性（严格遵循 Notion API schema）
        # 参考数据库列：标题 / 日期 / 情绪(select) / 强度(number) /
        #              触发事件 / 身体感觉 / AI 建议 / 反思 / 应对方式
        now = datetime.now(timezone.utc)

        # 强度 number：OCC 归一化为 0~1，Notion 数据库列为 0~10，乘以 10 换算
        stored_intensity = round(float(intensity) * 10, 1)

        properties: dict[str, Any] = {
            # 标题：默认格式 "情绪日记 - YYYY-MM-DD HH:MM"
            "标题": {
                "title": [
                    {
                        "text": {
                            "content": custom_title
                            if custom_title
                            else f"情绪日记 - {now.strftime('%Y-%m-%d %H:%M')}"
                        }
                    }
                ]
            },
            # 日期
            "日期": {"date": {"start": now.isoformat()}},
            # 情绪 select
            "情绪": {"select": {"name": normalized_emotion}},
            # 强度 number：统一换算为 0~10 范围
            "强度": {"number": stored_intensity},
        }

        # 可选字段：仅在内容非空时才添加
        def rich_text_field(content: str) -> dict:
            return {"rich_text": [{"text": {"content": content[:2000]}}]}

        if event_description:
            properties["触发事件"] = rich_text_field(event_description)

        if body_sensation:
            properties["身体感觉"] = rich_text_field(body_sensation)

        if ai_advice:
            properties["AI 建议"] = rich_text_field(ai_advice)

        if reflection:
            properties["反思"] = rich_text_field(reflection)

        if coping_strategy:
            # multi_select 格式：逗号分隔转为列表
            options = [opt.strip() for opt in coping_strategy.split(",") if opt.strip()]
            if options:
                properties["应对方式"] = {
                    "multi_select": [{"name": opt} for opt in options]
                }

        # 3. 调用 Notion API 创建页面
        logger.info(
            f"[Notion] 正在创建情绪日记页面 | "
            f"情绪={normalized_emotion}, 强度={stored_intensity}/10, "
            f"触发事件={event_description[:30]!r}"
        )

        page = client.pages.create(
            parent={"database_id": database_id},
            properties=properties,
        )

        page_id: str = page["id"]
        page_url = f"https://www.notion.so/{page_id.replace('-', '')}"

        logger.info(f"[Notion] 页面创建成功 | id={page_id} | url={page_url}")

        return json.dumps(
            {
                "success": True,
                "page_id": page_id,
                "page_url": page_url,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        logger.error(f"[Notion] 记录情绪日记失败: {e}")
        return json.dumps(
            {"success": False, "error": str(e)},
            ensure_ascii=False,
        )
