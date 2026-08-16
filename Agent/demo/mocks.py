"""
婉情AI - Demo Mock 适配层
===========================
将所有外部依赖（Redis、ChromaDB、Notion、MySQL）Mock 为内存实现，
不影响原有代码，演示模式下自动生效。
"""

from __future__ import annotations

import asyncio
import json
import time
import math
from typing import Any


# ==============================================================================
# 1. Redis Mock：纯内存 dict，模拟异步 Redis 操作
# ==============================================================================

class InMemoryRedis:
    """
    完全运行在内存中的 Redis Mock。
    实现了 demo 演示所需的最小 Redis API 子集：
    - lpush / lrange / ltrim / llen  (List 操作)
    - get / set / setex              (String 操作)
    - expire / exists                 (TTL/存在性)
    - pipeline                        (事务管道)
    """

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._ttls: dict[str, float] = {}

    # ---- String 操作 ----

    async def get(self, key: str) -> str | None:
        if key in self._data:
            ttl = self._ttls.get(key)
            if ttl and time.time() > ttl:
                del self._data[key]
                del self._ttls[key]
                return None
            return self._data[key]
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value
        if ex:
            self._ttls[key] = time.time() + ex
        elif key in self._ttls:
            del self._ttls[key]

    async def setex(self, key: str, seconds: int, value: str) -> None:
        await self.set(key, value, ex=seconds)

    async def exists(self, key: str) -> int:
        v = await self.get(key)
        return 1 if v is not None else 0

    async def expire(self, key: str, seconds: int) -> None:
        if key in self._data:
            self._ttls[key] = time.time() + seconds

    # ---- List 操作 ----

    # ---- List 操作 ----
    # Redis LPUSH key v1 v2 的真实行为：
    #   先 LPUSH v1 → [v1]，再 LPUSH v2 → [v2, v1]
    # 所以多个参数时，【后面的参数排在队首】。
    # 实现：依次将每个参数 insert(0, v)，即可得到正确顺序 [v2, v1, ...]
    async def lpush(self, key: str, *values: str) -> int:
        if key not in self._data:
            self._data[key] = []
        lst: list = self._data[key]
        for v in values:
            lst.insert(0, v)
        return len(lst)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        if key not in self._data:
            return []
        lst: list = self._data[key]
        if end == -1:
            return lst[start:]
        return lst[start:end + 1]

    # list index
    async def _li(key, idx):
        if key not in self._data:
            return None
        lst = self._data[key]
        return lst[idx] if -len(lst) <= idx < len(lst) else None

    # list trim: keep [start, end] inclusive
    async def ltrim(self, key: str, start: int, end: int) -> None:
        if key not in self._data:
            return
        lst = self._data[key]
        if end == -1:
            self._data[key] = lst[start:]
        else:
            self._data[key] = lst[start:end + 1]

    async def llen(self, key: str) -> int:
        if key not in self._data:
            return 0
        return len(self._data[key])

    # ---- Pipeline（Mock） ----

    async def pipeline(self, transaction: bool = True):
        return _InMemoryPipeline(self)


class _InMemoryPipeline:
    """Mock Redis Pipeline，将多个命令批量执行"""

    def __init__(self, redis: InMemoryRedis):
        self._redis = redis
        self._commands: list[tuple] = []

    def set(self, key: str, value: str):
        self._commands.append(("set", key, value))
        return self

    def ltrim(self, key: str, start: int, end: int):
        self._commands.append(("ltrim", key, start, end))
        return self

    async def execute(self) -> list:
        results = []
        for cmd in self._commands:
            if cmd[0] == "set":
                await self._redis.set(cmd[1], cmd[2])
                results.append(True)
            elif cmd[0] == "ltrim":
                await self._redis.ltrim(cmd[1], cmd[2], cmd[3])
                results.append(True)
        self._commands.clear()
        return results


# ==============================================================================
# 2. ChromaDB Mock：纯内存向量数据库（余弦相似度）
# ==============================================================================

