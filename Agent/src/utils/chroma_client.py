"""
婉情AI - ChromaDB 共享客户端单例
=================================
职责：提供全局唯一的 ChromaDB PersistentClient 和 Embedding 模型实例，
      避免 long_term.py 和 retriever.py 各自独立初始化同一目录。

使用方式：
    from src.utils.chroma_client import get_chroma_client, get_embedding_model

依赖：
 - chromadb
 - sentence-transformers
"""

import os
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

from typing import Optional

from config import chroma_config, rag_config, huggingface_config
from src.utils.logger import logger

_chroma_client: Optional[chromadb.PersistentClient] = None
_embedding_model: Optional[SentenceTransformer] = None


def _configure_huggingface_mirror() -> None:
    """统一配置 HuggingFace 镜像，解决国内网络访问问题"""
    hf_endpoint = huggingface_config.ENDPOINT or os.getenv("HF_ENDPOINT")
    if hf_endpoint:
        logger.info(f"[chroma_client] 使用 HuggingFace 镜像：{hf_endpoint}")
        os.environ["HF_ENDPOINT"] = hf_endpoint


def get_chroma_client() -> chromadb.PersistentClient:
    """获取全局唯一的 ChromaDB PersistentClient（延迟初始化）"""
    global _chroma_client
    if _chroma_client is None:
        logger.info(f"[chroma_client] 初始化 ChromaDB Client，路径：{chroma_config.PERSIST_DIR}")
        _chroma_client = chromadb.PersistentClient(
            path=chroma_config.PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
    return _chroma_client


def get_embedding_model(model_name: Optional[str] = None) -> SentenceTransformer:
    """
    获取全局唯一的 SentenceTransformer 实例（延迟初始化）。

    Args:
        model_name: 可选，指定模型名。默认使用 rag_config.EMBEDDING_MODEL。
    """
    global _embedding_model
    if _embedding_model is None:
        _configure_huggingface_mirror()
        actual_model = model_name or rag_config.EMBEDDING_MODEL
        logger.info(f"[chroma_client] 正在加载 Embedding 模型：{actual_model} ...")
        _embedding_model = SentenceTransformer(actual_model)
    return _embedding_model
