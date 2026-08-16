from __future__ import annotations

"""
婉情AI - Qwen-VL-Max 多模态场景分析工具
========================================
职责：
  封装对 Qwen-VL-Max API 的调用，将图像 + AU 参数整合为多模态 Prompt，
  输出结构化的 QwenAnalysis 对象。

触发时机（来自文档1.1.md）：
  仅在"专注模式"下按需调用（由 fuse_emotion 节点决定是否调用），
  而非每帧都触发，以控制 API 成本和延迟。

注意事项：
  - Qwen-VL-Max 使用 OpenAI 兼容格式，图像通过 base64 内联传入
  - 输出使用 PydanticOutputParser 解析，保证结构化
  - 若解析失败，返回默认中性分析结果，不阻断主流程
"""

import base64
import json
import time

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from config import qwen_config, emotion_config
from src.models.schemas import AUIntensities, HeadPose, QwenAnalysis, ValenceArousal
from src.utils.logger import logger


# ==============================================================================
# Qwen-VL 客户端（延迟初始化）
# ==============================================================================

_qwen_client: ChatOpenAI | None = None


def _get_qwen_client() -> ChatOpenAI:
    """获取 Qwen-VL 客户端（单例）"""
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = ChatOpenAI(
            model=qwen_config.VL_MODEL,
            api_key=qwen_config.API_KEY,
            base_url=qwen_config.BASE_URL,
            temperature=qwen_config.TEMPERATURE,
            max_tokens=qwen_config.MAX_TOKENS,
        )
    return _qwen_client


# ==============================================================================
# Prompt 模板
# ==============================================================================

_QWEN_SYSTEM_PROMPT = """你是一个专业的多模态情感分析助手，擅长通过面部图像和客观生理参数判断人的情绪状态。

【情绪标签枚举】
必须从以下选项中选取：焦虑、沮丧、平静、开心、疲惫、愤怒、恐惧、厌恶、惊讶、中性

【认知扭曲枚举】
若观察到，必须从以下选取：灾难化、读心术、非黑即白、过度概括、情绪推理、贴标签、个人化、应该陈述

【面部动作单元（AU）解读参考】
- AU4（皱眉）> 0.6：高强度负面情绪（焦虑/愤怒/恐惧）
- AU12（嘴角上扬）> 0.4：积极情绪；若同时 AU4 > 0.5 可能为苦笑
- AU15（嘴角下垂）> 0.5：悲伤/沮丧的典型标志
- AU1+AU4 组合：可能表示恐惧或悲伤
- AU5（瞪眼）> 0.5：恐惧或惊讶

【场景分析要点】
1. 注意整体情境（用户在做什么？工作/休息/交谈）
2. 眉毛、眼睛、嘴角是情绪的关键面部区域
3. 头部姿态可辅助判断：低头可能是疲惫或沮丧；抬头可能是自信或惊讶

【输出要求】
只输出以下 JSON，不包含任何其他文本或 markdown 代码块标记：
{format_instructions}"""


# ==============================================================================
# 核心分析函数
# ==============================================================================

async def analyze_scene_with_qwen(
    image_base64: str,
    au: AUIntensities,
    head_pose: HeadPose,
    blink_rate: float = 0.0,
    session_id: str = "",
) -> QwenAnalysis:
    """
    调用 Qwen-VL-Max，综合图像和 AU 客观参数，输出结构化情感分析。

    Args:
        image_base64: 用户面部截图的 base64 编码字符串（JPEG/PNG）
        au: HuggingFace AU 模型输出的面部动作单元强度
        head_pose: 头部欧拉角
        blink_rate: 眨眼频率（次/分钟）
        session_id: 会话ID（用于日志）

    Returns:
        QwenAnalysis —— 结构化情感分析，含 primary_emotion、facial_cues 等
        若调用失败，返回默认中性分析结果（不抛异常，避免阻断主流程）
    """
    # --- 构建 AU 自然语言描述（注入 Prompt 的客观证据） ---
    au_description = _build_au_description(au, head_pose, blink_rate)

    # --- 构建输出解析器 ---
    parser = PydanticOutputParser(pydantic_object=_QwenRawOutput)

    # --- 构建系统提示 ---
    system_content = _QWEN_SYSTEM_PROMPT.format(
        format_instructions=parser.get_format_instructions()
    )

    # --- 构建多模态消息（图像 + AU文本） ---
    human_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
        },
        {
            "type": "text",
            "text": (
                f"【客观感知数据】\n{au_description}\n\n"
                "请结合图像和以上客观数据，分析当前用户的情绪状态。"
            ),
        },
    ]

    logger.info(f"[Qwen-VL] 开始分析: session={session_id}, AU4={au.AU4:.2f}, pitch={head_pose.pitch:.1f}°")

    try:
        client = _get_qwen_client()
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ]
        response = await client.ainvoke(messages)
        raw_text = response.content

        # --- 解析输出 ---
        raw_output = parser.parse(raw_text)
        result = _map_to_qwen_analysis(raw_output, session_id)
        logger.info(
            f"[Qwen-VL] 分析完成: emotion={result.primary_emotion}, "
            f"intensity={result.emotion_intensity:.2f}, confidence={result.confidence:.2f}"
        )
        return result

    except ValidationError as ve:
        logger.warning(f"[Qwen-VL] 输出解析失败（ValidationError）: {ve}")
        return _default_neutral_analysis(session_id)
    except Exception as e:
        logger.error(f"[Qwen-VL] API 调用失败: {e}")
        return _default_neutral_analysis(session_id)


