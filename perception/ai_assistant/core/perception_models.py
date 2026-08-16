# ==============================================================================
# Wanqing Backend - 感知模型封装
# ==============================================================================
# 职责：
#   1. HuggingFace 情绪分类模型（FER2013）的加载与推理
#   2. 从情绪标签反向推断 AU 近似强度
#   3. 提供统一的推理接口，供 perception_engine 调用
#
# 模型选择：
#   - 情绪分类：trpakov/vit-face-expression（FER2013验证集71.13%，社区最流行）
#     备选：Tanneru/Facial-Emotion-Detection-FER-RAFDB-AffectNet-BEIT-Large（76.2%）
#   - AU 推断：基于情绪→AU 映射表做近似反推
#     未来可升级为专用 AU 检测模型（如 OpenFace 封装或 AU-rcnn）
#
# 设计原则：
#   - 延迟初始化（程序启动时不加载，PerceptionEngine 首次推理前才加载）
#   - 单例模式（全程只加载一份模型）
#   - 线程安全（推理在感知引擎专用线程中进行，不存在并发问题）
# ==============================================================================

from __future__ import annotations

import os
import threading
import numpy as np
from typing import Any

# ------------------------------------------------------------------------------
# 配置 HuggingFace 镜像（解决国内网络无法访问 huggingface.co 的问题）
# ------------------------------------------------------------------------------
# 注意：必须在 transformers 库加载之前设置环境变量
# 优先从环境变量读取，若未设置则使用默认值
try:
    from dotenv import load_dotenv
    # 尝试加载 backend/.env（确保感知服务能读取到配置）
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except ImportError:
    pass

# 获取 HuggingFace 镜像地址，若未配置则使用默认值
hf_endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
# 设置环境变量（确保 transformers 库使用镜像）
os.environ["HF_ENDPOINT"] = hf_endpoint
print(f"[PerceptionModel] HuggingFace 镜像: {hf_endpoint}")

# ------------------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------------------

# HuggingFace 模型 ID（首次推理时自动下载到本地缓存）
# 推荐模型：trpakov/vit-face-expression（FER2013验证集71.13%，社区最流行）
# 备选：Tanneru/Facial-Emotion-Detection-FER-RAFDB-AffectNet-BEIT-Large（76.2%，需较大显存）
# 已废弃：mit/fer2013plus（HuggingFace不存在此模型ID）
EMOTION_MODEL_ID = "trpakov/vit-face-expression"

# FER2013 输出的情绪标签映射到 Agent 期望的 10 类中文标签
FER_TO_CHINESE: dict[str, str] = {
    "angry":   "愤怒",
    "disgust": "厌恶",
    "fear":    "恐惧",
    "happy":   "开心",
    "neutral": "中性",
    "sad":     "沮丧",
    "surprise": "惊讶",
}

# 情绪 → AU 近似强度映射表
# 格式：{ emotion_label: { AU_Number: estimated_intensity } }
# 基于 FACS 标准的心理学规律构建
EMOTION_TO_AU: dict[str, dict[str, float]] = {
    "angry":   {"AU4": 0.85, "AU5": 0.30, "AU7": 0.20, "AU17": 0.50},
    "disgust": {"AU4": 0.60, "AU9": 0.70, "AU15": 0.30, "AU17": 0.40},
    "fear":    {"AU1": 0.60, "AU2": 0.50, "AU4": 0.70, "AU5": 0.60, "AU7": 0.40},
    "happy":   {"AU6": 0.80, "AU12": 0.90, "AU25": 0.30},
    "neutral":  {},
    "sad":     {"AU1": 0.40, "AU4": 0.30, "AU15": 0.80, "AU17": 0.50},
    "surprise": {"AU1": 0.60, "AU2": 0.50, "AU5": 0.70, "AU26": 0.50},
}


