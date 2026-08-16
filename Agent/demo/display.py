"""
婉情AI - Demo 辅助展示函数
==========================
提供格式化的终端 UI 输出，包括：
- OCC 八维向量条形图
- 五因子评分可视化
- 知识卡片格式化
- ASCII 装饰边框
"""

from __future__ import annotations

import sys
import time

# 强制 UTF-8 编码（Windows GBK 终端兼容）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


# ==============================================================================
# 安全打印：处理 Windows GBK 编码问题
# ==============================================================================

def _safe_print(*args, **kwargs):
    """带 ANSI 颜色支持的 print，自动降级 GBK 不兼容字符"""
    def _make_safe(obj):
        if isinstance(obj, str):
            try:
                obj.encode(sys.stdout.encoding or 'utf-8')
                return obj
            except UnicodeEncodeError:
                return obj.encode('ascii', 'replace').decode('ascii')
        return str(obj)

    args = tuple(_make_safe(a) for a in args)
    safe_kwargs = {k: _make_safe(v) if isinstance(v, str) else v for k, v in kwargs.items()}
    print(*args, **safe_kwargs)


# ==============================================================================
# ANSI 颜色码
# ==============================================================================

C = type("ColorCodes", (), {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "MAGENTA": "\033[95m",
    "CYAN": "\033[96m",
    "WHITE": "\033[97m",
    "GRAY": "\033[90m",
    "DARK_RED": "\033[31m",
    "DARK_GREEN": "\033[32m",
    "DARK_YELLOW": "\033[33m",
})()


def _color(text: str, color: str) -> str:
    """为文本添加颜色（在非 TTY 环境下自动降级）"""
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


def _bold(text: str) -> str:
    return _color(text, C.BOLD)


def _gray(text: str) -> str:
    return _color(text, C.GRAY)


def _section(title: str, subtitle: str = "") -> None:
    """打印带颜色的分节标题"""
    bar = _color("-" * 64, C.DARK_GREEN)
    title_str = _color(f" 【{title}】 ", C.CYAN + C.BOLD)
    _safe_print()
    _safe_print(bar)
    _safe_print(f"{title_str}{_bold(subtitle) if subtitle else ''}")
    _safe_print(bar)


def _info(label: str, value: str, indent: int = 2) -> None:
    """打印一行信息"""
    prefix = " " * indent
    _safe_print(f"{prefix}{_color('>', C.DARK_GREEN)} {_color(label + ':', C.YELLOW)} {value}")


def _step(label: str) -> None:
    """打印步骤标题"""
    _safe_print()
    _safe_print(f"  {_color(f'[{label}]', C.CYAN + C.BOLD)}")


# ==============================================================================
# Banner / Footer
# ==============================================================================

def print_banner() -> None:
    """打印演示横幅"""
    banner = f"""
{_color('+' + '=' * 66 + '+', C.CYAN)}
{_color('|', C.CYAN)}{_bold(' ' * 18 + '婉情AI - 核心功能演示')}{' ' * 24}{_color('|', C.CYAN)}
{_color('|', C.CYAN)}{' ' * 12 + '多模态感知 · 主动关怀 · RAG知识库 · 情绪日记 · 三层记忆'}{' ' * 5}{_color('|', C.CYAN)}
{_color('+' + '=' * 66 + '+', C.CYAN)}
"""
    _safe_print(banner)


def print_footer() -> None:
    """打印结尾横幅"""
    _safe_print()
    _safe_print(f"{_color('+' + '=' * 66 + '+', C.CYAN)}")
    _safe_print(f"{_color('|', C.CYAN)}{_bold(' ' * 16 + '演示完成！所有核心功能正常运行。')}{' ' * 20}{_color('|', C.CYAN)}")
    _safe_print(f"{_color('|', C.CYAN)}{' ' * 16 + 'DeepSeek API - Redis Mock - ChromaDB Mock'}{' ' * 16}{_color('|', C.CYAN)}")
    _safe_print(f"{_color('+' + '=' * 66 + '+', C.CYAN)}")
    _safe_print()


