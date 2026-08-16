from __future__ import annotations

"""
婉情AI - collect_perception LangGraph 节点
==========================================
职责：从 Redis 读取感知微服务最近写入的多模态感知数据，
      存入 AgentState.latest_perception，供后续 fuse_emotion 使用。

【Qwen-VL 集成说明】
  专注模式触发时（check_attention_trigger 返回 True），
  本节点负责从 Redis 读取摄像头帧，调用 Qwen-VL-Max 进行图像理解，
  结果存入 state["qwen_analysis"]，供 fuse_emotion 融合使用。

  调用频率受 perception_config.QWEN_ANALYSIS_INTERVAL_SECONDS 控制（默认 15 秒），
  避免过于频繁的 API 调用。

设计说明：
  感知数据由感知微服务（MediaPipe + openSMILE + HuggingFace AU）以 10Hz 频率
  写入 Redis（key: emotion:realtime:{session_id}）。本节点负责读取并注入 state。

  分离为独立节点的理由（文档 01-emotion-recognition/1.1.md）：
    - 走神模式（默认）：仅读取感知数据，不触发 LLM 分析
    - 专注模式：感知数据加上 qwen_analysis 一起供 fuse_emotion 使用
    - 将感知数据读取独立出来，确保 fuse_emotion 始终有最新数据可用

依赖工具：Redis 客户端（复用 perception.py 中的连接池）
"""

"""
collect_perception_node 是婉晴AI项目中 LangGraph 决策引擎 的一个节点，
负责从 Redis 读取感知微服务写入的最新多模态感知数据（面部、音频、姿态等），
并将这些数据存入 Agent 状态 AgentState 的 latest_perception 字段中，供后续 fuse_emotion 等节点使用。

该节点的设计遵循了 关注点分离 原则：将感知数据的获取独立出来，
既可以在走神模式下仅使用感知数据进行简单规则判断，
也可以在专注模式下结合多模态大模型（Qwen-VL-Max）的分析结果进行情感融合。
"""


import time
from typing import Any

from config import perception_config
from src.agent.state import AgentState
from src.emotion.analyzer import analyze_scene_with_qwen
from src.emotion.perception import (
    check_attention_trigger,
    get_focus_mode,
    get_last_qwen_call_time,
    get_latest_camera_frame,
    get_latest_perception,
    set_focus_mode,
    set_last_qwen_call_time,
)
from src.models.schemas import HeadPose, PerceptionData, QwenAnalysis
from src.utils.logger import logger


# ==============================================================================
# 注意：Qwen-VL 调用间隔使用 Redis 管理（见 src/emotion/perception.py）
# 以支持 Python Agent 多 worker 进程的并发场景
# ==============================================================================


async def collect_perception_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph collect_perception 节点：从 Redis 读取最新感知数据。

    【Qwen-VL 集成】
      当专注模式触发（check_attention_trigger 返回 True）且距上次调用 >= 15 秒时，
      自动从 Redis 读取摄像头帧 Base64，调用 analyze_scene_with_qwen，
      结果存入 state["qwen_analysis"] 和 state["is_focused_mode"]。

    数据流：
      session_id (from state)
        ↓
      Redis GET emotion:realtime:{session_id}
        ↓
      PerceptionData (validated Pydantic model)
        ↓
      [专注模式触发?] → Redis GET camera:frame:{session_id} → Qwen-VL 分析
        ↓
      latest_perception, qwen_analysis, is_focused_mode (写入 state)

    Returns:
        dict，包含：
          - latest_perception: PerceptionData | None
          - qwen_analysis: QwenAnalysis | None（专注模式触发时）
          - is_focused_mode: bool
    """
    session_id = state.get("session_id", "unknown")
    logger.debug(f"[collect_perception] === 采集感知数据: session={session_id} ===")

    try:
        # 读取感知数据
        perception = await get_latest_perception(session_id)

        if perception is None:
            logger.debug(f"[collect_perception] Redis 中无感知数据: session={session_id}")
            return {"latest_perception": None, "is_focused_mode": False}

        logger.debug(
            f"[collect_perception] 读取成功: "
            f"AU4={perception.au.AU4:.2f}, "
            f"focus={perception.focus_level:.2f}, "
            f"blink={perception.blink_rate:.1f}/min, "
            f"pitch={perception.audio.pitch:.1f}Hz"
        )

        # 构建返回字典（基础字段）
        result: dict[str, Any] = {
            "latest_perception": perception,
            "is_focused_mode": False,
        }

        # =======================================================================
        # Qwen-VL 集成：专注模式触发检测
        # =======================================================================
        # 从 Redis 读取当前专注模式状态（支持多 worker 进程）
        current_focus = await get_focus_mode(session_id)
        triggered, trigger_reason = check_attention_trigger(perception)

        if triggered:
            logger.info(f"[collect_perception] 专注模式触发: {trigger_reason}")

            # 检查调用间隔（避免过于频繁）
            interval_seconds = perception_config.QWEN_ANALYSIS_INTERVAL_SECONDS
            last_call = await get_last_qwen_call_time(session_id)
            now = time.time()

            if now - last_call >= interval_seconds:
                # 更新调用时间记录（写入 Redis，支持多 worker 进程）
                await set_last_qwen_call_time(session_id)

                # 从 Redis 读取摄像头帧 Base64
                frame_base64 = await get_latest_camera_frame(session_id)

                if frame_base64:
                    logger.info(f"[collect_perception] 开始 Qwen-VL 分析，帧长度={len(frame_base64)}")

                    # 调用 Qwen-VL-Max 图像理解（async，不阻塞主线程）
                    qwen_result = await analyze_scene_with_qwen(
                        image_base64=frame_base64,
                        au=perception.au,
                        head_pose=HeadPose(
                            pitch=perception.head_pose.pitch,
                            yaw=perception.head_pose.yaw,
                            roll=perception.head_pose.roll,
                        ),
                        blink_rate=perception.blink_rate,
                        session_id=session_id,
                    )

                    result["qwen_analysis"] = qwen_result
                    result["is_focused_mode"] = True
                    # 同步更新 Redis 专注模式状态（支持多 worker）
                    await set_focus_mode(session_id, True)

                    logger.info(
                        f"[collect_perception] Qwen-VL 分析完成: "
                        f"emotion={qwen_result.primary_emotion}, "
                        f"intensity={qwen_result.emotion_intensity:.2f}, "
                        f"confidence={qwen_result.confidence:.2f}"
                    )
                else:
                    logger.warning(f"[collect_perception] 摄像头帧为空，跳过 Qwen-VL 分析")
                    # 帧为空但触发专注模式，仍标记状态
                    await set_focus_mode(session_id, True)
            else:
                logger.debug(
                    f"[collect_perception] 距上次调用不足 {interval_seconds}s "
                    f"(已过 {now - last_call:.1f}s)，跳过 Qwen-VL 分析"
                )
                # 即使跳过分析，也标记为专注模式（保持状态一致性）
                result["is_focused_mode"] = True
                await set_focus_mode(session_id, True)
        elif current_focus and not triggered:
            # 情绪趋于平静，自动退出专注模式
            logger.info(f"[collect_perception] 情绪平稳，退出专注模式")
            await set_focus_mode(session_id, False)
            result["is_focused_mode"] = False
        else:
            result["is_focused_mode"] = current_focus

        return result

    except Exception as e:
        logger.error(f"[collect_perception] 读取感知数据失败: {e}")
        return {"latest_perception": None, "is_focused_mode": False}
