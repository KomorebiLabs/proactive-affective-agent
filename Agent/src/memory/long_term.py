"""
婉情AI - 长期语义与反思记忆 (Long-Term Semantic & Reflective Memory)
====================================================================
职责：使用 ChromaDB 存储非结构化高维语义信息（如对话摘要、情绪洞察反思等）。
机制：以余弦相似度进行上下文检索，作为深度干预或者情绪回溯的 Prompt 后盾。

依赖：
 - sentence-transformers 模型（由 chroma_client 单例提供）
 - chromadb（通过 chroma_client 单例使用）
"""

import time
from typing import Any

import chromadb  # 仅用于类型注解

from config import chroma_config
from src.models.schemas import LongTermMemory, MemoryType
from src.utils.logger import logger
from src.utils.chroma_client import get_chroma_client, get_embedding_model

# ==============================================================================
# Chroma Client 与 Embedding — 统一由 chroma_client 单例提供
# ==============================================================================

def _get_chroma_collection() -> chromadb.Collection:
    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=chroma_config.LONG_TERM_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )
    return collection

# ==============================================================================
# 读写接口 (对外暴露 Async，内部可通过 asyncio.to_thread 封装同步 IO)
# ==============================================================================

import asyncio

async def store_long_term_memory(
    user_id: str,
    content: str,
    memory_type: MemoryType = MemoryType.CONVERSATION_SUMMARY,
    metadata: dict[str, Any] = None
) -> str:
    """
    向量化并存储长期记忆
    """
    def _sync_store():
        model = get_embedding_model()
        collection = _get_chroma_collection()

        # 【任务7】会话摘要去重：同一 session_id 只保留最新一条
        if memory_type == MemoryType.CONVERSATION_SUMMARY:
            session_id = metadata.get("session_id") if metadata else None
            if session_id:
                existing = collection.get(
                    where={"$and": [
                        {"user_id": {"$eq": user_id}},
                        {"type": {"$eq": MemoryType.CONVERSATION_SUMMARY.value}},
                        {"session_id": {"$eq": session_id}},
                    ]}
                )
                if existing and existing.get("ids"):
                    collection.delete(ids=existing["ids"])
                    logger.debug(f"[long_term] 删除旧会话摘要: {existing['ids']}")

        vec = model.encode(content).tolist()
        memory_id = f"mem_{user_id}_{int(time.time()*1000)}"

        meta = {
            "user_id": user_id,
            "type": memory_type.value,
            "timestamp": int(time.time()),
            "is_cold": False
        }
        if metadata:
            meta.update(metadata)

        collection.add(
            documents=[content],
            embeddings=[vec],
            metadatas=[meta],
            ids=[memory_id]
        )
        return memory_id

    try:
        mem_id = await asyncio.to_thread(_sync_store)
        logger.info(f"[long_term] 成功存储长期向量记忆: id={mem_id}, type={memory_type.value}")
        return mem_id
    except Exception as e:
        logger.error(f"[long_term] 存储向量记忆失败: {e}")
        return ""


async def retrieve_relevant_memories(
    user_id: str,
    query_text: str,
    k: int = chroma_config.DEFAULT_TOP_K
) -> list[LongTermMemory]:
    """
    通过相似度检索高度相关的长期情感洞察
    """
    def _sync_retrieve():
        model = get_embedding_model()
        collection = _get_chroma_collection()

        query_vec = model.encode(query_text).tolist()

        # 【任务7】扩大候选集 + post-filter 优先保留洞察类型
        # ChromaDB where 不支持 $in 或 OR-type 数组过滤，在结果层做类型优先级筛选
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=k * 3,  # 扩大候选集，由 post-filter 筛选
            where={"$and": [
                {"user_id": {"$eq": user_id}},
                {"is_cold": {"$eq": False}}
            ]}
        )

        memories = []
        if not results["ids"] or not results["ids"][0]:
            return memories

        # 【任务7】Post-filter：按类型优先级排序（洞察 > 摘要 > 模式），取 TOP-k
        # 类型优先级映射
        TYPE_PRIORITY = {
            MemoryType.SESSION_INSIGHT.value: 0,
            MemoryType.CONVERSATION_SUMMARY.value: 1,
            MemoryType.LONG_PATTERN.value: 2,
        }

        scored = []
        for i in range(len(results["ids"][0])):
            doc_id = results["ids"][0][i]
            content = results["documents"][0][i]
            meta = results["metadatas"][0][i]
            mem_type_val = meta.get("type", MemoryType.CONVERSATION_SUMMARY.value)
            priority = TYPE_PRIORITY.get(mem_type_val, 99)
            dist = results["distances"][0][i] if results["distances"] else 0.0
            scored.append({
                "priority": priority,
                "dist": dist,
                "doc_id": doc_id,
                "content": content,
                "meta": meta,
            })

        # 按 (priority ASC, dist ASC) 排序，取前 k 个
        scored.sort(key=lambda x: (x["priority"], x["dist"]))
        top_results = scored[:k]

        for item in top_results:
            doc_id = item["doc_id"]
            content = item["content"]
            meta = item["meta"]

            mem = LongTermMemory(
                id=doc_id,
                user_id=meta["user_id"],
                content=content,
                type=MemoryType(meta.get("type", MemoryType.CONVERSATION_SUMMARY.value)),
                timestamp=meta.get("timestamp", int(time.time())),
                metadata={k: v for k, v in meta.items() if k not in ["user_id", "type", "timestamp", "is_cold"]},
                is_cold=False
            )
            memories.append(mem)
        return memories

    try:
        memories = await asyncio.to_thread(_sync_retrieve)
        logger.debug(f"[long_term] 针对 query='{query_text[:10]}...' 检索到 {len(memories)} 条相关记忆")
        return memories
    except Exception as e:
        logger.error(f"[long_term] 检索向量记忆失败: {e}")
        return []