def print_scenario_header(scenario) -> None:
    """打印场景标题"""
    _safe_print()
    _safe_print(f"{_color('*' * 32, C.DARK_YELLOW)}")
    _safe_print(f"  {_bold(scenario.title)}")
    _safe_print(f"  {_gray(scenario.description)}")
    _safe_print(f"{_color('*' * 32, C.DARK_YELLOW)}")


# ==============================================================================
# OCC 八维向量
# ==============================================================================

def print_occ_vector(occ, perception=None) -> None:
    """
    打印 OCC 八维情感向量（ASCII 条形图）。
    支持 dict 和带属性的 OCC 对象。
    如果没有 OCC 数据（走神模式快速规则），打印友好提示。
    """
    # 标准化为 dict
    if isinstance(occ, dict):
        occ_dict = occ
    else:
        occ_dict = {
            "occ_joy": getattr(occ, "occ_joy", None),
            "occ_sadness": getattr(occ, "occ_sadness", None),
            "occ_anger": getattr(occ, "occ_anger", None),
            "occ_fear": getattr(occ, "occ_fear", None),
            "occ_disgust": getattr(occ, "occ_disgust", None),
            "occ_surprise": getattr(occ, "occ_surprise", None),
            "occ_well_grounding": getattr(occ, "occ_well_grounding", None),
            "occ_anticipation": getattr(occ, "occ_anticipation", None),
        }

    # 判断是否有有效 OCC 数据（走神模式快速规则路径没有 OCC）
    has_occ = any(v is not None and v > 0.0 for v in occ_dict.values())

    if not has_occ:
        _safe_print()
        _safe_print(f"  {_bold('OCC 八维情感向量')}（{_gray('走神模式 - 快速规则兜底 - 无 OCC 输出')}）")
        _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")
        _safe_print(f"  {_color('[!] 跳过 DeepSeek LLM 调用，仅基于 AU 阈值规则判断', C.DARK_YELLOW)}")
        _safe_print(f"  {_gray('  （专注模式才会调用 DeepSeek 生成完整 OCC 八维向量）')}")
        _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")
        return

    _safe_print()
    _safe_print(f"  {_bold('OCC 八维情感向量')}（DeepSeek LLM 综合推理结果）")
    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")

    dims = [
        ("occ_joy", "喜悦", C.GREEN),
        ("occ_sadness", "悲伤", C.BLUE),
        ("occ_anger", "愤怒", C.RED),
        ("occ_fear", "恐惧", C.MAGENTA),
        ("occ_disgust", "厌恶", C.DARK_YELLOW),
        ("occ_surprise", "惊讶", C.CYAN),
        ("occ_well_grounding", "踏实感", C.DARK_GREEN),
        ("occ_anticipation", "期待/焦虑", C.YELLOW),
    ]

    all_vals = [occ_dict.get(f, 0.0) or 0.0 for f, _, _ in dims]
    max_val = max(all_vals) if all_vals else 0.0

    for field, label, color in dims:
        value = occ_dict.get(field, 0.0) or 0.0
        bar_len = int(value * 28)
        bar = _color("#" * bar_len, color)
        empty = _color("-" * (28 - bar_len), C.GRAY)
        score = f"{value:.2f}"
        # 高亮最大值
        if value == max_val and value > 0.1:
            score = _color(score, C.GREEN + C.BOLD)
            bar = _color("#" * bar_len, C.GREEN + C.BOLD)
        _safe_print(f"  {label:12s} |{bar}{empty} | {score}")

    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")


def print_cognitive_distortions(distortions: list) -> None:
    """打印认知扭曲识别结果"""
    if not distortions:
        return
    _safe_print()
    _safe_print(f"  {_bold('认知扭曲识别：')}")
    colors = [C.RED, C.MAGENTA, C.YELLOW]
    for i, d in enumerate(distortions):
        color = colors[i % len(colors)]
        _safe_print(f"    {_color('*', color)} {_color(d.value, color)}")