class AUModelWrapper:
    """
    AU 检测模型封装器（延迟初始化 + 单例）
    """

    # 【修复】负面情绪校准配置
    NEGATIVE_EMOTIONS = {"angry", "disgust", "fear", "sad"}  # 负面情绪列表
    NEGATIVE_GAP_THRESHOLD = 0.15  # 如果 neutral 与最高情绪概率差距 < 15%，强制设为 neutral
    NEGATIVE_CONF_THRESHOLD = 0.50  # 负面情绪必须 > 50% 才考虑保留，否则直接设为 neutral

    def __init__(self):
        self._model = None
        self._feature_extractor = None
        self._lock = threading.Lock()
        self._initialized = False

    def _lazy_load(self) -> None:
        """延迟加载模型（首次推理前调用）"""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                from transformers import AutoModelForImageClassification, AutoImageProcessor
                import torch

                print(f"[PerceptionModel] 正在加载情绪模型: {EMOTION_MODEL_ID} ...")
                self._feature_extractor = AutoImageProcessor.from_pretrained(EMOTION_MODEL_ID)
                self._model = AutoModelForImageClassification.from_pretrained(EMOTION_MODEL_ID)
                self._model.eval()  # 推理模式
                print("[PerceptionModel] 情绪模型加载完成")
                self._initialized = True
            except Exception as e:
                print(f"[PerceptionModel] 模型加载失败: {e}")
                print(f"[PerceptionModel] 将使用规则兜底方案（无模型推理）。提示：请检查网络连接和模型ID是否正确（当前: {EMOTION_MODEL_ID}）")
                self._initialized = True  # 标记已尝试，避免重复尝试

    def predict(self, frame: np.ndarray) -> dict[str, Any]:
        """
        对输入帧进行情绪分类，并推断 AU 近似强度。

        【修复】FER2013 模型容易把中性误判为愤怒/厌恶/沮丧，需要二次校准：
        - 负面情绪必须显著领先于 neutral（差距 > 15%）才保留
        - 负面情绪本身置信度必须 > 50% 才考虑保留
        - 否则强制设为 neutral

        Args:
            frame: BGR 格式的 numpy ndarray 图像（H x W x 3）

        Returns:
            dict，包含：
              - primary_emotion: str（英文标签，如 "sad"）
              - emotion_zh: str（中文标签，如 "沮丧"）
              - confidence: float（模型置信度，0~1）
              - emotion_scores: dict[str, float]（各情绪的原始分数）
              - au_intensities: dict[str, float]（各 AU 的近似强度，0~1）
        """
        self._lazy_load()

        # --------------------------------------------------------------------------
        # 步骤 1：情绪分类推理
        # --------------------------------------------------------------------------
        emotion_en = "neutral"
        confidence = 0.0
        emotion_scores: dict[str, float] = {}

        if self._model is not None and self._feature_extractor is not None:
            try:
                from transformers import AutoImageProcessor
                import torch

                # BGR → RGB（PyTorch 期望 RGB）
                frame_rgb = frame[:, :, ::-1]

                inputs = self._feature_extractor(
                    images=frame_rgb, return_tensors="pt"
                )

                with torch.no_grad():
                    outputs = self._model(**inputs)
                    probs = torch.softmax(outputs.logits, dim=1)

                # 获取所有情绪标签和概率
                if hasattr(self._model, "config") and hasattr(self._model.config, "id2label"):
                    id2label = self._model.config.id2label
                    emotion_scores = {
                        id2label.get(i, label): probs[0, i].item()
                        for i, label in enumerate(["surprise", "sad", "neutral", "happy", "fear", "disgust", "angry"])
                        if i < probs.shape[1]
                    }
                else:
                    labels = ["surprise", "sad", "neutral", "happy", "fear", "disgust", "angry"]
                    emotion_scores = {
                        labels[i]: probs[0, i].item()
                        for i in range(min(len(labels), probs.shape[1]))
                    }

                # 获取最高概率的情绪
                emotion_en = max(emotion_scores, key=emotion_scores.get)
                confidence = emotion_scores[emotion_en]

                # 【修复】FER2013 误判校准：负面情绪必须显著领先于 neutral
                NEUTRAL_PROB = emotion_scores.get("neutral", 0.0)

                if emotion_en in self.NEGATIVE_EMOTIONS:
                    # 条件1：负面情绪置信度必须 > 阈值
                    # 条件2：负面情绪必须领先 neutral 超过差距阈值
                    if confidence <= self.NEGATIVE_CONF_THRESHOLD or \
                       NEUTRAL_PROB >= confidence - self.NEGATIVE_GAP_THRESHOLD:
                        emotion_en = "neutral"
                        confidence = NEUTRAL_PROB
                        print(f"[PerceptionModel] 校准：{list(emotion_scores.keys())} → neutral (neutral={NEUTRAL_PROB:.2f}, top={confidence:.2f})")

            except Exception as e:
                print(f"[PerceptionModel] 推理出错: {e}")
                emotion_en = "neutral"
                confidence = 0.0
                emotion_scores = {}
        # else: 默认值在上面初始化

        # --------------------------------------------------------------------------
        # 步骤 2：AU 近似推断
        # --------------------------------------------------------------------------
        au_intensities = self._infer_au_from_emotion(emotion_en)

        # --------------------------------------------------------------------------
        # 步骤 3：构建返回值
        # --------------------------------------------------------------------------
        emotion_zh = FER_TO_CHINESE.get(emotion_en, "中性")

        return {
            "primary_emotion": emotion_en,
            "emotion_zh": emotion_zh,
            "confidence": float(confidence),
            "emotion_scores": emotion_scores,
            "au_intensities": au_intensities,
        }

    @staticmethod
    def _infer_au_from_emotion(emotion: str) -> dict[str, float]:
        """
        基于情绪标签推断 AU 近似强度。

        原理：FER2013 等情绪分类模型的输出本质上是面部肌肉运动的组合模式，
        可以通过反向映射表近似还原 AU 强度。

        未来升级方向：使用专用 AU 检测模型（OpenFace / AU-rcnn）替代此近似逻辑。
        """
        base_au = EMOTION_TO_AU.get(emotion, {})

        # 为未在映射表中的 AU 填充默认值 0.0
        all_au = ["AU1", "AU2", "AU4", "AU5", "AU6", "AU7", "AU9",
                   "AU12", "AU15", "AU17", "AU25", "AU26"]
        result = {au: base_au.get(au, 0.0) for au in all_au}

        return result


# ------------------------------------------------------------------------------
# 全局单例（延迟初始化）
# ------------------------------------------------------------------------------
_au_model: AUModelWrapper | None = None


def get_au_model() -> AUModelWrapper:
    """获取全局 AU 模型单例"""
    global _au_model
    if _au_model is None:
        _au_model = AUModelWrapper()
    return _au_model
