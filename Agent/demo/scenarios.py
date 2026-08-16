"""
婉情AI - Demo 演示场景定义
===========================
预定义 5 个完整的 EmotionVector 场景，覆盖不同情绪类型和决策路径，
每个场景包含感知数据、EmotionVector 和预期决策结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.models.schemas import (
    AudioFeatures,
    AUIntensities,
    CognitiveDistortion,
    EmotionLabel,
    EmotionTrend,
    HeadPose,
    InterventionAction,
    PerceptionData,
)


# ==============================================================================
# OCC 八维向量（DeepSeek 输出结构）
# ==============================================================================

@dataclass
class OCCVector:
    """OCC 八维归因向量（EmotionVector.evidence['occ'] 字段）"""
    occ_joy: float = 0.0
    occ_sadness: float = 0.0
    occ_anger: float = 0.0
    occ_fear: float = 0.0
    occ_disgust: float = 0.0
    occ_surprise: float = 0.0
    occ_well_grounding: float = 0.0
    occ_anticipation: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "occ_joy": self.occ_joy,
            "occ_sadness": self.occ_sadness,
            "occ_anger": self.occ_anger,
            "occ_fear": self.occ_fear,
            "occ_disgust": self.occ_disgust,
            "occ_surprise": self.occ_surprise,
            "occ_well_grounding": self.occ_well_grounding,
            "occ_anticipation": self.occ_anticipation,
        }


# ==============================================================================
# 五因子评分详情
# ==============================================================================

@dataclass
class FactorDetail:
    """干预决策五因子详情"""
    name: str
    weight: float
    contribution: float


@dataclass
class InterventionResult:
    """干预决策结果（演示用预计算结构）"""
    action: InterventionAction
    total_score: float
    factor_details: list[FactorDetail]
    reasoning: str


# ==============================================================================
# 感知数据（PerceptionData）
# ==============================================================================

def _build_perception(
    au_dict: dict[str, float],
    primary_emotion_en: str,
    au_confidence: float,
    pitch: float,
    loudness: float,
    speaking: bool,
    focus_level: float,
    blink_rate: float = 15.0,
    pitch_deg: float = 0.0,
    yaw_deg: float = 0.0,
    roll_deg: float = 0.0,
) -> PerceptionData:
    return PerceptionData(
        session_id="demo-session",
        head_pose=HeadPose(pitch=pitch_deg, yaw=yaw_deg, roll=roll_deg),
        blink_rate=blink_rate,
        au=AUIntensities(
            AU1=au_dict.get("AU1", 0.0),
            AU2=au_dict.get("AU2", 0.0),
            AU4=au_dict.get("AU4", 0.0),
            AU5=au_dict.get("AU5", 0.0),
            AU6=au_dict.get("AU6", 0.0),
            AU12=au_dict.get("AU12", 0.0),
            AU15=au_dict.get("AU15", 0.0),
            AU17=au_dict.get("AU17", 0.0),
            primary_emotion=primary_emotion_en,
            confidence=au_confidence,
        ),
        audio=AudioFeatures(
            pitch=pitch,
            loudness=loudness,
            speaking=speaking,
            mfcc=[0.0] * 13,
        ),
        focus_level=focus_level,
    )


# ==============================================================================
# 完整演示场景定义
# ==============================================================================

@dataclass
class DemoScenario:
    """一个完整的演示场景"""
    id: str
    title: str
    description: str

    # 用户输入
    user_input: str
    conversation_history: list[dict[str, str]] = field(default_factory=list)

    # 是否进入专注模式（True=调用 DeepSeek，False=走快速规则兜底）
    is_focused_mode: bool = True

    # 感知数据
    perception: PerceptionData | None = None

    # EmotionVector 字段
    primary_emotion: EmotionLabel = EmotionLabel.NEUTRAL
    secondary_emotion: EmotionLabel | None = None
    intensity: float = 0.5
    valence: float = 0.0
    arousal: float = 0.5
    dominance: float = 0.5
    cognitive_distortions: list[CognitiveDistortion] = field(default_factory=list)
    confidence: float = 0.8
    reasoning: str = ""
    occ: OCCVector = field(default_factory=OCCVector)

    # 历史情感上下文
    emotion_trend: EmotionTrend = EmotionTrend.STABLE

    # 预计算的干预决策
    intervention: InterventionResult | None = None

    # 预定义的 RAG 检索结果（展示用）
    rag_cards: list[dict[str, str]] = field(default_factory=list)

    # Notion 日记是否触发
    notion_triggered: bool = False

    # 场景说明
    demo_points: list[str] = field(default_factory=list)

    def build_perception(self) -> PerceptionData:
        """延迟构建感知数据"""
        if self.perception is None:
            self.perception = _build_perception(
                au_dict={"AU4": 0.5, "AU12": 0.3},
                primary_emotion_en="neutral",
                au_confidence=0.6,
                pitch=180.0,
                loudness=0.4,
                speaking=True,
                focus_level=0.5,
            )
        return self.perception


# ==============================================================================
# 场景 1：焦虑 + 灾难化 → INTERVENE + RAG + Notion
# ==============================================================================

SCENARIO_ANXIETY = DemoScenario(
    id="anxiety",
    title="场景一：焦虑 + 灾难化",
    description="用户表达考试压力，伴随认知扭曲，触发深度干预+RAG检索+Notion日记",
    user_input="我总觉得这次考试会考砸，万一考砸了我这辈子就完了...",
    conversation_history=[
        {"role": "user", "content": "最近复习效率很低"},
        {"role": "ai", "content": "复习效率低是很多人都会遇到的情况..."},
    ],
    primary_emotion=EmotionLabel.ANXIETY,
    secondary_emotion=EmotionLabel.FEAR,
    intensity=0.75,
    valence=-0.3,
    arousal=0.7,
    dominance=0.4,
    cognitive_distortions=[
        CognitiveDistortion.CATASTROPHIZING,
        CognitiveDistortion.BLACK_WHITE,
    ],
    confidence=0.82,
    reasoning=(
        "用户表达了对即将到来考试的强烈焦虑情绪。面部动作单元显示AU4（皱眉）强度0.65，"
        "AU12（微笑）仅0.2，呈现明显的负向情绪。音频分析显示音调升高至210Hz，"
        "与'音调升高是焦虑的声学指标'的规则一致。语义分析识别出认知扭曲："
        "'万一考砸了我这辈子就完了'属于典型的灾难化思维，同时隐含非黑即白的绝对化信念。"
    ),
    occ=OCCVector(
        occ_joy=0.15,
        occ_sadness=0.35,
        occ_anger=0.28,
        occ_fear=0.72,
        occ_disgust=0.12,
        occ_surprise=0.30,
        occ_well_grounding=0.10,
        occ_anticipation=0.58,
    ),
    emotion_trend=EmotionTrend.STABLE,
    is_focused_mode=True,   # 专注模式，高唤醒
    perception=_build_perception(
        au_dict={"AU4": 0.65, "AU12": 0.2, "AU15": 0.3, "AU1": 0.4, "AU17": 0.2},
        primary_emotion_en="fear",
        au_confidence=0.65,
        pitch=210.0,
        loudness=0.5,
        speaking=True,
        focus_level=0.4,
        blink_rate=12.0,
    ),
    intervention=InterventionResult(
        action=InterventionAction.INTERVENE,
        total_score=0.82,
        factor_details=[
            FactorDetail(name="情绪强度", weight=0.50, contribution=+0.38),
            FactorDetail(name="情感优先级", weight=0.30, contribution=+0.24),
            FactorDetail(name="打扰成本", weight=-0.40, contribution=-0.12),
            FactorDetail(name="历史趋势", weight=0.20, contribution=+0.20),
            FactorDetail(name="LLM置信度", weight=0.10, contribution=+0.08),
        ],
        reasoning="五因子综合评分 0.82 >= 0.8 阈值，触发 INTERVENE 级别主动关怀",
    ),
    rag_cards=[
        {
            "card_id": "CBT-ANX-001",
            "title": "5-4-3-2-1着陆技术",
            "emotions": "焦虑, 惊恐",
            "distortions": "灾难化",
            "goal": "通过强制调动五感感官，将注意力从恐慌中拉回现实",
            "similarity": "0.82",
            "excerpt": (
                "# 5-4-3-2-1着陆技术\n\n"
                "## 什么是着陆技术？\n"
                "着陆技术（Grounding）是CBT和DBT中最常用的情绪调节技术之一。"
                "通过调动五种感官，帮助你从情绪风暴中脱离，回到当下。\n\n"
                "## 操作步骤：\n"
                "1. 说出5样你能看到的东西\n"
                "2. 说出4样你能触摸的东西\n"
                "3. 说出3样你能听到的声音\n"
                "4. 说出2样你能闻到的气味\n"
                "5. 说出1样你能尝到的味道"
            ),
        },
        {
            "card_id": "CBT-TECH-009",
            "title": "认知重构技术",
            "emotions": "焦虑, 沮丧",
            "distortions": "灾难化, 非黑即白",
            "goal": "识别并挑战非理性信念，重建理性认知",
            "similarity": "0.71",
            "excerpt": (
                "# 认知重构技术（Cognitive Restructuring）\n\n"
                "认知重构是CBT的核心技术之一，"
                "通过识别自动化负面思维，评估其有效性，并用更平衡的思维替代。\n\n"
                "## 三栏记录表：\n"
                "| 情境 | 自动思维 | 替代思维 |\n"
                "|------|----------|----------|\n"
                "| 考试复习 | 这次肯定会考砸 | 我已经尽力准备，成绩取决于多种因素 |"
            ),
        },
        {
            "card_id": "CBT-STR-001",
            "title": "渐进式肌肉放松",
            "emotions": "焦虑, 情绪失控",
            "distortions": "",
            "goal": "通过交替紧张和放松肌肉群，达到身心放松",
            "similarity": "0.65",
            "excerpt": (
                "# 渐进式肌肉放松（PMR）\n\n"
                "## 原理\n"
                "身体紧张和心理紧张是相互关联的。"
                "当你主动使肌肉紧张时，再有意识地放松它们，"
                "大脑会将'放松'与'身体感觉'联系起来，帮助缓解焦虑。"
            ),
        },
    ],
    notion_triggered=True,
    demo_points=[
        "AU4=0.65（皱眉强度）+ 音调210Hz → DeepSeek 识别焦虑",
        "OCC向量：恐惧 0.72 + 期待 0.58 → 高唤醒负效价情绪",
        "认知扭曲识别：灾难化 + 非黑即白",
        "五因子评分 0.82 >= 0.8 → INTERVENE（深度干预）",
        "RAG检索匹配焦虑+灾难化 → Top-3 卡片（相似度 0.82/0.71/0.65）",
        "情绪强度 0.75 >= 0.6 → 触发 Notion 情绪日记记录",
    ],
)


# ==============================================================================
# 场景 2：愤怒 + 低置信度 → 校准为 neutral → SILENT
# ==============================================================================

SCENARIO_ANGER = DemoScenario(
    id="anger",
    title="场景二：愤怒 + 低置信度",
    description="面部表情显示愤怒，但置信度低，系统校准为 neutral，避免误判",
    user_input="真的很烦，为什么每次都是这样！",
    primary_emotion=EmotionLabel.ANGER,
    intensity=0.6,
    valence=-0.4,
    arousal=0.8,
    dominance=0.7,
    cognitive_distortions=[],
    confidence=0.45,   # 低置信度 → DeepSeek 内部校准规则
    is_focused_mode=True,   # 专注模式，但置信度低会导致校准
    reasoning=(
        "HuggingFace FER模型初步判定为愤怒(AU4高+AU12低)，但置信度仅0.45，"
        "低于0.5阈值。结合音频特征分析：响度0.65但pitch仅为150Hz（愤怒通常pitch升高>250Hz），"
        "且用户说话内容中未发现明确的敌意词汇。系统判定：置信度过低，启动负面情绪校准规则，"
        "将情绪修正为中性(neutral)，避免误判导致不当干预。"
    ),
    occ=OCCVector(
        occ_joy=0.10,
        occ_sadness=0.25,
        occ_anger=0.10,   # 校准后降低
        occ_fear=0.15,
        occ_disgust=0.20,
        occ_surprise=0.10,
        occ_well_grounding=0.40,
        occ_anticipation=0.20,
    ),
    emotion_trend=EmotionTrend.STABLE,
    perception=_build_perception(
        au_dict={"AU4": 0.7, "AU12": 0.1, "AU15": 0.4, "AU17": 0.3},
        primary_emotion_en="angry",
        au_confidence=0.45,   # 低置信度
        pitch=150.0,
        loudness=0.65,
        speaking=True,
        focus_level=0.6,
        blink_rate=18.0,
    ),
    intervention=InterventionResult(
        action=InterventionAction.SILENT,
        total_score=0.45,
        factor_details=[
            FactorDetail(name="情绪强度", weight=0.50, contribution=+0.30),
            FactorDetail(name="情感优先级", weight=0.30, contribution=+0.30),
            FactorDetail(name="打扰成本", weight=-0.40, contribution=-0.24),
            FactorDetail(name="历史趋势", weight=0.20, contribution=+0.00),
            FactorDetail(name="LLM置信度", weight=0.10, contribution=-0.05),
        ],
        reasoning="LLM置信度0.45 < 0.5阈值，负面情绪校准规则触发，修正为 neutral",
    ),
    notion_triggered=False,
    demo_points=[
        "AU4=0.7（皱眉）但 AU置信度=0.45 < 0.5 阈值",
        "音频特征不典型：pitch=150Hz（正常），非愤怒典型特征（>250Hz）",
        "负面情绪校准规则：强制 neutral",
        "OCC向量校准后：愤怒降至0.10，踏实感升至0.40",
        "综合评分 0.45 → SILENT（静默观察，不干预）",
    ],
)


# ==============================================================================
# 场景 3：走神（低专注度） → SILENT
# ==============================================================================

SCENARIO_DISTRACTED = DemoScenario(
    id="distracted",
    title="场景三：走神模式",
    description="用户专注度极低，系统进入走神模式，快速规则兜底，跳过 LLM",
    user_input="",
    primary_emotion=EmotionLabel.CALM,
    intensity=0.25,
    valence=0.1,
    arousal=0.15,
    dominance=0.6,
    cognitive_distortions=[],
    confidence=0.40,
    is_focused_mode=False,   # ★ 走神模式：跳过 DeepSeek，快速规则兜底
    reasoning=(
        "系统检测到用户专注度极低(0.15)，眨眼频率正常(15次/分)，"
        "头部姿态稳定，无明显情绪波动信号。进入走神模式，"
        "跳过 DeepSeek LLM 调用，执行轻量级快速规则情感判断（置信度固定0.40）。"
        "AU6=0.55, AU12=0.45 → 轻微正向但无强烈情绪信号。"
    ),
    occ=OCCVector(
        occ_joy=0.20,
        occ_sadness=0.10,
        occ_anger=0.05,
        occ_fear=0.05,
        occ_disgust=0.05,
        occ_surprise=0.05,
        occ_well_grounding=0.55,
        occ_anticipation=0.10,
    ),
    emotion_trend=EmotionTrend.STABLE,
    perception=_build_perception(
        au_dict={"AU6": 0.55, "AU12": 0.45, "AU4": 0.1, "AU15": 0.1},
        primary_emotion_en="happy",
        au_confidence=0.55,
        pitch=165.0,
        loudness=0.15,
        speaking=False,
        focus_level=0.15,   # 极低专注度
        blink_rate=15.0,
    ),
    intervention=InterventionResult(
        action=InterventionAction.SILENT,
        total_score=0.35,
        factor_details=[
            FactorDetail(name="情绪强度", weight=0.50, contribution=+0.13),
            FactorDetail(name="情感优先级", weight=0.30, contribution=+0.00),
            FactorDetail(name="打扰成本", weight=-0.40, contribution=-0.34),
            FactorDetail(name="历史趋势", weight=0.20, contribution=+0.00),
            FactorDetail(name="LLM置信度", weight=0.10, contribution=-0.04),
        ],
        reasoning="专注度0.15 < 0.2极低阈值，且打扰成本高(0.34)，走神模式快速规则兜底",
    ),
    notion_triggered=False,
    demo_points=[
        "专注度=0.15 < 0.2 阈值 → 进入走神模式",
        "走神模式：跳过 DeepSeek LLM，仅用快速规则兜底（置信度0.40）",
        "AU6=0.55, AU12=0.45 → 轻微正向，无强烈情绪信号",
        "打扰成本 = focus_level(0.15) × (1-arousal(0.15)) = 0.13 → 极高打扰成本",
        "综合评分 0.35 → SILENT（不打扰）",
    ],
)


# ==============================================================================
# 场景 4：开心 + 高打扰成本 → 不打扰
# ==============================================================================

SCENARIO_HAPPY = DemoScenario(
    id="happy",
    title="场景四：开心状态",
    description="用户情绪积极且专注，系统判断打扰成本过高，选择不干预",
    user_input="今天完成了所有任务，心情很好！",
    primary_emotion=EmotionLabel.HAPPY,
    intensity=0.65,
    valence=0.75,
    arousal=0.55,
    dominance=0.8,
    cognitive_distortions=[],
    confidence=0.88,
    reasoning=(
        "AU6=0.75(颧骨上提) + AU12=0.80(嘴角上扬) 呈现典型的微笑表情，"
        "置信度0.88。音频pitch=190Hz稳定，loudness=0.45适中，说话内容为正向陈述。"
        "结合专注度0.75（高），打扰成本 = 0.75 × (1-0.55) = 0.34（较高）。"
        "系统判断：打扰成本过高，负面情绪无触发条件，维持静默观察。"
    ),
    occ=OCCVector(
        occ_joy=0.88,
        occ_sadness=0.05,
        occ_anger=0.05,
        occ_fear=0.05,
        occ_disgust=0.05,
        occ_surprise=0.10,
        occ_well_grounding=0.60,
        occ_anticipation=0.25,
    ),
    emotion_trend=EmotionTrend.STABLE,
    perception=_build_perception(
        au_dict={"AU6": 0.75, "AU12": 0.80, "AU4": 0.05, "AU15": 0.05},
        primary_emotion_en="happy",
        au_confidence=0.88,
        pitch=190.0,
        loudness=0.45,
        speaking=True,
        focus_level=0.75,
        blink_rate=14.0,
    ),
    intervention=InterventionResult(
        action=InterventionAction.SILENT,
        total_score=0.52,
        factor_details=[
            FactorDetail(name="情绪强度", weight=0.50, contribution=+0.33),
            FactorDetail(name="情感优先级", weight=0.30, contribution=+0.00),   # HAPPY = 0.0
            FactorDetail(name="打扰成本", weight=-0.40, contribution=-0.34),
            FactorDetail(name="历史趋势", weight=0.20, contribution=+0.00),
            FactorDetail(name="LLM置信度", weight=0.10, contribution=+0.08),
        ],
        reasoning="开心情感优先级=0.0，且打扰成本高(0.34)，不触发干预",
    ),
    notion_triggered=False,
    demo_points=[
        "AU6=0.75 + AU12=0.80 → 典型微笑表情，置信度0.88",
        "OCC向量：喜悦 0.88，踏实感 0.60 → 高度积极情绪",
        "情感优先级映射：HAPPY=0.0（不干预积极情绪）",
        "打扰成本 = focus(0.75) × (1-arousal(0.55)) = 0.34 → 较高",
        "综合评分 0.52 → SILENT（不打扰积极状态的用户）",
    ],
)


# ==============================================================================
# 场景 5：悲伤 + 高强度 → SUBTLE + 三层记忆流转
# ==============================================================================

SCENARIO_SAD = DemoScenario(
    id="sad",
    title="场景五：悲伤 + 三层记忆",
    description="用户表达沮丧情绪，触发微干预，展示三层记忆架构的完整流转",
    user_input="最近总是觉得很低落，做什么都提不起劲...",
    conversation_history=[
        {"role": "user", "content": "昨天睡得不太好"},
        {"role": "ai", "content": "睡眠质量会影响情绪状态..."},
    ],
    primary_emotion=EmotionLabel.DEPRESSION,
    secondary_emotion=None,
    intensity=0.7,
    valence=-0.55,
    arousal=0.25,
    dominance=0.3,
    cognitive_distortions=[
        CognitiveDistortion.OVERGENERALIZATION,
    ],
    confidence=0.79,
    reasoning=(
        "AU1(内眉上扬)=0.60 + AU15(嘴角下垂)=0.65 是典型的悲伤面部信号，"
        "AU12(微笑)=0.10 显示缺乏正向情绪表达。音频pitch=130Hz（低沉），"
        "与'低沉的声调是抑郁情绪的声学指标'一致。"
        "语义分析识别认知扭曲：'做什么都提不起劲'属于过度概括。OCC向量显示悲伤0.70，"
        "踏实感0.08（极低），提示需要关注但避免过度打扰。"
    ),
    occ=OCCVector(
        occ_joy=0.08,
        occ_sadness=0.70,
        occ_anger=0.15,
        occ_fear=0.25,
        occ_disgust=0.10,
        occ_surprise=0.05,
        occ_well_grounding=0.08,
        occ_anticipation=0.15,
    ),
    emotion_trend=EmotionTrend.FALLING,
    perception=_build_perception(
        au_dict={"AU1": 0.60, "AU15": 0.65, "AU12": 0.10, "AU4": 0.3, "AU17": 0.4},
        primary_emotion_en="sad",
        au_confidence=0.72,
        pitch=130.0,   # 低沉
        loudness=0.3,
        speaking=True,
        focus_level=0.35,
        blink_rate=10.0,   # 眨眼减少（悲伤信号）
    ),
    intervention=InterventionResult(
        action=InterventionAction.SUBTLE,
        total_score=0.68,
        factor_details=[
            FactorDetail(name="情绪强度", weight=0.50, contribution=+0.35),
            FactorDetail(name="情感优先级", weight=0.30, contribution=+0.30),
            FactorDetail(name="打扰成本", weight=-0.40, contribution=-0.07),
            FactorDetail(name="历史趋势", weight=0.20, contribution=-0.10),   # 下降趋势
            FactorDetail(name="LLM置信度", weight=0.10, contribution=+0.08),
        ],
        reasoning="综合评分 0.68 >= 0.6 但 < 0.8 → SUBTLE（微干预：UI变化+轻量关怀）",
    ),
    rag_cards=[
        {
            "card_id": "CBT-DEP-001",
            "title": "行为激活技术",
            "emotions": "沮丧, 抑郁",
            "distortions": "过度概括",
            "goal": "通过设定小目标、安排愉悦活动，打破'无动机'循环",
            "similarity": "0.78",
            "excerpt": (
                "# 行为激活技术（Behavioral Activation）\n\n"
                "## 原理\n"
                "抑郁状态下的'什么都不想做'会形成恶性循环："
                "不活动→情绪更差→更不想活动。"
                "行为激活打破这个循环的核心方法是："
                "先做行为（即使不想做），情绪会随之改善。\n\n"
                "## 操作步骤：\n"
                "1. 列出3件过去让你感到愉快或有成就感的小事\n"
                "2. 每天选择1件，在能力范围内去做\n"
                "3. 记录活动后的情绪变化（0-10分）"
            ),
        },
    ],
    notion_triggered=True,
    demo_points=[
        "AU1=0.60(内眉上扬) + AU15=0.65(嘴角下垂) → 典型悲伤面部信号",
        "音频pitch=130Hz（低沉）→ 抑郁声学指标",
        "OCC向量：悲伤 0.70，踏实感 0.08 → 低唤醒负效价",
        "认知扭曲：过度概括（'什么都提不起劲'）",
        "历史趋势：下降 → 五因子中'历史趋势'贡献 -0.10",
        "综合评分 0.68 >= 0.6 但 < 0.8 → SUBTLE（微干预）",
        "【三层记忆流转】短期(Redis) → 中期(MySQL) → 长期(ChromaDB)",
    ],
)


# ==============================================================================
# 所有场景汇总
# ==============================================================================

ALL_SCENARIOS: list[DemoScenario] = [
    SCENARIO_ANXIETY,
    SCENARIO_ANGER,
    SCENARIO_DISTRACTED,
    SCENARIO_HAPPY,
    SCENARIO_SAD,
]