def print_au_features(au, audio, perception=None) -> None:
    """打印 AU 参数和音频特征"""
    _safe_print()
    _safe_print(f"  {_bold('多模态感知数据')}（摄像头 + 麦克风）")
    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")

    # AU 参数
    au_pairs = [
        ("AU4", "皱眉", au.AU4 if au else 0),
        ("AU12", "嘴角上扬", au.AU12 if au else 0),
        ("AU15", "嘴角下垂", au.AU15 if au else 0),
        ("AU1", "内眉上扬", au.AU1 if au else 0),
        ("AU6", "颧骨上提", au.AU6 if au else 0),
    ]
    for field, name, val in au_pairs:
        bar_len = int(val * 20)
        bar = _color("#" * bar_len, C.DARK_YELLOW)
        empty = _color("-" * (20 - bar_len), C.GRAY)
        au_label = "0.00" if val < 0.01 else f"{val:.2f}"
        _safe_print(f"  {field}({name:4s}) |{bar}{empty} | {au_label}")

    # 音频特征
    if audio:
        _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")
        pitch = audio.pitch
        loud = audio.loudness
        speaking = "是" if audio.speaking else "否"
        if pitch > 200:
            pitch_desc = _color("↑ 音调升高（焦虑信号）", C.RED)
        elif pitch < 150:
            pitch_desc = _color("↓ 音调低沉（抑郁信号）", C.BLUE)
        else:
            pitch_desc = _color("正常", C.DARK_GREEN)
        _safe_print(f"  {'音调:':12s} {pitch:.1f} Hz  {pitch_desc}")
        _safe_print(f"  {'响度:':12s} {loud:.2f}  " + "#" * int(loud * 10) + "-" * int((1 - loud) * 10))
        _safe_print(f"  {'说话中:':12s} {speaking}")


# ==============================================================================
# 干预决策
# ==============================================================================

def print_intervention_decision(intervention) -> None:
    """
    打印五因子评分详情（支持 tuple 列表或带属性的对象）
    """
    _safe_print()
    _safe_print(f"  {_bold('五因子加权评分详情')}")
    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")

    action_value = getattr(intervention.action, "value", str(intervention.action))
    action_color = {
        "intervene": C.RED + C.BOLD,
        "subtle": C.YELLOW + C.BOLD,
        "silent": C.DARK_GREEN,
    }.get(action_value, C.WHITE)

    action_text = {
        "intervene": "INTERVENE（深度干预）",
        "subtle": "SUBTLE（微干预）",
        "silent": "SILENT（静默观察）",
    }.get(action_value, action_value)

    for factor in intervention.factor_details:
        # 支持 tuple ("名称", 权重, 贡献) 或带属性的对象
        if isinstance(factor, tuple):
            name, weight, contribution = factor
        else:
            name = getattr(factor, "name", "?")
            weight = getattr(factor, "weight", 0.0)
            contribution = getattr(factor, "contribution", 0.0)

        bar_len = int(abs(contribution) * 20)
        if contribution >= 0:
            bar = _color("#" * bar_len, C.DARK_GREEN)
            sign = _color("+", C.DARK_GREEN)
        else:
            bar = _color("#" * bar_len, C.DARK_RED)
            sign = _color("-", C.DARK_RED)

        weight_str = f"{weight:+.2f}"
        contrib_str = f"{abs(contribution):.2f}"
        _safe_print(f"  {name:12s} 权重={_color(weight_str, C.GRAY)}  |{bar}  贡献 {sign}{contrib_str}")

    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")
    total_score = getattr(intervention, "total_score", 0.0)
    score_str = f"{total_score:.2f}"
    if total_score >= 0.8:
        score_color = C.RED
    elif total_score >= 0.6:
        score_color = C.YELLOW
    else:
        score_color = C.DARK_GREEN
    _safe_print(f"  综合评分：{_color(score_str, score_color + C.BOLD)}  |  干预等级：{_color(action_text, action_color)}")
    reasoning = getattr(intervention, "reasoning", "")
    _safe_print(f"  {_gray('推理：')}{reasoning}")


# ==============================================================================
# RAG 卡片
# ==============================================================================

