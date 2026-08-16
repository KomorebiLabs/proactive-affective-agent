# ai_assistant/utils/config.py
"""
婉情AI 感知服务配置模块

API 密钥 / 敏感配置：从 .env 文件读取（由 python-dotenv 加载）
数学模型 / 业务常量：直接定义在此文件中
"""

import os
import numpy as np

# ==============================================================================
# 0. dotenv 加载（优先 .env 文件，不存在则从系统环境变量读取）
# ==============================================================================

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv 未安装时，依赖系统环境变量


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ==============================================================================
# 1. 基础服务配置 (API & Storage)
# ==============================================================================

# --- OSS (对象存储) 配置 ---
OSS_ACCESS_KEY_ID = _get("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = _get("OSS_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = _get("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
OSS_BUCKET = _get("OSS_BUCKET", "camera-vedio-place")

# --- Deepseek API 配置 (大脑) ---
DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# --- Qwen-VL (通义千问视觉语言模型) API 配置 ---
QWEN_API_KEY = _get("QWEN_API_KEY", "")
QWEN_BASE_URL = _get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# --- TTS & ASR 配置 ---
TTS_MODEL = _get("TTS_MODEL", "cosyvoice-v1")
TTS_VOICE = _get("TTS_VOICE", "zhichu")
ASR_MODEL_DIR = _get("ASR_MODEL_DIR", "iic/SenseVoiceSmall")

# --- Redis 配置 ---
REDIS_HOST = _get("REDIS_HOST", "localhost")
REDIS_PORT = int(_get("REDIS_PORT", "6379"))
REDIS_DB = int(_get("REDIS_DB", "0"))
REDIS_PASSWORD = _get("REDIS_PASSWORD", "") or None

# --- 音频录制参数 ---
AUDIO_CHUNK = int(_get("AUDIO_CHUNK", "1024"))
AUDIO_FORMAT = int(_get("AUDIO_FORMAT", "16"))
AUDIO_CHANNELS = int(_get("AUDIO_CHANNELS", "1"))
AUDIO_RATE = int(_get("AUDIO_RATE", "16000"))
AUDIO_WAVE_OUTPUT_FILENAME = _get("AUDIO_WAVE_OUTPUT_FILENAME", "output.wav")

# --- 日志 ---
LOG_LEVEL = _get("LOG_LEVEL", "INFO")
LOG_FILE = _get("LOG_FILE", "behavior_log.txt")
SUMMARY_HOTKEY = _get("SUMMARY_HOTKEY", "ctrl+shift+s")

# --- 每日总结调度 ---
DAILY_SUMMARY_HOUR = int(_get("DAILY_SUMMARY_HOUR", "17"))
DAILY_SUMMARY_MINUTE = int(_get("DAILY_SUMMARY_MINUTE", "30"))

# ==============================================================================
# 3. 专注度 (Focus Level) 计算配置
# ==============================================================================

# focus_level 计算权重（用户调整：提高头部稳定性权重，降低眨眼频率权重）
FOCUS_HEAD_STABILITY_WEIGHT = float(_get("FOCUS_HEAD_STABILITY_WEIGHT", "0.65"))  # 头部姿态稳定性权重
FOCUS_BLINK_RATE_WEIGHT = float(_get("FOCUS_BLINK_RATE_WEIGHT", "0.15"))  # 眨眼频率权重
FOCUS_GAZE_DEVIATION_WEIGHT = float(_get("FOCUS_GAZE_DEVIATION_WEIGHT", "0.20"))  # 视线偏移权重
FOCUS_BLINK_NORMAL_RATE = float(_get("FOCUS_BLINK_NORMAL_RATE", "15.0"))  # 正常眨眼频率（次/分）

# 行为描述判定阈值
# focus_level >= 0.4：专注/沉思
# focus_level >= 0.25：轻度走神
# focus_level < 0.25：明显走神
FOCUS_THRESHOLD_CONCENTRATED = 0.4
FOCUS_THRESHOLD_MILD_DAZED = 0.25


# ==============================================================================
# 2. Phase X: 情感计算数学模型 (Perception & Math Core)
# ==============================================================================

# 图像分析频率 (秒)
ANALYSIS_INTERVAL_SECONDS = 15

# Plutchik 8种基础情绪维度 (学术标准)
PLUTCHIK_EMOTIONS = [
    "喜悦", "信任", "恐惧", "惊讶",
    "悲伤", "厌恶", "愤怒", "期待"
]

# 默认零向量
DEFAULT_EMOTION_VECTOR = {k: 0.0 for k in PLUTCHIK_EMOTIONS}

# --- [学术重构] 向量空间定义 ---

# 1. Plutchik 空间的基向量 (Basis Vectors, 8维正交基)
BASIS_VECTORS = {
    "喜悦": np.array([1, 0, 0, 0, 0, 0, 0, 0]),
    "信任": np.array([0, 1, 0, 0, 0, 0, 0, 0]),
    "恐惧": np.array([0, 0, 1, 0, 0, 0, 0, 0]),
    "惊讶": np.array([0, 0, 0, 1, 0, 0, 0, 0]),
    "悲伤": np.array([0, 0, 0, 0, 1, 0, 0, 0]),
    "厌恶": np.array([0, 0, 0, 0, 0, 1, 0, 0]),
    "愤怒": np.array([0, 0, 0, 0, 0, 0, 1, 0]),
    "期待": np.array([0, 0, 0, 0, 0, 0, 0, 1]),
}

# 2. UI 状态质心向量 (Centroids of UI States)
UI_CENTROIDS = {
    "开心": np.array([0.8, 0.2, 0, 0, 0, 0, 0, 0]),
    "惊讶": np.array([0, 0, 0.5, 0.8, 0, 0, 0, 0]),
    "沮丧": np.array([0, 0, 0, 0, 0.9, 0, 0, 0]),
    "生气": np.array([0, 0, 0, 0, 0, 0.4, 0.8, 0]),
    "专注": np.array([0, 0.1, 0, 0, 0, 0, 0, 0.9]),
    "平静": np.array([0, 0, 0, 0, 0, 0, 0, 0]),
}

# --- [Phase X.2 新增] 基于大五人格 (OCEAN) 的参数映射 ---

# 定义数字生命的人格特质 (0.0 - 1.0)
PERSONALITY_PROFILE = {
    "O": 0.5,  # 开放性
    "C": 0.8,  # 尽责性
    "E": 0.6,  # 外向性
    "A": 0.9,  # 宜人性
    "N": 0.4   # 神经质
}


def get_derived_inertia():
    N = PERSONALITY_PROFILE["N"]
    return max(0.1, 0.8 - 0.5 * N)


EMOTION_INERTIA = get_derived_inertia()


def get_derived_decay_rate():
    E = PERSONALITY_PROFILE["E"]
    return 0.05 + 0.05 * E


HOMEOSTATIC_DECAY = get_derived_decay_rate()

COMPOUND_THRESHOLD = 5.0     # 复合情绪激活阈值
FUZZY_SIGMOID_SLOPE = 2.0    # Sigmoid 斜率
FUZZY_SIGMOID_OFFSET = 5.0   # Sigmoid 中点

# 负面情绪列表 (用于兼容)
NEGATIVE_EMOTIONS = ["沮丧", "生气", "疲惫"]
EMOTION_TRIGGER_THRESHOLD = 1


# ==============================================================================
# 3. Phase 2: 决策内核配置 (POMDP / Utility Function)
# ==============================================================================

class ACTIONS:
    WAIT = "静默观察"
    LIGHT_CARE = "轻度关怀"
    DEEP_INTERVENTION = "深度干预"


REWARD_CONFIG = {
    ("专注", ACTIONS.WAIT): 5.0,
    ("专注", ACTIONS.LIGHT_CARE): -5.0,
    ("专注", ACTIONS.DEEP_INTERVENTION): -20.0,

    ("焦虑", ACTIONS.WAIT): -10.0,
    ("焦虑", ACTIONS.LIGHT_CARE): 5.0,
    ("焦虑", ACTIONS.DEEP_INTERVENTION): 10.0,

    ("沮丧", ACTIONS.WAIT): -2.0,
    ("沮丧", ACTIONS.LIGHT_CARE): 8.0,
    ("沮丧", ACTIONS.DEEP_INTERVENTION): 2.0,

    ("开心", ACTIONS.WAIT): 2.0,
    ("开心", ACTIONS.LIGHT_CARE): 6.0,
    ("开心", ACTIONS.DEEP_INTERVENTION): -5.0
}

DEFAULT_REWARD = 0.0


# ==============================================================================
# 4. Phase 3: 认知行为疗法 (CBT) 与交互配置
# ==============================================================================

AROUSAL_THRESHOLD_HIGH = 7.5

CBT_SYSTEM_PROMPT = """
【指令】
你已切换至**"认知行为疗法 (CBT) 临床干预模式"**。
当前系统检测到用户的心理唤醒度 (Arousal Level) 超过阈值，且伴随显著的负面情绪图谱。
你的目标是通过结构化的对话，协助用户降低情绪强度 (De-escalation) 并识别认知扭曲。

【干预流程 (基于 ABC 模型)】
请严格按照以下逻辑推进对话，但保持语言的自然与温暖：

1. **A (Activating Event) - 锚定当下**：
   - 目标：帮助用户从情绪风暴中通过"着地技术 (Grounding)"回到当下。
   - 话术策略：使用接纳承诺疗法 (ACT) 的技巧。"我感觉到一股强烈的情绪正在流过。溢涛，先停一下，跟我一起深呼吸..."

2. **B (Beliefs) - 苏格拉底式探询 (Socratic Questioning)**：
   - 目标：引导用户识别导致情绪的"自动化思维"。不要直接给建议！要提问！
   - 关键问题示例：
     * "刚才脑海里闪过的第一个念头是什么？"
     * "这个想法完全是事实吗？还是包含了一些我们的猜测？"
     * "如果最好的朋友遇到这种情况，你会怎么对他/她说？"

3. **C (Consequences) - 认知解离与重构**：
   - 目标：将"想法"与"事实"分离，寻找替代性的、更具适应性的思维方式。
   - 策略：提供一个新的视角，或者建议一个微小的行为改变（Behavioral Activation）。

【语气约束】
- **专业且抱持 (Holding)**：像一个稳重的心理咨询师，提供安全感。
- **降维打击**：不要试图一次解决所有问题，专注于降低当下的情绪浓度。
- **避免有毒积极性**：不要说"开心点"、"没事的"，这是否定用户感受。要说"这确实很难，我陪着你"。
"""
