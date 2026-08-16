"""
婉情AI - 心理学知识卡片解析器 (Knowledge Loader)
=================================================
职责：
1. 读取 `knowledge_cards/` 和 `corpus/` 目录下的所有 Markdown 文件。
2. 解析 YAML Frontmatter 和正文内容，兼容两套 schema。
3. 对 corpus 中的转义序列文件进行规范化预处理。
4. 返回结构化的 KnowledgeCard 对象列表，供后续入库或校验。
"""

import re
from pathlib import Path
from typing import Any

import yaml

from config import KNOWLEDGE_CARDS_DIR, CORPUS_CBT_DIR, CORPUS_ACT_DIR
from src.models.schemas import KnowledgeCard
from src.utils.logger import logger


# ==============================================================================
# 转义序列规范化
# ==============================================================================

def _normalize_escaped_content(content: str) -> str:
    """
    规范化 corpus 文件中的转义序列，将其还原为标准 Markdown。
    处理的问题：
      - \---  →  ---
      - \#    →  #
      - \##   →  ##
      - \###  →  ###
      - \n    →  实际换行符
      - 1\.   →  1.   (有序列表编号)
      - \*    →  *    (斜体/列表标记)
      - \*\*  →  **   (粗体)
    """
    # 先判断是否是需要规范化的 corpus 文件（非标准 frontmatter）
    lines = content.split("\n")
    if not lines:
        return content

    first_line = lines[0].strip()
    # 如果文件以 \--- 开头，说明是转义格式，需要全面规范化
    if first_line.startswith("\\---") or first_line.startswith("---"):
        # 统一处理：检测是否真的是转义文件
        # 转义文件的特征：frontmatter 边界是 \--- 而非 ---

        # 1. \--- 前置边界 → 标准 ---
        if content.startswith("\\---"):
            content = content.replace("\\---", "---", 1)
        if content.startswith("\\\n---"):
            content = content.replace("\\\n---", "---\n", 1)

        # 2. \--- 后置边界（第2个，处理开头多行的情况）
        # 找到第一个真正的 --- 行（排除 \--- 和空行）
        frontmatter_end_marker_count = 0
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "\\---":
                lines[i] = "---"
                frontmatter_end_marker_count += 1
                if frontmatter_end_marker_count == 2:
                    break

        content = "\n".join(lines)

    # 3. 正文中的转义序列（在整个文件中全局替换）
    # 注意：只在非 YAML frontmatter 区域处理，但为了简化，
    # 统一做，因为 frontmatter 区域（--- 之间）不会有这些转义
    replacements = [
        # 有序列表编号：1\. 2\. → 1. 2.
        (r"(\\)\s*(\d+)\\\.", r"\2."),
        # 标题转义：\# ## \### → # ## ###
        (r"\\#{1,3}\s?", lambda m: m.group(0).replace("\\", "")),
        # 粗体：\*\*text** → **text**（修复不完整的转义）
        (r"\\\*\*(.+?)\\\*\*", r"**\1**"),
        # 粗体前半：\*\*text → **text
        (r"\\\*\*(.+?)(?=[^*\n]|$)", r"**\1**"),
        # 斜体：\*text* → *text*
        (r"\\\*([^*]+?)\*", r"*\1*"),
        # 列表项前导：- \n- → - \n-
        (r"\n\\-\s?", r"\n- "),
        # 残留的单个反斜杠（不在合法转义序列中）
        (r"(?<!\\)\\(?![#*\-nrt\\])", ""),  # 移除孤立的 \
    ]

    for pattern, replacement in replacements:
        if callable(replacement):
            content = re.sub(pattern, replacement, content)
        else:
            content = re.sub(pattern, replacement, content)

    # 4. 特殊处理：在 YAML 值字符串中的 \n 转义（如 "焦虑\、惊恐"）
    # 恢复为正常标点
    content = content.replace("\\、", "、")
    content = content.replace("\\，", "，")
    content = content.replace("\\。", "。")
    content = content.replace("\\：", "：")
    content = content.replace("\\；", "；")
    content = content.replace("\\?", "?")

    return content


# ==============================================================================
# Markdown 卡片解析
# ==============================================================================