class InMemoryChromaCollection:
    """
    纯内存 ChromaDB Collection Mock。
    实现最小 API 子集：
    - add (upsert 行为)     添加/覆盖文档
    - query                  向量最近邻搜索
    - get                    按条件查询
    - delete                 删除文档
    """

    def __init__(self, name: str = "default", metadata: dict | None = None):
        self.name = name
        self._docs: list[str] = []
        self._embeddings: list[list[float]] = []
        self._metadatas: list[dict] = []
        self._ids: list[str] = []

    def _cosine_sim(self, a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def add(self, ids: list[str], embeddings: list[list[float]],
            metadatas: list[dict], documents: list[str]) -> None:
        for i, doc_id in enumerate(ids):
            if doc_id in self._ids:
                idx = self._ids.index(doc_id)
                self._docs[idx] = documents[i]
                self._embeddings[idx] = embeddings[i]
                self._metadatas[idx] = metadatas[i]
            else:
                self._ids.append(doc_id)
                self._docs.append(documents[i])
                self._embeddings.append(embeddings[i])
                self._metadatas.append(metadatas[i])

    def upsert(self, ids: list[str], embeddings: list[list[float]],
               metadatas: list[dict], documents: list[str]) -> None:
        self.add(ids, embeddings, metadatas, documents)

    def query(self, query_embeddings: list[list[float]],
              n_results: int = 10,
              where: dict | None = None) -> dict:
        if not self._ids:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        query_vec = query_embeddings[0]
        scored = []
        for i, emb in enumerate(self._embeddings):
            meta = self._metadatas[i]
            # apply where filter
            if where:
                skip = False
                for k, v in where.items():
                    if isinstance(v, dict):
                        op = list(v.keys())[0]
                        val = v[op]
                        if op == "$eq":
                            if meta.get(k) != val:
                                skip = True
                        elif op == "$ne":
                            if meta.get(k) == val:
                                skip = True
                        elif op == "$and":
                            for sub in val:
                                sub_k = list(sub.keys())[0]
                                sub_op = list(sub[sub_k].keys())[0]
                                sub_val = sub[sub_k][sub_op]
                                if sub_op == "$eq" and meta.get(sub_k) != sub_val:
                                    skip = True
                    elif meta.get(k) != v:
                        skip = True
                if skip:
                    continue

            sim = self._cosine_sim(query_vec, emb)
            scored.append({
                "idx": i,
                "distance": 1.0 - sim,   # ChromaDB distance = 1 - cosine
                "sim": sim,
            })

        scored.sort(key=lambda x: x["distance"])
        top = scored[:n_results]

        return {
            "ids": [[self._ids[s["idx"]] for s in top]],
            "documents": [[self._docs[s["idx"]] for s in top]],
            "metadatas": [[self._metadatas[s["idx"]] for s in top]],
            "distances": [[s["distance"] for s in top]],
        }

    def get(self, where: dict | None = None, ids: list[str] | None = None) -> dict:
        if ids:
            result = {"ids": [], "documents": [], "metadatas": []}
            for i, doc_id in enumerate(self._ids):
                if doc_id in ids:
                    result["ids"].append(doc_id)
                    result["documents"].append(self._docs[i])
                    result["metadatas"].append(self._metadatas[i])
            return result

        result = {"ids": [], "documents": [], "metadatas": []}
        for i in range(len(self._ids)):
            meta = self._metadatas[i]
            skip = False
            if where:
                for k, v in where.items():
                    if isinstance(v, dict):
                        for op, val in v.items():
                            if op == "$eq" and meta.get(k) != val:
                                skip = True
                    elif meta.get(k) != v:
                        skip = True
            if not skip:
                result["ids"].append(self._ids[i])
                result["documents"].append(self._docs[i])
                result["metadatas"].append(self._metadatas[i])
        return result

    def delete(self, ids: list[str]) -> None:
        for doc_id in ids:
            if doc_id in self._ids:
                idx = self._ids.index(doc_id)
                del self._ids[idx]
                del self._docs[idx]
                del self._embeddings[idx]
                del self._metadatas[idx]


class InMemoryChromaClient:
    """
    纯内存 ChromaDB PersistentClient Mock。
    支持多个 Collection，按 name 区分。
    """

    def __init__(self):
        self._collections: dict[str, InMemoryChromaCollection] = {}

    def get_or_create_collection(
        self, name: str, metadata: dict | None = None
    ) -> InMemoryChromaCollection:
        if name not in self._collections:
            self._collections[name] = InMemoryChromaCollection(name=name, metadata=metadata)
        return self._collections[name]


# ==============================================================================
# 3. Notion Mock：返回成功 JSON，不实际写入 Notion
# ==============================================================================

class MockNotionClient:
    """Mock Notion Client，返回成功响应"""

    _created_pages: list[dict] = []

    def __init__(self, auth: str = ""):
        self._auth = auth

    def pages_create(self, **kwargs) -> dict:
        import uuid
        page_id = str(uuid.uuid4()).replace("-", "")[:32]
        page = {
            "object": "page",
            "id": page_id,
            "url": f"https://notion.so/demo-mock-{page_id[:8]}",
            "created_time": "2026-04-06T00:00:00.000Z",
        }
        self._created_pages.append(page)
        return page


# ==============================================================================
# 4. MySQL Callback Mock：直接返回 True（模拟成功）
# ==============================================================================

async def mock_call_java(session_log: dict[str, Any]) -> bool:
    """Mock Java MySQL 回调，直接返回 True"""
    return True


# ==============================================================================
# 全局 Mock 实例（单例）
# ==============================================================================

_mock_redis: InMemoryRedis | None = None
_mock_chroma: InMemoryChromaClient | None = None


def get_mock_redis() -> InMemoryRedis:
    global _mock_redis
    if _mock_redis is None:
        _mock_redis = InMemoryRedis()
    return _mock_redis


def get_mock_chroma() -> InMemoryChromaClient:
    global _mock_chroma
    if _mock_chroma is None:
        _mock_chroma = InMemoryChromaClient()
    return _mock_chroma


# ==============================================================================
# patch：将原有模块的全局变量替换为 Mock 实例
# ==============================================================================

def apply_mocks():
    """
    将所有外部依赖 Patch 为 Mock 实现。
    必须在任何业务代码导入之前调用（或在 demo 入口处调用）。
    """
    import sys
    from importlib import import_module

    mock_redis = get_mock_redis()

    # ---- Patch redis_client ----
    redis_module = import_module("src.utils.redis_client")
    redis_module._redis = mock_redis

    # ---- Patch short_term.get_redis factory ----
    # short_term.py has its own async get_redis() that builds a new connection pool each time.
    # We need to replace that function entirely so it returns our mock Redis.
    short_module = import_module("src.memory.short_term")

    async def _mock_short_term_get_redis():
        return mock_redis

    short_module.get_redis = _mock_short_term_get_redis
    short_module._redis_pool = None  # prevent rebuild attempt

    # ---- Patch chroma_client ----
    chroma_module = import_module("src.utils.chroma_client")
    chroma_module._chroma_client = get_mock_chroma()
    chroma_module._embedding_model = None  # embedding 模型仍然使用真实的

    # ---- Patch notion_tool ----
    try:
        notion_module = import_module("src.agent.tools.notion_tool")

        class _MockNotionClient:
            """
            Mock Notion 客户端。
            支持 client.pages.create(...) 的链式调用语法。
            record_mood_diary 函数内部会 json.dumps 序列化返回结果。
            """

            _created_pages: list = []

            def __init__(self):
                self.pages = _MockPages()

        class _MockPages:
            """Mock notion_client.Pages 子对象"""

            _created: list = []

            def create(self, **kwargs) -> dict:
                """模拟 pages.create()"""
                import uuid
                page_id = str(uuid.uuid4()).replace("-", "")[:32]
                page = {
                    "object": "page",
                    "id": page_id,
                    "url": f"https://notion.so/demo-mock-{page_id[:8]}",
                    "created_time": "2026-04-06T00:00:00.000Z",
                }
                _MockPages._created.append(page)
                return page

        notion_module._notion_client = _MockNotionClient()

        # Patch _get_database_id to avoid ValueError when NOTION_DATABASE_ID is unset
        notion_module._get_database_id = lambda: "demo-database-id-0000"
    except Exception:
        pass

    # ---- Patch callback ----
    callback_module = import_module("src.memory.callback")
    callback_module.call_java_conversation_log = mock_call_java


def reset_mocks():
    """重置所有 Mock 状态（每次 demo 演示前调用）"""
    global _mock_redis, _mock_chroma
    _mock_redis = None
    _mock_chroma = None