# ==============================================================================
# 内部辅助函数
# ==============================================================================

def _build_au_description(au: AUIntensities, head_pose: HeadPose, blink_rate: float) -> str:
    """将 AU 数值转换为自然语言描述，注入 Prompt 作为客观证据"""
    lines = [
        f"- AU4（皱眉）强度：{au.AU4:.2f}",
        f"- AU6（颧骨上提）强度：{au.AU6:.2f}",
        f"- AU12（嘴角上扬）强度：{au.AU12:.2f}",
        f"- AU15（嘴角下垂）强度：{au.AU15:.2f}",
        f"- AU1（内眉上扬）强度：{au.AU1:.2f}",
        f"- AU5（瞪眼）强度：{au.AU5:.2f}",
        f"- 头部俯仰角（pitch）：{head_pose.pitch:.1f}°（负值=低头）",
        f"- 头部偏航角（yaw）：{head_pose.yaw:.1f}°",
        f"- 眨眼频率：{blink_rate:.1f} 次/分钟",
        f"- AU 模型初步判断：{au.primary_emotion}（置信度={au.confidence:.2f}）",
    ]
    return "\n".join(lines)


class _QwenRawOutput:
    """Qwen-VL 输出的内部解析模型（局部使用，不对外暴露）"""
    from pydantic import BaseModel as _B, Field as _F

    class _QwenRawOutput(_B):
        primary_emotion: str
        emotion_intensity: float
        confidence: float
        facial_cues: list[str] = []
        cognitive_distortions: list[str] = []
        scene_description: str = ""
        valence: float = 0.0
        arousal: float = 0.0


# 重新定义（避免嵌套类 PydanticOutputParser 的问题）
from pydantic import BaseModel as _BaseModel, Field as _Field


class _QwenRawOutput(_BaseModel):
    """Qwen-VL 原始输出解析模型"""
    primary_emotion: str = _Field(..., description="主要情绪")
    emotion_intensity: float = _Field(0.5, ge=0.0, le=1.0)
    confidence: float = _Field(0.5, ge=0.0, le=1.0)
    facial_cues: list[str] = _Field(default_factory=list)
    cognitive_distortions: list[str] = _Field(default_factory=list)
    scene_description: str = _Field("")
    valence: float = _Field(0.0, ge=-1.0, le=1.0)
    arousal: float = _Field(0.0, ge=0.0, le=1.0)


def _map_to_qwen_analysis(raw: _QwenRawOutput, session_id: str) -> QwenAnalysis:
    """将 _QwenRawOutput 映射为标准 QwenAnalysis 对象"""
    return QwenAnalysis(
        timestamp=int(time.time() * 1000),
        primary_emotion=raw.primary_emotion,
        emotion_intensity=raw.emotion_intensity,
        confidence=raw.confidence,
        facial_cues=raw.facial_cues,
        cognitive_distortions=raw.cognitive_distortions,
        scene_description=raw.scene_description,
        valence_arousal=ValenceArousal(valence=raw.valence, arousal=raw.arousal),
    )


def _default_neutral_analysis(session_id: str = "") -> QwenAnalysis:
    """当 Qwen-VL 调用失败时，返回默认中性分析（不阻断主流程）"""
    return QwenAnalysis(
        timestamp=int(time.time() * 1000),
        primary_emotion="中性",
        emotion_intensity=0.2,
        confidence=0.1,  # 置信度极低，标记为不可信
        facial_cues=[],
        cognitive_distortions=[],
        scene_description="[Qwen-VL 分析失败，使用默认中性状态]",
        valence_arousal=ValenceArousal(valence=0.0, arousal=0.2),
        raw_response="",
    )
