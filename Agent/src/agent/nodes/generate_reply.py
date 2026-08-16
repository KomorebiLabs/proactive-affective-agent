from __future__ import annotations

"""
婉情AI - generate_reply LangGraph 节点
======================================
职责：当干预决策为 INTERVENE 或 SUBTLE 时，基于情感向量 + RAG 检索结果，
      调用 DeepSeek 生成结构化的关怀回复。

触发条件（由 decide_intervention 的 suggested_action 决定）：
  - INTERVENE：需要 DeepSeek 生成完整关怀对话回复
  - SUBTLE：同样需要生成回复（仅发送给前端，不主动推送通知）

Prompt 设计严格遵循文档：
  - context-docs/04-rag-knowledge/01.md（RAG 检索 + Prompt 设计）
  - context-docs/02-intervention-decision/01.md（干预策略三级）
"""

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.state import AgentState
from src.agent.tools.notion_tool import record_mood_diary
from src.agent.tools.system_health import SystemHealthStatus
from src.models.schemas import InterventionAction, InterventionDecision
from src.utils.logger import logger
from src.utils.llm_common import get_deepseek_client


# ==============================================================================
# LLM 输出模型
# ==============================================================================

class GenerateReplyLLMOutput(BaseModel):
    """DeepSeek 输出格式约束"""
    reply: str = Field(..., description="生成的关怀回复文本，应自然、温暖、易于理解")
    recommended_strategy: str | None = Field(
        None,
        description="推荐的心理学技术名称，如'5-4-3-2-1着陆技术'、'认知重构'等"
    )


# ==============================================================================
# Prompt 模板（严格遵循文档 04-rag-knowledge/01.md）
# ==============================================================================

_SYSTEM_PROMPT = """你是一位温暖、善解人意的心理支持助手，更是用户亲密的朋友，名为"婉情"。
你的任务是根据用户的情感状态和心理学知识，生成一段简短、自然的关怀回复。

【回复风格要求】
- 语言温暖、亲切，像一位耐心的朋友在倾听
- 回复长度控制在 30-60 字左右（一个短段落）
- 不使用专业术语，不做诊断，不给压力
- 如果适合，可轻柔地引导用户关注当下或呼吸

【必须避免的句式】（极其重要！任何违反以下规则的回复将被直接拒绝）
- ❌ 严格禁止以"看到你..."开头（例：看到你很开心、看到你很紧张、看到你在哭）
- ❌ 严格禁止以"我能感受到你..."开头（例：我能感受到你的不安、你的担忧）
- ❌ 严格禁止以"注意到你..."开头
- ❌ 严格禁止以"观察到你..."开头
- ❌ 严格禁止"看到你xxx，我能感受到你yyy"的固定三段式
- ❌ 禁止在每句话都提及用户的情绪状态
- ❌ 禁止以任何形式开头描述你"观察"或"感知"到用户的行为

【正确开场方式示例】（必须从中随机选择，不要每次都选第一个）
1. 直接问候："今天感觉怎么样？"
2. 分享感受："你这么说，让我也挺开心的。"
3. 轻松话题："你之前提到过洛克王国，最近有什么新发现吗？"
4. 开放式探询："最近有什么让你特别在意的事情吗？"
5. 轻松调侃："看你这样，我都有点想和你聊聊天了。"
6. 温和肯定："能这样说出来，已经很不容易了。"

【回复结构】
1. 自然地开场（从上面的"正确开场方式"中选一种）
2. 如果检索到了心理学技术，可以温和地提及一个轻量的技巧名称（不要展开讲解步骤）
3. 以开放式问句结尾，鼓励用户继续表达

【Notion 情绪日记工具】
你可以使用 record_mood_diary 工具将情绪记录自动写入用户的 Notion 情绪日记。
当出现以下情况时，请主动调用此工具：
  - 用户情绪强度 >= 0.6（中高强度）且内容涉及具体生活事件
  - 用户明确说"帮我记一下"、"写到日记里"等
  - 对话中出现明显的情绪波动（如哭泣、叹气、表达压抑等）
调用时，请传入：
  - event_description：触发情绪的事件（从对话中提取，不超过 200 字）
  - emotion_type：从"喜悦/平静/焦虑/悲伤/愤怒"中选择最匹配的
  - intensity：情绪强度（0.0~1.0）
  - ai_advice：根据心理学知识给出的 1-3 句话建议（30-60 字）
  - body_sensation（如有）：用户提到的身体感受
  - reflection（如有）：引导性自我反思（1 句话）

【系统状态声明】
重要：以下【系统状态确认】中的信息是经过程序验证的真实状态，
请在回复中不要否认或质疑这些已确认的事实，也不要编造任何系统状态信息。
{system_health_facts}

{format_instructions}"""