def parse_markdown_card(file_path: Path) -> KnowledgeCard | None:
    """
    解析单个 Markdown 知识卡片。

    兼容两种 Frontmatter schema：
      - 旧格式（knowledge_cards）：card_id, title, emotions, cognitive_distortions, ...
      - 新格式（corpus）：card_id, title, emotions, 适用场景, ...

    自动检测 corpus 文件中的转义序列并规范化。
    """
    try:
        raw_content = file_path.read_text(encoding="utf-8")

        # 前置处理：规范化转义序列
        content = _normalize_escaped_content(raw_content)

        # 匹配标准 YAML frontmatter（以 --- 开头和结束，中间非贪婪）
        match = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)

        if not match:
            logger.warning(
                f"[knowledge_loader] 文件 {file_path.name} 缺少标准 YAML frontmatter，已跳过。"
            )
            return None

        yaml_text = match.group(1)
        markdown_body = match.group(2).strip()

        # 解析 YAML
        metadata: dict[str, Any] = yaml.safe_load(yaml_text) or {}
        if not isinstance(metadata, dict):
            logger.warning(
                f"[knowledge_loader] 文件 {file_path.name} 的 frontmatter 不是有效字典，已跳过。"
            )
            return None

        # ── 字段名兼容映射 ────────────────────────────────────────────────

        def _parse_list(val: Any) -> list[str]:
            if isinstance(val, list):
                return [str(v).strip() for v in val]
            if isinstance(val, str):
                # corpus 文件用中文顿号、逗号、分号分隔
                for sep in ["、", "，", ";", "；"]:
                    if sep in val:
                        return [v.strip() for v in val.split(sep) if v.strip()]
                return [v.strip() for v in val.split(",") if v.strip()]
            return []

        # card_id：旧用 card_id，新用 卡片ID
        card_id = metadata.get("card_id") or metadata.get("卡片ID") or file_path.stem

        # title：旧用 title，新用 标题
        title = metadata.get("title") or metadata.get("标题", file_path.stem)

        # emotions：旧用 emotions/emotion，新用 情绪标签
        emotions = _parse_list(
            metadata.get("emotions")
            or metadata.get("emotion")
            or metadata.get("情绪标签", "")
        )

        # cognitive_distortions：仅旧格式有，新格式留空
        cognitive_distortions = _parse_list(
            metadata.get("cognitive_distortions", "")
        )

        # scenario：旧用 scenario，新用 适用场景
        scenario = _parse_list(
            metadata.get("scenario") or metadata.get("适用场景", "")
        )

        # goal：优先使用 frontmatter 中已有的值
        goal = str(metadata.get("goal", "")).strip()
        if not goal and markdown_body:
            # 兜底：从正文提取，策略：跳过所有 Markdown 标题行，取第一个有效段落
            # 1. 去掉开头连续的所有 # 标题行
            body_stripped = re.sub(r"^(?:#{1,6}\s+[^\n]*\n+)+", "", markdown_body, count=1).strip()
            if body_stripped:
                # 2. 取第一个段落（以空行分隔）
                first_para = body_stripped.split("\n\n", 1)[0].strip()
                if first_para:
                    goal = first_para[:200].replace("\n", " ")

        card = KnowledgeCard(
            card_id=card_id,
            title=title,
            emotions=emotions,
            cognitive_distortions=cognitive_distortions,
            scenario=scenario,
            goal=goal,
            difficulty=str(metadata.get("difficulty", "中等")),
            duration=str(metadata.get("duration", "")),
            tags=_parse_list(metadata.get("tags", "")),
            content=markdown_body,
        )
        return card

    except yaml.YAMLError as e:
        logger.error(f"[knowledge_loader] 文件 {file_path.name} 的 YAML 解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"[knowledge_loader] 解析 {file_path.name} 时发生错误: {e}")
        return None


# ==============================================================================
# 全量加载
# ==============================================================================

def load_all_knowledge_cards() -> list[KnowledgeCard]:
    """
    读取所有知识卡片目录：
      1. knowledge_cards/    （旧卡片）
      2. corpus/markdown/    （CBT 技术卡片）
      3. corpus/markdown(ACT)/（ACT 技术卡片）

    每个目录独立记录日志，避免单目录失败导致全部跳过。
    返回的卡片去重（按 card_id），优先保留 knowledge_cards 中的定义。
    """
    cards: list[KnowledgeCard] = []
    seen_ids: set[str] = set()

    scan_dirs = [
        (KNOWLEDGE_CARDS_DIR, "knowledge_cards"),
        (CORPUS_CBT_DIR, "corpus/markdown"),
        (CORPUS_ACT_DIR, "corpus/markdown(ACT)"),
    ]

    for scan_dir, dir_name in scan_dirs:
        if not scan_dir.exists():
            logger.warning(f"[knowledge_loader] 目录 {dir_name} 不存在，已跳过。")
            continue

        dir_cards = []
        for p in sorted(scan_dir.rglob("*.md")):
            card = parse_markdown_card(p)
            if card:
                # 重复检测：knowledge_cards 优先级最高
                if card.card_id in seen_ids:
                    logger.debug(
                        f"[knowledge_loader] 跳过重复卡片 {card.card_id}（来自 {p.parent.name}）"
                    )
                    continue
                seen_ids.add(card.card_id)
                dir_cards.append(card)

        logger.info(f"[knowledge_loader] 扫描目录 {dir_name}，加载 {len(dir_cards)} 张卡片。")
        cards.extend(dir_cards)

    logger.info(f"[knowledge_loader] 共加载 {len(cards)} 张心理学知识卡片。")
    return cards
