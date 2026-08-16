"""
婉情AI - 混合检索 RAG 核心模块
==============================
职责：
1. 将解析好的知识卡片向量化并存入 ChromaDB，维护知识库更新。
2. 承接 LangGraph 的 `generate_reply` 节点，基于当前用户情感向量（EmotionVector）
   和输入消息，提供高关联度的干预方法卡片。

依赖：
 - ChromaDB（共享 chroma_client 单例）
 - sentence-transformers（共享单例）
"""

import asyncio

from src.models.schemas import EmotionVector, EmotionLabel
from src.rag.knowledge_loader import load_all_knowledge_cards
from src.utils.logger import logger
from src.utils.chroma_client import get_chroma_client, get_embedding_model

from config import chroma_config, rag_config

# ==============================================================================
# 辅助函数
# ==============================================================================

def _get_rag_collection() -> "chromadb.Collection":
    """获取 RAG 知识库集合（使用共享 chroma_client 单例）"""
    import chromadb
    client: chromadb.PersistentClient = get_chroma_client()
    collection = client.get_or_create_collection(
        name=chroma_config.RAG_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )
    return collection

# ==============================================================================
# RAG 数据库构建与同步
# ==============================================================================

def sync_knowledge_base():
    """
    全量同步本地知识卡片到 ChromaDB
    (系统启动时或内容更新后调用)
    """
    cards = load_all_knowledge_cards()
    if not cards:
        logger.warning("[RAG] 没有发现知识卡片，跳过同步。")
        return
        
    collection = _get_rag_collection()
    model = get_embedding_model()
    
    docs = []
    embs = []
    metas = []
    ids = []
    
    for c in cards:
        # 为了提高检索效果，拼装关键上下文到文本进行 Embedding
        # 比如：[焦虑/灾难化] 5-4-3-2-1着陆技术 \n 目标：... \n ...正文
        enriched_text = (
            f"属性: [{','.join(c.emotions)}] / [{','.join(c.cognitive_distortions)}]\n"
            f"标题: {c.title}\n"
            f"目标: {c.goal}\n\n"
            f"正文:\n{c.content}"
        )
        
        docs.append(enriched_text)
        embs.append(model.encode(enriched_text).tolist())
        
        # ChromaDB metadata 仅支持 str/int/float/bool，将列表字段存为 CSV 字符串
        # post-filtering 由 retrieve_knowledge_cards 在 Python 层做（不依赖 ChromaDB 数组操作符）
        metas.append({
            "card_id": c.card_id,
            "title": c.title,
            "emotions": ",".join(c.emotions),                          # CSV 字符串
            "cognitive_distortions": ",".join(c.cognitive_distortions),  # CSV 字符串
            "scenario": ",".join(c.scenario),                          # CSV 字符串 ★新增
            "difficulty": c.difficulty,
            "goal": c.goal,
            "tags": ",".join(c.tags),                             # CSV 字符串 ★新增
            "duration": c.duration,                                   # str ★新增
        })
        ids.append(c.card_id)
        
    logger.info(f"[RAG] 正在向 ChromaDB 写入 {len(docs)} 张知识卡片...")
    
    # 覆盖式更新（或upsert）
    # 由于使用同样的 ids, upsert 会更新现有记录，避免重复
    collection.upsert(
        documents=docs,
        embeddings=embs,
        metadatas=metas,
        ids=ids
    )
    logger.info("[RAG] 知识卡片同步完毕。")

# ==============================================================================
# RAG 知识检索
# ==============================================================================

# ==============================================================================
# RAG 知识检索
# ==============================================================================