def print_rag_cards(cards: list[dict]) -> None:
    """打印 RAG 检索到的知识卡片"""
    if not cards:
        _safe_print()
        _safe_print(f"  {_gray('无匹配卡片（相似度均低于阈值）')}")
        return

    _safe_print()
    _safe_print(f"  {_bold(f'检索到 {len(cards)} 张心理学知识卡片')}（ChromaDB 向量检索）")
    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")

    for i, card in enumerate(cards, 1):
        sim = float(card.get("similarity", 0))
        sim_color = C.GREEN if sim >= 0.7 else C.YELLOW if sim >= 0.6 else C.GRAY
        sim_bar = _color("#" * int(sim * 20), sim_color)

        card_title = _color(card.get("title", ""), C.CYAN + C.BOLD)
        card_id = _color(f"[{card.get('card_id', '')}]", C.GRAY)

        _safe_print()
        _safe_print(f"  {_color(f'【卡片 {i}】', C.BOLD)} {card_title}  {card_id}")
        _safe_print(f"  匹配度: {sim_bar} {sim:.2f}")

        emotions = card.get("emotions", "")
        distortions = card.get("distortions", "")
        if emotions:
            _safe_print(f"  情绪: {_color(emotions, C.MAGENTA)}")
        if distortions:
            _safe_print(f"  认知扭曲: {_color(distortions, C.YELLOW)}")

        goal = card.get("goal", "")
        if goal:
            _safe_print(f"  目标: {goal}")

        excerpt = card.get("excerpt", "")
        if excerpt:
            lines = excerpt.split("\n")
            preview = "\n".join(lines[:6])
            _safe_print(f"  内容预览:\n  {preview}")


# ==============================================================================
# Notion 记忆
# ==============================================================================

def print_notion_diary(enabled: bool, emotion=None) -> None:
    """打印 Notion 情绪日记记录结果"""
    _safe_print()
    _safe_print(f"  {_bold('Notion 情绪日记')}")
    _safe_print(f"  {_color('-' * 58, C.DARK_GREEN)}")

    if enabled:
        _safe_print(f"  {_color('[OK]', C.DARK_GREEN)} {_color('情绪日记写入成功！', C.DARK_GREEN + C.BOLD)}")
        if emotion:
            emotion_label = getattr(emotion, "primary_emotion", "未知")
            intensity = getattr(emotion, "intensity", 0)
            _safe_print(f"  页面URL: {_color('https://notion.so/demo-mock-xxxxx', C.BLUE)}")
            _safe_print(f"  情绪类型: {emotion_label}")
            _safe_print(f"  情绪强度: {intensity:.2f}")
    else:
        _safe_print(f"  {_color('[--]', C.DARK_RED)} 不需要记录日记（情绪强度 < 0.6）")


def print_memory_flow(scenario_id: str, conversation: list[dict]) -> None:
    """打印三层记忆流转"""
    _safe_print()
    _safe_print(f"  {_color('【短期记忆】', C.CYAN)} Redis Mock（TTL=2小时）")
    for turn in conversation[-3:]:
        role = turn.get("role", "?")
        content = turn.get("content", "")[:40]
        icon = _color("*", C.GREEN) if role == "ai" else _color("*", C.BLUE)
        _safe_print(f"    {icon} [{role}] {content}...")

    _safe_print()
    _safe_print(f"  {_color('【中期记忆】', C.CYAN)} MySQL Mock（session_logs 表）")
    _safe_print(f"    [OK] SessionLog 已写入")
    _safe_print(f"    字段: session_id, user_message, ai_reply, emotion_vector, intervention_decision")

    _safe_print()
    _safe_print(f"  {_color('【长期记忆】', C.CYAN)} ChromaDB Mock（向量库）")
    _safe_print(f"    [OK] EmotionVector 已向量化存入（384维）")
    _safe_print(f"    [OK] 近30天可按语义检索（余弦相似度）")


# ==============================================================================
# 进度提示
# ==============================================================================

def print_progress(msg: str) -> None:
    """打印进度提示"""
    _safe_print(f"  {_color('>>>', C.DARK_YELLOW)} {msg}...", end="", flush=True)


def print_done() -> None:
    """打印完成标记"""
    _safe_print(f"  {_color('[OK]', C.DARK_GREEN)} 完成")


def print_thinking(dots: int = 3, delay: float = 0.4) -> None:
    """打印 DeepSeek 思考动画"""
    for _ in range(dots):
        _safe_print(f"{_gray('.')}", end="", flush=True)
        time.sleep(delay)
    _safe_print(f"  {_color('完成', C.DARK_GREEN)}")
