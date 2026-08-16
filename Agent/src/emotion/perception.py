from __future__ import annotations

"""
婉情AI - 感知数据处理层
========================
职责：
  1. 从 Redis 读取感知微服务写入的实时数据（PerceptionData）
  2. 计算派生指标：focus_level（专注度）、arousal（唤醒度）
  3. 提供情感历史查询接口及趋势计算（MySQL，本期预留接口）
  4. 判断是否触发"专注模式"规则引擎（走神→专注切换）

设计约定：
  - 所有公开函数均为 async，以匹配 LangGraph 异步节点
  - Redis 连接在模块级延迟初始化，避免导入时的副作用
  - focus_level 计算不依赖屏幕捕获，仅用头部姿态 + 眨眼频率
"""

import json
import math
import time
from typing import Any

import redis.asyncio as aioredis

from config import redis_config, perception_config
from src.models.schemas import (
    AUIntensities,
    AudioFeatures,
    EmotionTrend,
    HeadPose,
    PerceptionData,
)
from src.utils.logger import logger


# ==============================================================================
# Redis 连接管理
# ==============================================================================

_redis_pool: aioredis.ConnectionPool | None = None


def _get_redis_pool() -> aioredis.ConnectionPool:
    """延迟初始化 Redis 连接池（单例）"""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool(
            host=redis_config.HOST,
            port=redis_config.PORT,
            db=redis_config.DB,
            password=redis_config.PASSWORD,
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


async def get_redis() -> aioredis.Redis:
    """获取 Redis 客户端（使用共享连接池）"""
    return aioredis.Redis(connection_pool=_get_redis_pool())


# ==============================================================================
# 感知数据读写
# ==============================================================================

async def get_latest_perception(session_id: str) -> PerceptionData | None:
    """
    从 Redis 读取感知微服务最近写入的一帧感知数据。

    Key 格式: emotion:realtime:{session_id}
    写入方: 感知微服务（MediaPipe + openSMILE + HuggingFace AU），10Hz 频率

    Args:
        session_id: 当前会话ID

    Returns:
        PerceptionData 对象；若 Redis 中无数据则返回 None
    """
    key = redis_config.perception_key(session_id)
    try:
        r = await get_redis()
        raw = await r.get(key)
        if not raw:
            logger.debug(f"[Perception] Redis 中无感知数据: key={key}")
            return None

        data = json.loads(raw)
        perception = PerceptionData(
            session_id=session_id,
            timestamp=data.get("timestamp", int(time.time() * 1000)),
            head_pose=HeadPose(**data.get("head_pose", {})),
            blink_rate=data.get("blink_rate", 0.0),
            au=AUIntensities(**data.get("au", {})),
            audio=AudioFeatures(**data.get("audio", {})),
            focus_level=data.get("focus_level", 0.5),
        )
        logger.debug(f"[Perception] 读取成功: session={session_id}, AU4={perception.au.AU4:.2f}")
        return perception

    except Exception as e:
        logger.error(f"[Perception] 读取 Redis 失败: {e}")
        return None


async def write_perception(session_id: str, data: dict[str, Any]) -> None:
    """
    将感知数据写入 Redis（供感知微服务调用或测试用）。
    实际生产中由感知微服务直接写入，此函数供测试用。

    Args:
        session_id: 会话ID
        data: 原始感知数据 dict（需符合 PerceptionData 字段结构）
    """
    key = redis_config.perception_key(session_id)
    try:
        r = await get_redis()
        data["timestamp"] = int(time.time() * 1000)
        await r.set(key, json.dumps(data, ensure_ascii=False))
        logger.debug(f"[Perception] 写入成功: key={key}")
    except Exception as e:
        logger.error(f"[Perception] 写入 Redis 失败: {e}")


async def get_latest_camera_frame(session_id: str) -> str | None:
    """
    从 Redis 读取感知微服务最近写入的摄像头帧 Base64。

    Key 格式: camera:frame:{session_id}
    写入方: 感知微服务（PerceptionEngine._write_to_redis），每帧分析后覆盖写入
    TTL: 30 秒，过期自动清理

    Args:
        session_id: 当前会话ID

    Returns:
        Base64 编码的 JPEG 图像字符串；若 Redis 中无数据则返回 None
    """
    frame_key = f"camera:frame:{session_id}"
    try:
        r = await get_redis()
        frame_base64 = await r.get(frame_key)
        if not frame_base64:
            logger.debug(f"[Perception] Redis 中无摄像头帧: key={frame_key}")
            return None
        logger.debug(f"[Perception] 读取摄像头帧成功: key={frame_key}, 长度={len(frame_base64)}")
        return frame_base64
    except Exception as e:
        logger.error(f"[Perception] 读取摄像头帧 Redis 失败: {e}")
        return None


# ==============================================================================
# Qwen-VL 调用间隔管理（使用 Redis 存储，避免进程级缓存的并发问题）
# ==============================================================================

_QWEN_LAST_CALL_KEY = "qwen:last_call:{session_id}"


async def get_last_qwen_call_time(session_id: str) -> float:
    """
    从 Redis 读取上次 Qwen-VL 调用时间戳。

    Key 格式: qwen:last_call:{session_id}
    TTL: 24 小时（防止过期 key 堆积）

    Returns:
        上次调用时间戳（Unix 秒）；若无记录则返回 0.0
    """
    key = _QWEN_LAST_CALL_KEY.format(session_id=session_id)
    try:
        r = await get_redis()
        value = await r.get(key)
        return float(value) if value else 0.0
    except Exception:
        return 0.0


async def set_last_qwen_call_time(session_id: str) -> None:
    """
    更新 Qwen-VL 调用时间戳到 Redis。

    Key 格式: qwen:last_call:{session_id}
    TTL: 24 小时
    """
    import time as _time
    key = _QWEN_LAST_CALL_KEY.format(session_id=session_id)
    try:
        r = await get_redis()
        await r.setex(key, 86400, str(_time.time()))  # 24小时过期
    except Exception as e:
        logger.warning(f"[Perception] 更新 Qwen 调用时间失败: {e}")


# ==============================================================================
# 专注模式状态管理（使用 Redis 存储，支持多 worker 进程）
# ==============================================================================

_FOCUS_MODE_KEY = "focus:mode:{session_id}"


async def get_focus_mode(session_id: str) -> bool:
    """
    从 Redis 读取专注模式状态。

    Key 格式: focus:mode:{session_id}
    TTL: 5 分钟（无更新时自动退出专注模式）

    Returns:
        True=专注模式，False=走神模式
    """
    key = _FOCUS_MODE_KEY.format(session_id=session_id)
    try:
        r = await get_redis()
        value = await r.get(key)
        return value == "1"
    except Exception:
        return False


async def set_focus_mode(session_id: str, focused: bool) -> None:
    """
    更新专注模式状态到 Redis。

    Key 格式: focus:mode:{session_id}
    TTL: 5 分钟（无更新时自动退出专注模式，与 FOCUS_MODE_DURATION_SECONDS 配合）
    """
    key = _FOCUS_MODE_KEY.format(session_id=session_id)
    try:
        r = await get_redis()
        await r.setex(key, 300, "1" if focused else "0")  # 5分钟过期
    except Exception as e:
        logger.warning(f"[Perception] 更新专注模式状态失败: {e}")


# ==============================================================================
# 派生指标计算
# ==============================================================================

def compute_focus_level(perception: PerceptionData) -> float:
    """
    基于感知数据估算用户专注度（0~1），**不依赖屏幕捕获**。

    计算逻辑（来自文档 02-intervention-decision/01.md 第1.4节）：
        focus_level = w1*(1-head_instability) + w2*blink_score + w3*(gaze_factor)

    - 头部稳定性：通过欧拉角绝对值估算（|pitch| + |yaw| 越小越专注）
    - 眨眼频率：偏差正常值(15次/分)越小越专注
    - 低头特殊处理：pitch < -40° 视为严重低头/看手机，pitch >= -40° 均视为专注

    Args:
        perception: 最新感知数据帧

    Returns:
        float，范围 [0, 1]，越大越专注
    """
    cfg = perception_config

    # --- 1. 头部稳定性评分 ---
    # 绝对角度偏转量归一化（超过60度视为完全分心）
    head_deviation = (abs(perception.head_pose.pitch) + abs(perception.head_pose.yaw)) / 60.0
    head_deviation = min(head_deviation, 1.0)

    # 低头阅读特例：pitch >= -40° 均视为专注，不惩罚
    # 严重低头（pitch < -40°）才视为走神
    if perception.head_pose.pitch < -40.0:
        head_deviation = 1.0  # 完全惩罚

    head_score = 1.0 - head_deviation

    # --- 2. 眨眼频率评分 ---
    normal_blink = cfg.FOCUS_BLINK_NORMAL_RATE  # 正常值 15次/分
    blink_deviation = abs(perception.blink_rate - normal_blink) / normal_blink
    blink_score = max(0.0, 1.0 - blink_deviation)

    # --- 3. 加权合并 ---
    # 由于无视线追踪数据，权重分配给前两项（w3=0直接忽略gaze_factor）
    w1 = cfg.FOCUS_HEAD_STABILITY_WEIGHT   # 0.65（头部稳定性）
    w2 = cfg.FOCUS_BLINK_RATE_WEIGHT       # 0.15（眨眼频率）
    # gaze_factor 默认 0.5（无数据时中性）
    gaze_factor = 0.5
    w3 = cfg.FOCUS_GAZE_DEVIATION_WEIGHT   # 0.20（视线偏移）

    focus = w1 * head_score + w2 * blink_score + w3 * gaze_factor
    focus = max(0.0, min(1.0, focus))

    logger.debug(
        f"[Perception] focus_level={focus:.3f} "
        f"(head={head_score:.2f}, blink={blink_score:.2f})"
    )
    return float(focus)


def compute_arousal(perception: PerceptionData) -> float:
    """
    基于音频特征和 AU 强度估算用户唤醒度（0~1）。

    来源：文档 02-intervention-decision/01.md 第1.4节第2点
        arousal = w4*norm(pitch) + w5*norm(energy) + w6*norm(blink) + w7*norm(AU_arousal)

    AU_arousal：AU4（皱眉）和 AU1（眉头上扬）与 arousal 正相关

    Args:
        perception: 感知数据帧

    Returns:
        float，范围 [0, 1]，越大越激动
    """
    # --- 音调归一化：200Hz=低，400Hz=高，600Hz封顶 ---
    pitch_score = min(1.0, max(0.0, (perception.audio.pitch - 150.0) / 350.0))

    # --- 能量已是 0~1 ---
    energy_score = min(1.0, max(0.0, perception.audio.loudness))

    # --- 眨眼频率：>25次/分为高唤醒（归一化到0~1） ---
    blink_score = min(1.0, max(0.0, perception.blink_rate / 40.0))

    # --- AU 唤醒相关（AU4 皱眉 + AU1 内眉上扬，均与 arousal 正相关） ---
    au_arousal = (perception.au.AU4 + perception.au.AU1) / 2.0

    # 加权合并（权重来自文档 1.4 节，可后续实验优化）
    arousal = (
        0.25 * pitch_score
        + 0.25 * energy_score
        + 0.20 * blink_score
        + 0.30 * au_arousal
    )
    arousal = max(0.0, min(1.0, arousal))

    logger.debug(
        f"[Perception] arousal={arousal:.3f} "
        f"(pitch={pitch_score:.2f}, energy={energy_score:.2f}, blink={blink_score:.2f}, au={au_arousal:.2f})"
    )
    return float(arousal)


# ==============================================================================
# 走神→专注模式触发规则引擎
# ==============================================================================

def check_attention_trigger(perception: PerceptionData) -> tuple[bool, str]:
    """
    走神模式下的规则引擎：判断是否需要切换到专注模式。

    触发条件（满足任一即切换，来自文档1.1.md）：
        1. 眨眼频率 > 25次/分（持续异常）
        2. 低头角度 < -40°（严重低头才判定为走神）
        3. AU4（皱眉）> 0.7
        4. AU小模型置信度 > 0.6 且情绪为负面

    Args:
        perception: 感知数据帧

    Returns:
        (triggered: bool, reason: str) — 是否触发及原因描述
    """
    cfg = perception_config
    au = perception.au

    # 条件1：眨眼频率异常
    if perception.blink_rate > cfg.ATTENTION_TRIGGER_BLINK_RATE:
        return True, f"眨眼频率过高: {perception.blink_rate:.1f}次/分 > {cfg.ATTENTION_TRIGGER_BLINK_RATE}"

    # 条件2：低头角度
    if perception.head_pose.pitch < cfg.ATTENTION_TRIGGER_HEAD_PITCH:
        return True, f"低头角度过大: pitch={perception.head_pose.pitch:.1f}°"

    # 条件3：AU4 强烈皱眉
    if au.AU4 > 0.7:
        return True, f"AU4(皱眉)过高: {au.AU4:.2f}"

    # 条件4：AU模型负面情绪 + 高置信度
    negative_emotions = {"sad", "angry", "fear", "disgust", "contempt"}
    if (
        au.confidence > cfg.ATTENTION_TRIGGER_CONFIDENCE
        and au.primary_emotion in negative_emotions
    ):
        return True, f"AU模型: {au.primary_emotion}(置信度={au.confidence:.2f})"

    return False, ""


# ==============================================================================
# 情感历史趋势分析
# 架构说明：Python 层不直连 MySQL（MySQL 归 Java 微服务管理）。
# 历史情感记录由 Java 在调用 /internal/v1/agent/invoke 时，
# 作为 emotion_history 字段序列化到请求体里传入，
# FastAPI 层解析后注入 AgentState.emotion_history，节点直接读取 state。
# ==============================================================================

def get_emotion_trend_from_state(
    emotion_history: list[dict[str, Any]],
) -> EmotionTrend:
    """
    从 AgentState.emotion_history 计算情绪趋势（无 I/O，纯计算）。

    这是 compute_emotion_trend 的别名，语义更清晰地表达数据来源是 state。

    Args:
        emotion_history: 由 Java API 传入并存入 state 的历史情感记录，
                         每条格式：{"timestamp": int(ms), "primary_emotion": str, "intensity": float}
    Returns:
        EmotionTrend 枚举值（上升/下降/平稳）
    """
    return compute_emotion_trend(emotion_history)


def compute_emotion_trend(history: list[dict[str, Any]]) -> EmotionTrend:
    """
    基于历史情感强度序列计算趋势方向。

    使用最小二乘线性回归斜率：
        斜率 > 0.1/分钟  → 上升趋势
        斜率 < -0.1/分钟 → 下降趋势
        否则              → 平稳

    Args:
        history: 历史情感记录列表（按时间升序），
                 每条含 {"timestamp": int(ms), "intensity": float}

    Returns:
        EmotionTrend 枚举值
    """
    min_points = 3
    # 数据点不足，默认平稳
    if len(history) < min_points:
        logger.debug(f"[Perception] 历史数据不足({len(history)}条)，趋势默认：平稳")
        return EmotionTrend.STABLE

    # 提取时间（转为分钟）和强度
    t0 = history[0]["timestamp"]
    xs = [(h["timestamp"] - t0) / 60000.0 for h in history]  # 毫秒→分钟
    ys = [h.get("intensity", 0.0) for h in history]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    numerator = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    denominator = sum((xs[i] - mean_x) ** 2 for i in range(n))

    if abs(denominator) < 1e-9:
        return EmotionTrend.STABLE

    slope = numerator / denominator  # 单位：强度变化/分钟

    RISING_THRESHOLD = 0.1
    FALLING_THRESHOLD = -0.1

    if slope > RISING_THRESHOLD:
        trend = EmotionTrend.RISING
    elif slope < FALLING_THRESHOLD:
        trend = EmotionTrend.FALLING
    else:
        trend = EmotionTrend.STABLE

    logger.debug(f"[Perception] 趋势分析: slope={slope:.4f}/分钟 → {trend.value}")
    return trend