def _build_query_text(emotion_vector: EmotionVector, user_input: str) -> str:
    """
    构建向量化检索查询字符串。
    整合情感状态 + 历史趋势 + 认知扭曲 + 用户诉求，构成语义丰富的检索 query。
    """
    # 情绪标签
    query_emotions = emotion_vector.primary_emotion.value
    if emotion_vector.secondary_emotion:
        query_emotions += f", {emotion_vector.secondary_emotion.value}"

    # 认知扭曲
    distortions = [d.value for d in emotion_vector.cognitive_distortions]
    distortions_str = ",".join(distortions) if distortions else "无"

    # 历史上下文（任务2：注入 emotion_history 趋势）
    history_ctx = emotion_vector.history_context or {}
    recent_trend = history_ctx.get("recent_trend", "未知")
    baseline_deviation = history_ctx.get("baseline_deviation", 0.0)
    history_length = history_ctx.get("history_length", 0)

    query_text = (
        f"用户情绪: {query_emotions} (强度: {emotion_vector.intensity:.1f})\n"
        f"情感趋势: {recent_trend} | 基线偏差: {baseline_deviation:+.2f} | "
        f"历史记录数: {history_length}\n"
        f"认知扭曲: {distortions_str}\n"
        f"最新诉求/表达: {user_input}"
    )
    return query_text


def _build_metadata_filter(emotion_vector: EmotionVector) -> dict | None:
    """
    ChromaDB 当前版本不支持 $contains 操作符。
    metadata 精确过滤完全由 Python post-filter（_post_filter_cards）完成。
    此函数返回 None，即不做 ChromaDB 层的 metadata 预过滤。
    """
    return None


# ChromaDB 不支持 $contains 且 CSV 子串匹配不精确：
# emotion_tokens=["抑郁","情绪低落"]，检查 "沮丧" in token → False（误删）
# 改用排除过滤（黑名单）而非匹配过滤（白名单），保证向量相似度排序结果不被误杀
_OPPOSITE_EMOTION_GROUPS: dict[str, set[str]] = {
    "沮丧": {"开心", "快乐", "愉悦"},
    "焦虑": {"开心", "快乐", "愉悦"},
    "愤怒": {"开心", "快乐", "愉悦"},
    "恐惧": {"开心", "快乐", "愉悦"},
    "厌恶": {"开心", "快乐", "愉悦"},
    "平静": set(),  # 平静无反向
    "开心": {"沮丧", "愤怒", "恐惧"},
    "疲惫": {"开心"},
}


def _post_filter_cards(
    results: list[dict],
    emotion_vector: EmotionVector,
) -> list[dict]:
    """
    Python 层 post-filter：排除与当前情绪明显相反的卡片。

    方法：仅对高效价正面情绪（如开心）排除负面卡片，
    对负面情绪（如沮丧/焦虑）不做严格过滤，避免误删语义相关但标签措辞不同的卡片。
    ChromaDB 向量相似度本身已经做了语义排序，post-filter 只起安全阀作用。
    """
    if not results:
        return results

    primary = emotion_vector.primary_emotion.value

    # 开心时排除负面情绪卡片（精确黑名单）
    opposite_emotions = _OPPOSITE_EMOTION_GROUPS.get(primary, set())
    if not opposite_emotions:
        return results

    filtered = []
    for item in results:
        meta = item.get("meta", {})
        emotions_csv = meta.get("emotions", "")
        emotion_tokens = _parse_csv_list(emotions_csv)

        # 如果卡片包含明显反向情绪词 → 排除
        has_opposite = any(
            opp in token for opp in opposite_emotions for token in emotion_tokens
        )
        if has_opposite:
            continue
        filtered.append(item)

    return filtered


def _parse_csv_list(value: str | list) -> list[str]:
    """解析 CSV 字符串或保留列表格式。"""
    if isinstance(value, list):
        return [str(v).strip() for v in value]
    return [v.strip() for v in value.split(",") if v.strip()]


def _get_dynamic_top_k(intensity: float, forced_top_k: int | None = None) -> int:
    """
    根据情绪强度或强制值动态调整检索候选数量（任务6 + 优化v2）。

    Args:
        intensity: 情绪强度 (0~1)
        forced_top_k: 强制指定 top_k 值（优化v2使用，优先级最高）
    """
    if forced_top_k is not None:
        return forced_top_k

    if intensity >= 0.8:
        return 5
    elif intensity >= 0.6:
        return 4
    return 3


def _get_dynamic_threshold(emotion_vector: EmotionVector) -> float:
    """
    根据情绪类型动态调整相似度阈值（任务6）。
    高效价负面情绪（焦虑/愤怒/恐惧）需要更精确的匹配，减少噪声。
    """
    high_precision = [
        EmotionLabel.ANXIETY,
        EmotionLabel.ANGER,
        EmotionLabel.FEAR,
    ]
    if emotion_vector.primary_emotion in high_precision:
        return 0.60  # 负面高强度情绪：严格阈值
    return 0.55  # 其他情绪：适度阈值