_HUMAN_TEMPLATE = """【当前干预模式】：{intervention_mode}
（轻量关怀模式：简短自然，像朋友间的问候；深度干预模式：温暖专业，结合心理学知识）

【用户当前情感状态】
情绪：{emotion_state}
情绪强度：{intensity}
认知扭曲识别：{cognitive_distortions}
OCC八维归因：{occ_vector}

【对话历史】（请务必参考这些上下文进行回复）
{conversation_history}

【用户历史记忆】（来自长期记忆库，请据此个性化回复）
{personal_memories}

【心理学知识参考】
{knowledge_cards}

请基于以上信息，生成一段适合当前情境的关怀回复。注意：
1. 请务必参考【对话历史】中的内容，用户之前提到的事情要记得
2. 如果有用户历史记忆，请结合其历史背景给出个性化回复
3. 回复风格：自然、温暖，像一个真正关心用户的朋友
4. 回复长度：轻量关怀模式 20-40 字（朋友问候），深度干预模式 30-60 字（专业支持）"""


# ==============================================================================
# LLM 输出清洗
# ==============================================================================

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


def _normalize_json_string(text: str) -> str:
    """
    预处理 JSON 字符串，修复常见格式问题。

    核心问题：DeepSeek 有时在 JSON 字符串内容中使用中文引号，
    导致 json.loads() 解析失败。解决方案：将字符串内容中的中文引号替换为单引号。
    """
    # 中文引号的 Unicode 码点
    CN_OPEN = "\u201c"  # "
    CN_CLOSE = "\u201d"  # "

    # 先尝试直接解析
    try:
        json.loads(text)
        return text  # 已经可以解析，不需要处理
    except json.JSONDecodeError:
        pass

    # 逐字符处理：替换字符串内容中的中文引号为单引号
    result = []
    i = 0
    in_json_string = False
    escape_next = False

    while i < len(text):
        char = text[i]

        # 处理转义字符
        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue

        if char == "\\":
            result.append(char)
            escape_next = True
            i += 1
            continue

        # 检测 JSON 字符串边界
        if char == '"':
            in_json_string = not in_json_string
            result.append(char)
        elif in_json_string and (char == CN_OPEN or char == CN_CLOSE):
            # 在 JSON 字符串内部遇到中文引号，替换为单引号
            result.append("'")
        else:
            result.append(char)

        i += 1

    return "".join(result)


