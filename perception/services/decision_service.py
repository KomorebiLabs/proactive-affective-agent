# backend/services/decision_service.py
import asyncio
from ai_assistant.utils import config
from services.chat_service import chat_service

class DecisionService:
    """
    【决策与主动关怀服务】
    职责：
    1. 接收来自视觉服务的感官数据，评估是否需要介入。
    2. 如果决策结果非"静默"，则指挥 ChatService 发起主动关怀。

    注意：核心决策逻辑已迁移至 Java Agent 服务端（Agent/main.py）。
    此文件作为本地兜底规则引擎，当 Agent 服务不可用时提供基础的关怀判断。
    """
    def __init__(self):
        print("[DecisionService] 决策服务已就绪（本地兜底模式）...")

    async def process_new_observation(self, behavior_desc, ui_emotion, complex_emotion, arousal):
        """
        [兜底逻辑] 基于规则的简单决策，判断是否需要发起关怀。
        实际生产环境由 Java Agent 服务做深度决策。

        注意：arousal 范围为 [0.0, 1.0]，阈值应在此范围内。
        """
        # 唤醒度过高 → 深度干预（arousal > 0.75，即 75% 以上唤醒度）
        if arousal > 0.75:
            print(f"[Decision] 唤醒度过高({arousal:.2f})，触发深度干预...")
            await chat_service.handle_proactive_care(
                behavior=behavior_desc,
                emotion=ui_emotion,
                is_cbt=True
            )
            return

        # 负面情绪明显 → 轻度关怀
        negative_keywords = ["沮丧", "难过", "疲惫", "焦虑", "恐惧", "生气"]
        if any(kw in ui_emotion for kw in negative_keywords):
            print(f"[Decision] 检测到负面情绪({ui_emotion})，触发轻度关怀...")
            await chat_service.handle_proactive_care(
                behavior=behavior_desc,
                emotion=ui_emotion,
                is_cbt=False
            )
            return

        # 其他情况静默观察
        print(f"[Decision] 当前状态({ui_emotion})无需干预。")

# 单例导出
decision_service = DecisionService()