async def retrieve_knowledge_cards(
    emotion_vector: EmotionVector,
    user_input: str,
    top_k: int | None = None,
) -> tuple[list[str], list[dict]]:
    """
    根据当前用户的情感向量和最新的发言，从知识库中检索最合适的卡片内容。

    【优化 v2】新增 top_k 参数，支持外部强制指定检索数量：
      - top_k=1：SUBTLE 轻量检索模式
      - top_k=3：INTERVENE 深度检索模式
      - top_k=None：使用动态计算（根据情绪强度）

    返回值：
      - list[str]: 格式化文本列表（向后兼容，供 Prompt 注入）
      - list[dict]: 含 metadata 的完整检索结果（供调用方提取 recommended_strategy 等信息）

    数据流（任务2+5+6）：
      1. 注入 emotion_history/history_context 到 query_text
      2. ChromaDB 向量检索（无 metadata 过滤）
      3. 动态 top_k（按 intensity 分段，或外部强制指定）
      4. 动态相似度阈值（按 emotion 类型分段）
      5. Python post-filter：排除与当前情绪明显相反的卡片（黑名单策略）
    """
    def _sync_retrieve() -> list[dict]:
        collection = _get_rag_collection()
        model = get_embedding_model()

        # 1. 构建检索 query（任务2：注入历史上下文）
        query_text = _build_query_text(emotion_vector, user_input)
        logger.debug(f"[RAG] 构建检索查询:\n{query_text}")

        query_vec = model.encode(query_text).tolist()

        # 2. 动态参数（任务6 + 优化v2）
        dynamic_top_k = _get_dynamic_top_k(emotion_vector.intensity, forced_top_k=top_k)
        dynamic_threshold = _get_dynamic_threshold(emotion_vector)

        # Python post-filter 完全负责精确 emotion token 过滤
        # ChromaDB 当前版本不支持 $contains，候选集通过扩大 n_results 保证召回充分
        n_candidates = dynamic_top_k * 3

        results = collection.query(
            query_embeddings=[query_vec],
            n_results=n_candidates,
        )

        retrieved: list[dict] = []
        if not results["distances"] or not results["distances"][0]:
            return retrieved

        # 预收集所有符合相似度阈值的结果
        for i, dist in enumerate(results["distances"][0]):
            similarity = 1.0 - dist

            if similarity < dynamic_threshold:
                logger.debug(
                    f"[RAG] 过滤低于阈值 ({similarity:.3f} < {dynamic_threshold}) 的卡片: "
                    f"{results['ids'][0][i]}"
                )
                continue

            meta = results["metadatas"][0][i]
            doc = results["documents"][0][i]
            retrieved.append({
                "meta": meta,
                "doc": doc,
                "similarity": similarity,
            })

        # 【任务5】Python post-filter：排除与当前情绪明显相反的卡片
        # 排除过滤仅针对开心场景排除负面卡片；负面情绪不做严格过滤，防止误删
        if retrieved:
            retrieved = _post_filter_cards(retrieved, emotion_vector)

        # 限制为 top_k 个并格式化输出
        top_k_candidates = retrieved[:dynamic_top_k]
        formatted = []
        for item in top_k_candidates:
            meta = item["meta"]
            doc = item["doc"]
            similarity = item["similarity"]
            card_str = (
                f"【参考心理学方案 - {meta.get('title', '')}】\n"
                f"{doc}\n"
                f"(匹配度: {similarity:.2f})"
            )
            formatted.append({
                "card_str": card_str,
                "meta": meta,
                "similarity": similarity,
            })

        return formatted

    try:
        result = await asyncio.to_thread(_sync_retrieve)
        card_strs = [r["card_str"] for r in result]
        logger.info(
            f"[RAG] 检索完成: {len(card_strs)} 张卡片 "
            f"(top_k={len(result)}, threshold=动态)"
        )
        return card_strs, result  # (格式化文本列表, 含metadata的完整结果)
    except Exception as e:
        logger.error(f"[RAG] 检索知识卡片时发生意外: {e}")
        return [], []