def _clean_llm_json(raw_text: str) -> tuple[str, dict | None]:
    """
    清洗 LLM 输出，提取 JSON 部分。

    Returns:
        (cleaned_text, json_data) - 返回清洗后的文本和提取到的 JSON 数据
    """
    text = raw_text.strip()
    if not text:
        return "", None

    # 1. 尝试直接解析整个文本（如果它是纯 JSON）
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "reply" in data:
            logger.info("[generate_reply] 直接解析 JSON 成功")
            return "", data
    except json.JSONDecodeError:
        pass

    # 2. 提取 Markdown 代码块中的 JSON
    matches = _JSON_BLOCK_RE.findall(text)
    for json_str in matches:
        json_str = json_str.strip()
        # 预处理：规范化 JSON 格式
        json_str = _normalize_json_string(json_str)
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "reply" in data:
                # 提取 JSON 块之前的内容作为额外文本
                text_before = text[:text.find("```")].strip()
                reply_preview = data.get("reply", "")[:30]
                logger.info(f"[generate_reply] 从 Markdown 代码块提取 JSON 成功: reply={reply_preview}...")
                return text_before, data
        except json.JSONDecodeError as e:
            logger.debug(f"[generate_reply] JSON 解析失败: {e}, 原始内容: {json_str[:50]}...")
            continue

    # 3. 尝试在文本中查找 JSON 对象（多种模式）
    json_patterns = [
        r'\{\s*"reply"\s*:\s*"[^"]*"[^}]*\}',  # reply 在前面的紧凑格式
        r'\{\s*"reply"[^}]+\}',  # reply 在前面的宽松格式
    ]
    for pattern in json_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                json_str = _normalize_json_string(match.group())
                data = json.loads(json_str)
                if isinstance(data, dict) and "reply" in data:
                    logger.info(f"[generate_reply] 通过正则匹配提取 JSON")
                    return "", data
            except json.JSONDecodeError:
                continue

    # 4. 没有找到 JSON，检查是否是纯文本回复（不含 JSON）
    if not text.startswith("{") and not text.startswith("["):
        # 排除明显是代码块开头的情况
        if "```" not in text[:10] and "reply" not in text.lower():
            logger.info("[generate_reply] 未检测到 JSON，使用纯文本回复")
            return text, None

    # 5. 最后兜底：尝试找到并解析第一个 { 到最后一个 } 的内容
    try:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = _normalize_json_string(text[first_brace:last_brace + 1])
            data = json.loads(potential_json)
            if isinstance(data, dict) and "reply" in data:
                logger.info("[generate_reply] 兜底解析 JSON 成功")
                return "", data
    except json.JSONDecodeError:
        pass

    # 6. 完全失败，返回原始文本（去除 markdown 代码块）
    cleaned = re.sub(r"```[^`]*```", "", text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text, None


def _parse_llm_output(parser: PydanticOutputParser, raw_text: str) -> GenerateReplyLLMOutput:
    """
    带清洗的 LLM 输出解析。

    解析优先级：
      1. 提取 Markdown 代码块或末尾的 JSON
      2. json.loads + model_validate
      3. 提取纯文本回复（无 JSON 时）
      4. 最终兜底：固定文本
    """
    cleaned, json_data = _clean_llm_json(raw_text)

    # 如果成功提取到 JSON 数据
    if json_data and isinstance(json_data, dict) and "reply" in json_data:
        reply_text = json_data.get("reply", "").strip()
        if reply_text:
            logger.info(f"[generate_reply] 从 JSON 中提取回复: {reply_text[:30]}...")
            return GenerateReplyLLMOutput(
                reply=reply_text,
                recommended_strategy=json_data.get("recommended_strategy")
            )

    # 如果有纯文本部分（JSON 之前的文字）
    if cleaned and len(cleaned) >= 2:
        # 检查是否看起来像完整的自然语言回复（不是 JSON 片段）
        if not cleaned.startswith("{") and not cleaned.startswith("["):
            logger.info(f"[generate_reply] LLM 返回纯文本: {cleaned[:30]}...")
            return GenerateReplyLLMOutput(
                reply=cleaned,
                recommended_strategy=None
            )

    # 尝试 PydanticOutputParser 作为最后的兜底
    try:
        return parser.parse(raw_text)
    except Exception as e:
        logger.warning(f"[generate_reply] PydanticOutputParser 解析失败: {e}")

    # 所有方法都失败，返回最终兜底
    logger.warning(f"[generate_reply] LLM 输出解析全部失败，使用最终兜底文本")
    return GenerateReplyLLMOutput(reply="我在这里陪着你，想说什么都可以告诉我。", recommended_strategy=None)


# ==============================================================================
# 主节点函数
# ==============================================================================

async def generate_reply_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph generate_reply 节点：生成关怀回复。

    【优化 v2】根据干预模式区分回复风格：
      - SUBTLE（轻度干预）：轻量回复，1张知识卡片，简短自然
      - INTERVENE（深度干预）：完整关怀，3张知识卡片，温暖专业

    触发条件：
      - decide_intervention 输出 suggested_action == INTERVENE
      - decide_intervention 输出 suggested_action == SUBTLE（同样生成回复）

    Args:
        state: 当前 AgentState

    Returns:
        dict，更新 intervention_decision 中的 reply 和 recommended_strategy
    """
    session_id = state.get("session_id", "unknown")
    logger.info(f"[generate_reply] === 开始生成关怀回复: session={session_id} ===")

    decision = state.get("intervention_decision")
    if decision is None:
        logger.warning("[generate_reply] 无干预决策，跳过回复生成")
        return {}

    action = decision.suggested_action
    emotion = state.get("current_emotion")
    retrieved_cards: list[str] = state.get("retrieved_knowledge_cards", [])
    retrieved_cards_with_meta: list[dict] = state.get("retrieved_knowledge_cards_with_meta", [])
    retrieved_memories: list[str] = state.get("retrieved_long_term_memories", [])

    # 【优化 v2】根据干预模式决定回复风格
    is_subtle = (action.value == "subtle")
    intervention_mode = "轻量关怀模式" if is_subtle else "深度干预模式"
    logger.info(f"[generate_reply] 干预模式: {intervention_mode}, 知识卡片数量: {len(retrieved_cards)}")

    # 构建知识卡片字符串
    if is_subtle:
        # SUBTLE 模式：最多1张卡片，轻量化描述
        knowledge_cards_str = retrieved_cards[0] if retrieved_cards else "（暂无相关心理学知识参考）"
    else:
        # INTERVENE 模式：完整卡片列表
        knowledge_cards_str = "\n\n".join(retrieved_cards) if retrieved_cards else "（暂无相关心理学知识参考）"

    memories_str = "\n\n".join(retrieved_memories) if retrieved_memories else "（暂无历史记忆）"

    # 提取对话历史（短期记忆中最近 N 条）
    conversation_history = _get_conversation_history(state)
    if not conversation_history:
        conversation_history = "（暂无对话历史，这是本轮首次互动）"

    # 构建情感状态描述
    emotion_state = emotion.primary_emotion.value if emotion else "未知"
    intensity = emotion.intensity if emotion else 0.0

    distortions = []
    if emotion and emotion.cognitive_distortions:
        distortions = [d.value for d in emotion.cognitive_distortions]
    cognitive_distortions_str = "、".join(distortions) if distortions else "未识别出认知扭曲"

    # 构建 OCC 八维归因描述（用于 Prompt 注入）
    occ_str = _build_occ_string(emotion)

    # 【优化 v2】构建 LLM Prompt，注入干预模式
    parser = PydanticOutputParser(pydantic_object=GenerateReplyLLMOutput)
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("human", _HUMAN_TEMPLATE),
    ])

    # 注入系统健康状态（防止 LLM 捏造系统状态）
    system_health: dict = state.get("system_health", {})
    health_obj = SystemHealthStatus(
        java_backend_online=system_health.get("java_backend_online", False),
        perception_service_online=system_health.get("perception_service_online", False),
        redis_connected=system_health.get("redis_connected", False),
        emotion_model_loaded=system_health.get("emotion_model_loaded", False),
        has_realtime_perception=system_health.get("has_realtime_perception", False),
    )
    system_health_facts = health_obj.to_fact_string()

    logger.info(f"[generate_reply] 调用 DeepSeek 生成回复 (action={action.value}, mode={intervention_mode}) ...")

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    # 为 LLM 绑定 Notion 情绪日记工具（Tool Calling）
    # DeepSeek 会自动判断是否需要调用 record_mood_diary
    client = get_deepseek_client()
    client_with_tools = client.bind_tools([record_mood_diary])

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # 第一轮调用：LLM 可能返回文本回复，也可能触发 tool_calls
            # 【优化 v2】注入干预模式，让 LLM 根据模式生成不同风格的回复
            messages = await prompt.aformat_messages(
                format_instructions=parser.get_format_instructions(),
                emotion_state=emotion_state,
                intensity=f"{intensity:.2f}",
                cognitive_distortions=cognitive_distortions_str,
                occ_vector=occ_str,
                conversation_history=conversation_history,
                personal_memories=memories_str,
                knowledge_cards=knowledge_cards_str,
                system_health_facts=system_health_facts,
                intervention_mode=intervention_mode,
            )

            first_response = await client_with_tools.ainvoke(messages)
            raw_text = first_response.content

            # 调试：打印完整的响应对象
            logger.debug(
                f"[generate_reply] DeepSeek 响应 | type={type(first_response).__name__} | "
                f"content={repr(raw_text[:200] if raw_text else '')} | "
                f"content_length={len(raw_text) if raw_text else 0} | "
                f"tool_calls={getattr(first_response, 'tool_calls', None)} | "
                f"additional_kwargs={getattr(first_response, 'additional_kwargs', {})}"
            )

            # DeepSeek 有时会静默返回空字符串（非异常，需要单独检测并重试）
            # 但如果同时返回了 tool_calls，说明 LLM 正在使用工具，应该继续处理而不重试
            tool_calls = getattr(first_response, "tool_calls", None) or []
            if not raw_text or not raw_text.strip():
                if tool_calls:
                    # 有 tool_calls 但没有文本内容，这是正常行为（LLM 在使用工具）
                    # 不重试，直接退出循环，继续执行后面的工具处理逻辑
                    logger.info(
                        f"[generate_reply] DeepSeek 返回 tool_calls ({len(tool_calls)} 个)，跳过重试"
                    )
                    break  # 关键修复：退出重试循环，继续处理工具
                else:
                    # 既没有文本也没有工具调用，视为异常重试
                    logger.warning(
                        f"[generate_reply] DeepSeek 返回空内容 (attempt={attempt + 1}/{MAX_RETRIES})"
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue
            else:
                break  # 有正常文本内容，退出重试循环

        except Exception as e:
            last_error = e
            logger.warning(
                f"[generate_reply] DeepSeek 调用异常 (attempt={attempt + 1}/{MAX_RETRIES}): {e}"
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
            continue

    else:
        # 所有重试都失败
        logger.error(f"[generate_reply] DeepSeek API 重试 {MAX_RETRIES} 次全部失败: {last_error}")
        raw_text = ""

    # 获取 tool_calls（可能在重试循环中被检测过）
    final_tool_calls = getattr(first_response, "tool_calls", None) or []

    # 如果既没有文本也没有工具调用，使用兜底回复
    if not raw_text and not final_tool_calls:
        logger.warning("[generate_reply] DeepSeek 无输出，使用兜底回复")
        reply_text = "我在这里陪着你，想说什么都可以告诉我。"
        strategy = None
    else:
        # 有文本或工具调用，交给解析器处理
        try:
            # 检查是否触发了 Tool Calling
            tool_calls = final_tool_calls
            reply_text = ""
            strategy = None

            if tool_calls:
                logger.info(f"[generate_reply] 检测到 Tool Calling: {len(tool_calls)} 个工具调用")
                for tc in tool_calls:
                    # 兼容 OpenAI SDK 两种 tool_call 格式：
                    #   格式A: tc = {"name": "...", "arguments": "..."}  (新版 dict)
                    #   格式B: tc = {"function": {"name": "...", "arguments": "..."}} (旧版)
                    tool_call_dict = tc if isinstance(tc, dict) else {"function": {"name": tc.name, "arguments": tc.arguments}}
                    tool_name = tool_call_dict.get("name") or tool_call_dict.get("function", {}).get("name")
                    logger.info(f"[generate_reply] 执行工具: {tool_name}")

                    if tool_name == "record_mood_diary":
                        try:
                            # 支持多种参数键格式：args (LangChain), arguments (OpenAI), function.args/arguments
                            raw_args = (
                                tool_call_dict.get("args")
                                or tool_call_dict.get("arguments")
                                or tool_call_dict.get("function", {}).get("args")
                                or tool_call_dict.get("function", {}).get("arguments")
                                or "{}"
                            )
                            args_dict = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                        except (json.JSONDecodeError, TypeError) as je:
                            logger.warning(f"[generate_reply] 工具参数解析失败: {je}")
                            args_dict = {}

                        # 检查必填参数是否存在，避免 Pydantic 验证失败
                        required_fields = ["event_description", "emotion_type", "intensity", "ai_advice"]
                        missing_fields = [f for f in required_fields if not args_dict.get(f)]
                        if missing_fields:
                            logger.warning(
                                f"[generate_reply] record_mood_diary 缺少必填参数: {missing_fields}，跳过 Notion 写入"
                            )
                            # 缺少参数时，raw_text 可能为空，尝试从 additional_kwargs 中获取原始 arguments
                            # 作为兜底，使用参数构建简单回复
                            if not raw_text:
                                fallback_reply = f"我理解你现在感到{args_dict.get('emotion_type', '复杂')}。"
                                logger.info(f"[generate_reply] 使用兜底回复: {fallback_reply}")
                                raw_text = fallback_reply
                        else:
                            try:
                                tool_result_str = record_mood_diary.invoke(args_dict)
                                tool_result = json.loads(tool_result_str)

                                logger.info(
                                    f"[generate_reply] Notion 写入结果: success={tool_result.get('success')}, "
                                    f"url={tool_result.get('page_url', '')[:60]}"
                                )

                                # 兼容多种 tool_call_id 格式
                                tc_id = (
                                    tool_call_dict.get("id")
                                    or tool_call_dict.get("tool_call_id")
                                    or tool_call_dict.get("function", {}).get("id")
                                    or ""
                                )

                                # 将工具调用结果追加到消息历史，供 LLM 生成最终回复
                                tool_msg = ToolMessage(
                                    content=tool_result_str,
                                    tool_call_id=tc_id,
                                )
                                messages.append(first_response)  # AI 的 tool_call 消息
                                messages.append(tool_msg)        # 工具执行结果

                                # 第二轮调用：LLM 读取工具结果，生成包含页面链接的回复
                                second_response = await client_with_tools.ainvoke(messages)
                                raw_text = second_response.content

                                # 从工具结果中提取 page_url，附加到回复末尾
                                page_url = tool_result.get("page_url", "")
                                if page_url and raw_text:
                                    raw_text = raw_text.strip() + f"\n\n📝 已帮你记录到 Notion：{page_url}"
                                elif page_url and not raw_text:
                                    # 第二轮调用返回空，但工具执行成功，生成兜底回复
                                    raw_text = f"我理解你现在感到{args_dict.get('emotion_type', '复杂')}。有什么事想和我聊聊吗？\n\n📝 已帮你记录到 Notion：{page_url}"
                            except Exception as tool_err:
                                logger.warning(f"[generate_reply] Notion 写入工具执行失败: {tool_err}，跳过")
                                # 降级：构建基于参数的基本回复
                                raw_text = f"我理解你现在感到{args_dict.get('emotion_type', '复杂')}。有什么事想和我聊聊吗？"
            else:
                logger.debug("[generate_reply] 未触发 Tool Calling，直接生成文本回复")

            llm_output = _parse_llm_output(parser, raw_text)
            reply_text = llm_output.reply
            llm_strategy = llm_output.recommended_strategy

            # 任务1: recommended_strategy 优先从 RAG 检索结果提取（保证与实际使用的卡片一致）
            # LLM 自由输出的 strategy 仅作为降级兜底
            strategy = _extract_strategy_from_retrieved(retrieved_cards_with_meta, llm_strategy)

            logger.info(f"[generate_reply] 回复生成成功: {reply_text[:30]}... recommended_strategy={strategy}")

        except Exception as e:
            logger.error(f"[generate_reply] 解析/LLM 调用出错: {e}")
            reply_text = "我在这里陪着你，想说什么都可以告诉我。"
            strategy = None

        # 【性能优化】立即触发 TTS 语音合成（与 SSE 返回并行执行）
        if reply_text and reply_text.strip():
            await _trigger_tts_async(reply_text)

    # 更新干预决策中的 reply 字段
    updated_decision = InterventionDecision(
        needed=decision.needed,
        urgency=decision.urgency,
        suggested_action=decision.suggested_action,
        ui_instruction=decision.ui_instruction,
        recommended_strategy=strategy,
        reply=reply_text,
        intervention_score=decision.intervention_score,
        interrupt_cost=decision.interrupt_cost,
        trend=decision.trend,
    )

    return {
        "intervention_decision": updated_decision,
    }


# ==============================================================================
# 辅助函数
# ==============================================================================

def _extract_strategy_from_retrieved(
    retrieved_cards_with_meta: list[dict],
    llm_strategy: str | None,
) -> str | None:
    """
    任务1: recommended_strategy 提取逻辑。

    优先级：
    1. 从 RAG 检索结果（含 metadata）提取 TOP-1 卡片的 goal 字段
       → 保证 recommended_strategy 与实际使用的心理学技术一致
    2. LLM 自由输出的 strategy → 作为降级兜底
    3. 完全无结果 → 返回 None

    Args:
        retrieved_cards_with_meta: retrieve_knowledge_cards 返回的完整结果（list[dict]）
        llm_strategy: LLM 自由生成的 strategy 名称
    """
    if retrieved_cards_with_meta:
        top_card = retrieved_cards_with_meta[0]
        goal = top_card.get("meta", {}).get("goal", "")
        title = top_card.get("meta", {}).get("title", "")
        if goal:
            # goal 优先，goal 为空时用 title 兜底
            return goal
        if title:
            return title

    return llm_strategy


async def _trigger_tts_async(text: str) -> None:
    """
    【性能优化】异步触发 TTS 语音合成。
    使用 asyncio.create_task 在当前事件循环中并行执行。
    捕获异常并记录，避免未处理的错误。
    """
    from src.utils.tts import speak_text

    try:
        # 使用 create_task 让 TTS 与 LangGraph 并行执行
        # 注意：这不等待 TTS 完成，TTS 在后台独立运行
        task = asyncio.create_task(
            speak_text(text),
            name=f"tts_task_{text[:10]}"
        )

        # 添加 done_callback 记录完成状态
        def _on_tts_done(t: asyncio.Task):
            try:
                result = t.result()
                if result:
                    logger.info(f"[generate_reply] TTS 完成 ✓: {text[:15]}...")
                else:
                    logger.warning(f"[generate_reply] TTS 失败: {text[:15]}...")
            except asyncio.CancelledError:
                logger.info(f"[generate_reply] TTS 被取消: {text[:15]}...")
            except Exception as e:
                logger.error(f"[generate_reply] TTS 异常: {e}")

        task.add_done_callback(_on_tts_done)
        logger.info(f"[generate_reply] TTS 任务已创建: {text[:15]}...")

    except Exception as e:
        logger.warning(f"[generate_reply] TTS 任务创建失败: {e}")


def _get_conversation_history(state: AgentState) -> str:
    """
    从 AgentState.conversation_history 中提取对话，格式化为自然语言。
    用于注入 LLM Prompt，提供上下文。

    修复：使用 conversation_history 而非 messages，避免与 LangGraph MessagesState 冲突。
    """
    # 优先使用 conversation_history（Java 传入或 Redis 读取）
    history = state.get("conversation_history", [])
    if not history:
        # 兜底：尝试从 messages 读取（兼容旧代码）
        history = state.get("messages", [])
    if not history:
        return ""

    # 取最近 10 条消息构建对话历史
    recent = history[-10:]
    lines = []
    for msg in recent:
        # 字典格式
        if isinstance(msg, dict):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
        else:
            continue

        if role in ("human", "user"):
            lines.append(f"用户：{content[:200]}")
        elif role in ("ai", "assistant", "tool"):
            lines.append(f"婉情：{content[:200]}")

    return "\n".join(lines) if lines else ""


def _build_occ_string(emotion) -> str:
    """
    将 EmotionVector.evidence.occ 字段格式化为可读字符串，
    注入 generate_reply 的 Prompt（供 LLM 参考情感归因上下文）。
    """
    if emotion is None:
        return "（无 OCC 归因数据）"

    occ = emotion.evidence.get("occ", {}) if isinstance(emotion.evidence, dict) else {}
    if not occ:
        return "（无 OCC 归因数据）"

    labels = {
        "joy": "喜悦",
        "sadness": "悲伤",
        "anger": "愤怒",
        "fear": "恐惧",
        "disgust": "厌恶",
        "surprise": "惊讶",
        "well_grounding": "踏实感",
        "anticipation": "期待感",
    }

    parts = []
    for key, label in labels.items():
        val = occ.get(key, 0.0)
        bar = "█" * int(val * 5) + "░" * (5 - int(val * 5))
        parts.append(f"  {label}: [{bar}] {val:.2f}")

    return "\n".join(parts) if parts else "（无 OCC 归因数据）"
