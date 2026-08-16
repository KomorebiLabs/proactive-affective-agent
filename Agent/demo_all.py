"""
婉情AI - 一键演示脚本
=====================
无需 Redis / 摄像头 / 麦克风，通过 Mock 数据一键演示婉情AI的5大核心功能。

核心设计原则：
  - DeepSeek 调用：真实调用 LLM API，展示真实的 OCC 向量生成过程
  - 干预决策：调用真实的 decide_intervention_node，复用原有五因子逻辑
  - RAG 检索：调用真实的 retrieve_knowledge_cards，走真实向量检索
  - Notion 日记：调用真实的 record_mood_diary.invoke，走 Mock Notion 客户端
  - 三层记忆：调用真实 append_conversation_turn，走 Mock Redis

使用方式：
    cd Agent
    python demo_all.py

依赖：
    pip install -r requirements.txt
    DEEPSEEK_API_KEY 已配置于 .env
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from time import sleep

# ─────────────────────────────────────────────────────────────────────────────
# 初始化：设置编码 + ��载 .env
# ─────────────────────────────────────────────────────────────────────────────
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

_AGENT_ROOT = Path(__file__).parent
sys.path.insert(0, str(_AGENT_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=_AGENT_ROOT / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# Mock 层（必须在业务代码导入之前应用）
# ─────────────────────────────────────────────────────────────────────────────
from demo.mocks import apply_mocks
apply_mocks()

# ─────────────────────────────────────────────────────────────────────────────
# 导入 Mock/工具/展示模块
# ─────────────────────────────────────────────────────────────────────────────
from demo.scenarios import (
    ALL_SCENARIOS,
    SCENARIO_ANXIETY,
    SCENARIO_ANGER,
    SCENARIO_DISTRACTED,
    SCENARIO_HAPPY,
    SCENARIO_SAD,
    DemoScenario,
)
from demo.display import (
    print_banner,
    print_footer,
    print_scenario_header,
    print_occ_vector,
    print_cognitive_distortions,
    print_au_features,
    print_intervention_decision,
    print_rag_cards,
    print_notion_diary,
    print_memory_flow,
    print_progress,
    print_done,
    _step,
    _info,
    _section,
    _color,
    _bold,
    _gray,
    C,
)

# ─────────────────────────────────────────────────────────────────────────────
# 导入业务节点（Mock 后才导入）
# ─────────────────────────────────────────────────────────────────────────────
from src.models.schemas import (
    EmotionVector,
    EmotionLabel,
    CognitiveDistortion,
    InterventionAction,
    InterventionUrgency,
    UIInstruction,
    InterventionDecision,
)
from src.agent.nodes.fuse_emotion import fuse_emotion_node
from src.agent.nodes.decide_intervention import decide_intervention_node
from src.rag.retriever import sync_knowledge_base, retrieve_knowledge_cards
from src.memory.short_term import append_conversation_turn
from src.agent.tools.notion_tool import record_mood_diary


# ==============================================================================
# 辅助：构造 AgentState（fuse_emotion_node 需要的完整 state）
# ==============================================================================

def build_agent_state(scenario: DemoScenario):
    """
    根据场景构造一个完整的 AgentState，供 fuse_emotion_node 使用。
    数据来自 scenario 的 perception（Mock 感知数据）。
    """
    from src.agent.state import AgentState

    perception = scenario.build_perception()
    state = AgentState(
        session_id=f"demo-{scenario.id}",
        user_id="demo-user",
        user_input=scenario.user_input,
        latest_perception=perception,
        qwen_analysis=None,
        is_focused_mode=scenario.is_focused_mode,
        emotion_history=[],
        conversation_history=scenario.conversation_history,
        system_health={},
    )
    return state


# ==============================================================================
# 核心演示：DeepSeek 真实调用，OCC 向量真实输出
# ==============================================================================

async def demo_multimodal_fusion(scenario: DemoScenario) -> tuple[EmotionVector, dict]:
    """
    功能一：多模态情感融合——真实调用 DeepSeek。
    返回 (EmotionVector, raw_llm_text) 供后续流程使用。
    """
    _step("多模态情感融合")
    _info("用户输入", f"「{scenario.user_input}」" if scenario.user_input else "（感知数据驱动，无文字输入）")

    # 展示原始感知数据
    if scenario.perception:
        print_au_features(scenario.perception.au, scenario.perception.audio)
    else:
        print(f"\n  {_gray('（无感知数据）')}")

    # 真实调用 fuse_emotion_node（内部调用 DeepSeek）
    print_progress("调用 DeepSeek 进行情感融合分析")
    state = build_agent_state(scenario)
    result = await fuse_emotion_node(state)
    print_done()

    emotion_vector: EmotionVector = result["current_emotion"]
    return emotion_vector


# ==============================================================================
# 功能二：主动关怀决策（调用真实的 decide_intervention_node）
# ==============================================================================

async def demo_intervention_decision(scenario: DemoScenario, emotion_vector: EmotionVector) -> InterventionDecision:
    """
    功能二：主动关怀决策——调用真实的 decide_intervention_node。
    """
    _step("主动关怀决策")

    from src.agent.state import AgentState

    state = AgentState(
        session_id=f"demo-{scenario.id}",
        user_id="demo-user",
        user_input=scenario.user_input,
        latest_perception=scenario.build_perception(),
        current_emotion=emotion_vector,
        emotion_history=[],
        system_health={},
    )

    print_progress("计算五因子加权评分")
    result = await decide_intervention_node(state)
    print_done()

    intervention: InterventionDecision = result["intervention_decision"]

    # 打印五因子详情（从配置中重建 FactorDetail 列表）
    from config import intervention_config
    cfg = intervention_config

    intensity = emotion_vector.intensity
    from config import emotion_config
    emotion_priority = emotion_config.EMOTION_PRIORITY.get(
        emotion_vector.primary_emotion.value, 0.0
    )
    focus = scenario.build_perception().focus_level
    arousal = emotion_vector.arousal
    from src.emotion.perception import compute_emotion_trend
    trend_val = compute_emotion_trend([])
    trend_factor = {"RISING": 0.2, "FALLING": -0.1, "STABLE": 0.0}.get(
        trend_val.value, 0.0
    )
    confidence = emotion_vector.confidence

    interrupt_cost = focus * (1.0 - arousal)
    factor_details = [
        ("情绪强度",       cfg.WEIGHT_INTENSITY,          cfg.WEIGHT_INTENSITY * intensity),
        ("情感优先级",     cfg.WEIGHT_EMOTION_PRIORITY,   cfg.WEIGHT_EMOTION_PRIORITY * emotion_priority),
        ("打扰成本",      -cfg.WEIGHT_INTERRUPT_COST,     -cfg.WEIGHT_INTERRUPT_COST * interrupt_cost),
        ("历史趋势",      cfg.WEIGHT_TREND,              cfg.WEIGHT_TREND * trend_factor),
        ("LLM置信度",     cfg.WEIGHT_CONFIDENCE,         cfg.WEIGHT_CONFIDENCE * confidence),
    ]

    print_intervention_decision(
        _InterventionResultProxy(
            action=intervention.suggested_action,
            total_score=intervention.intervention_score,
            factor_details=factor_details,
            reasoning=(
                f"综合评分 {intervention.intervention_score:.2f} "
                f"→ {intervention.suggested_action.value.upper()}（"
                f"{intervention.suggested_action.value}"
                f"）"
            ),
        )
    )
    return intervention


# ==============================================================================
# 功能三：RAG 知识库检索（真实调用 retrieve_knowledge_cards）
# ==============================================================================

async def demo_rag_retrieval(scenario: DemoScenario, emotion_vector: EmotionVector) -> tuple[list[str], list[dict]]:
    """
    功能三：RAG 知识库检索——调用真实的 retrieve_knowledge_cards。
    """
    _step("RAG 知识库检索")

    print_progress("同步知识库到 ChromaDB（首次运行下载模型）")
    sync_knowledge_base()
    print_done()

    print_progress("构造向量检索 query")
    top_k = 3
    sleep(0.3)
    print_done()

    print_progress("向量相似度检索")
    cards, meta = await retrieve_knowledge_cards(
        emotion_vector=emotion_vector,
        user_input=scenario.user_input,
        top_k=top_k,
    )
    print_done()

    # 格式化卡片
    formatted = []
    for i, (card_text, card_result) in enumerate(zip(cards, meta)):
        card_meta = card_result.get("meta", {})
        similarity = card_result.get("similarity", 0.0)
        emotions_raw = card_meta.get("emotions", "")
        distortions_raw = card_meta.get("cognitive_distortions", "")
        goal = card_meta.get("goal", "")
        card_id = card_meta.get("card_id", f"CBT-TECH-{i:03d}")
        title = card_meta.get("title", "")
        if not title:
            for line in card_text.split("\n"):
                if line.startswith("【参考心理学方案 - "):
                    title = line.split(" - ", 1)[1].split("】")[0]
                    break

        formatted.append({
            "card_id": card_id,
            "title": title,
            "emotions": emotions_raw,
            "distortions": distortions_raw,
            "goal": goal,
            "similarity": f"{similarity:.2f}",
            "excerpt": card_text[:500],
        })

    print_rag_cards(formatted)
    return cards, meta


# ==============================================================================
# 功能四：Notion 情绪日记（真实调用 record_mood_diary）
# ==============================================================================

async def demo_notion_diary(scenario: DemoScenario, emotion_vector: EmotionVector) -> None:
    """
    功能四：Notion 情绪日记——真实调用 record_mood_diary.invoke，走 Mock Notion 客户端。
    """
    _step("Notion 情绪日记")

    if emotion_vector.intensity < 0.6:
        print_notion_diary(False)
        return

    print_progress("DeepSeek 判断情绪强度 >= 0.6，触发 record_mood_diary")
    sleep(0.3)
    print_done()

    print_progress("调用 record_mood_diary 工具")
    args = {
        "event_description": (
            f"用户在对话中表达了{scenario.primary_emotion.value}情绪："
            f"{scenario.user_input[:60]}"
        ),
        "emotion_type": scenario.primary_emotion.value,
        "intensity": float(emotion_vector.intensity),
        "ai_advice": "无论结果如何，你已经付出了努力，这本身就值得肯定。尝试把注意力放在当下可以控制的事情上，而不是无法预测的未来。",
        "body_sensation": "有些紧张，胃部有紧缩感",
        "coping_strategy": "深呼吸, 冥想",
        "custom_title": f"婉情日记 - {scenario.primary_emotion.value}情绪记录",
    }
    sleep(0.3)

    print_progress("调用 Notion API（Mock）")
    try:
        result_str = await asyncio.to_thread(record_mood_diary.invoke, args)
        result = json.loads(result_str)
        page_url = result.get("page_url", "https://notion.so/demo-mock")
        print_done()
        print(f"\n  {_color('✓', C.DARK_GREEN)} {_color('情绪日记写入成功！', C.DARK_GREEN + C.BOLD)}")
        print(f"  页面URL: {_color(page_url, C.BLUE)}")
        print(f"  情绪类型: {scenario.primary_emotion.value}")
        print(f"  情绪强度: {emotion_vector.intensity:.2f}")
    except Exception as e:
        print_done()
        print(f"  {_color('✗', C.DARK_RED)} Notion 写入失败: {e}")


# ==============================================================================
# 功能五：三层记忆流转（真实调用 Redis / MySQL Mock / ChromaDB Mock）
# ==============================================================================

async def demo_memory_flow(scenario: DemoScenario, emotion_vector: EmotionVector) -> None:
    """
    功能五：三层记忆流转——调用真实 append_conversation_turn，走 Mock Redis。
    """
    _step("三层记忆流转")
    session_id = f"demo-{scenario.id}"
    user_id = "demo-user"

    # 短期记忆（真实调用 append_conversation_turn，走 Mock Redis）
    print_progress("写入短期记忆（Redis Mock）")
    await append_conversation_turn(session_id, "user", scenario.user_input)
    await append_conversation_turn(
        session_id, "ai",
        f"我注意到你表达了{scenario.primary_emotion.value}的情绪..."
    )
    print_done()

    # 中期记忆（Mock 打印 session_log 结构）
    print_progress("写入中期记忆（MySQL Mock → Java Callback）")
    print_done()
    print(f"  {_color('SessionLog 已写入：', C.GRAY)}")
    print(f"    session_id={session_id}")
    print(f"    emotion_vector={scenario.primary_emotion.value} {emotion_vector.intensity:.2f}")
    print(f"    intervention={scenario.intervention.action.value}")

    # 长期记忆（真实调用 store_long_term_memory，走 Mock ChromaDB）
    print_progress("写入长期记忆（ChromaDB Mock → 向量化存储）")
    from src.memory.long_term import store_long_term_memory
    from src.models.schemas import MemoryType
    emotion_text = (
        f"用户表达了{scenario.primary_emotion.value}（强度={emotion_vector.intensity:.2f}），"
        f"认知扭曲={', '.join(d.value for d in scenario.cognitive_distortions) or '无'}，"
        f"系统决策：{scenario.intervention.action.value}"
    )
    await store_long_term_memory(
        user_id=user_id,
        content=emotion_text,
        memory_type=MemoryType.CONVERSATION_SUMMARY,
        metadata={"session_id": session_id},
    )
    print_done()

    print_memory_flow(scenario.id, scenario.conversation_history)


# ==============================================================================
# 辅助：干预决策详情 Proxy（用于 print_intervention_decision 的兼容接口）
# ==============================================================================

@dataclass
class _FactorDetailProxy:
    name: str
    weight: float
    contribution: float


@dataclass
class _InterventionResultProxy:
    """兼容 print_intervention_decision 接口的 Proxy"""
    action: InterventionAction
    total_score: float
    factor_details: list[tuple]
    reasoning: str


# ==============================================================================
# 主演示流程
# ==============================================================================

async def run_demo_for_scenario(scenario: DemoScenario) -> None:
    """运行单个场景的完整演示（真实调用所有节点）"""

    print_scenario_header(scenario)

    # ── 1. DeepSeek 真实调用 ──────────────────────────────────────────────
    _section("功能一：多模态情感融合")
    emotion_vector = await demo_multimodal_fusion(scenario)

    # 展示 OCC 八维向量
    # evidence['occ'] 用小写键 {'joy', 'sadness', ...}，需映射为 print_occ_vector 所需的大写键
    raw_occ = (emotion_vector.evidence or {}).get("occ", {})
    occ_dict = {
        f"occ_{k}": v for k, v in raw_occ.items()
    } if raw_occ else {}
    print_occ_vector(occ_dict, scenario.build_perception())
    print_cognitive_distortions(emotion_vector.cognitive_distortions)

    # 展示 DeepSeek 推理过程
    reasoning = emotion_vector.reasoning
    print(f"\n  {_bold('DeepSeek 推理过程：')}")
    if reasoning:
        for line in reasoning.split("。")[:5]:
            line = line.strip()
            if line:
                print(f"    {line}。")
    else:
        print(f"    {_gray('（推理过程为空）')}")

    # ── 2. 真实干预决策 ────────────────────────────────────────────────────
    _section("功能二：主动关怀决策")
    intervention = await demo_intervention_decision(scenario, emotion_vector)

    # ── 3. RAG 检索 ──────────────────────────────────────────────────────
    if intervention.suggested_action != InterventionAction.SILENT:
        _section("功能三：RAG 知识库检索")
        await demo_rag_retrieval(scenario, emotion_vector)
    else:
        _section("功能三：RAG 知识库检索（跳过）")
        print(f"\n  {_gray('SILENT 路径：无干预意图，跳过 RAG 检索')}")

    # ── 4. Notion 日记 ───────────────────────────────────────────────────
    _section("功能四：Notion 情绪日记")
    await demo_notion_diary(scenario, emotion_vector)

    # ── 5. 三层记忆 ──────────────────────────────────────────────────────
    _section("功能五：三层记忆流转")
    await demo_memory_flow(scenario, emotion_vector)


async def main() -> None:
    """主入口"""
    print_banner()

    # 前置检查
    print(f"  {_color('▶', C.DARK_GREEN)} 检查 DeepSeek API Key...")
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        print(f"  {_color('✗', C.RED)} DEEPSEEK_API_KEY 未配置，请检查 Agent/.env")
        return
    print(f"  {_color('✓', C.DARK_GREEN)} API Key: {api_key[:8]}...{api_key[-4:]}")
    print(f"  {_color('▶', C.DARK_GREEN)} Mock 环境：Redis / ChromaDB / Notion / MySQL 全部就绪")

    print(f"\n  {'=' * 66}")
    print(f"  {'即将演示 5 个核心功能（5 个真实调用链）：'}")
    print(f"  {'=' * 66}")
    scenario_names = [
        f"  ① {SCENARIO_ANXIETY.title}  → DeepSeek OCC + 5因子 + RAG + Notion",
        f"  ② {SCENARIO_ANGER.title}    → 负面校准 + SILENT",
        f"  ③ {SCENARIO_DISTRACTED.title} → 走神模式 + SILENT",
        f"  ④ {SCENARIO_HAPPY.title}    → 打扰成本高 + SILENT",
        f"  ⑤ {SCENARIO_SAD.title}  → SUBTLE + 三层记忆",
    ]
    for name in scenario_names:
        print(f"    {_color(name, C.GRAY)}")

    print(f"\n  {_color('▶', C.DARK_YELLOW)} 准备就绪，5秒后开始演示（Ctrl+C 可退出）")
    try:
        for i in range(5, 0, -1):
            print(f"    {str(i)}...", end="\r")
            sleep(1)
    except KeyboardInterrupt:
        print(f"\n  {_color('已退出', C.RED)}")
        return

    # 逐场景演示
    for i, scenario in enumerate(ALL_SCENARIOS, 1):
        try:
            await run_demo_for_scenario(scenario)
            if i < len(ALL_SCENARIOS):
                print(f"\n  {_color('─' * 60, C.GRAY)}")
                print(f"  {_color('▶ 下一场景准备中...', C.DARK_YELLOW)}")
                sleep(1)
        except KeyboardInterrupt:
            print(f"\n  {_color('已退出', C.RED)}")
            break
        except Exception as e:
            print(f"\n  {_color('✗ 场景出错:', C.RED)} {e}")
            import traceback
            traceback.print_exc()

    print_footer()


if __name__ == "__main__":
    asyncio.run(main())
