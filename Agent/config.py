"""
婉情AI智能体 - 统一配置管理
==============================
所有配置从环境变量加载，提供类型安全的默认值。
新增配置项请在此文件中统一定义，避免硬编码散落在各处。

环境变量加载：仅从 .env 文件读取（KEY=VALUE 格式）。
secrets.env 已废弃，所有密钥直接写在 .env 中。
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# 解决 Windows PowerShell 中文编码问题（必须在任何 print/log 之前执行）
# ─────────────────────────────────────────────────────────────────────────────
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

# 加载 secrets.env（仅含 KEY=VALUE 格式，dotenv 可正确解析）
_agent_root = Path(__file__).parent
load_dotenv(dotenv_path=_agent_root / ".env")


# ==============================================================================
# 路径配置
# ==============================================================================
BASE_DIR = Path(__file__).parent
SRC_DIR = BASE_DIR / "src"
KNOWLEDGE_CARDS_DIR = BASE_DIR / "knowledge_cards"
# --- 心理学语料库目录（ACT + CBT 技术卡片）---
CORPUS_CBT_DIR = BASE_DIR / "corpus" / "markdown"
CORPUS_ACT_DIR = BASE_DIR / "corpus" / "markdown(ACT)"
LOGS_DIR = BASE_DIR / "logs"
CHROMA_DB_DIR = BASE_DIR / "chroma_db"

# 确保必要目录存在
LOGS_DIR.mkdir(exist_ok=True)
CHROMA_DB_DIR.mkdir(exist_ok=True)
KNOWLEDGE_CARDS_DIR.mkdir(exist_ok=True)


# ==============================================================================
# 演示模式配置（demo_all.py 使用）
# ==============================================================================
DEMO_MODE: bool = os.getenv("DEMO_MODE", "").lower() in ("true", "1", "yes")


# ==============================================================================
# LLM API 配置
# ==============================================================================
class HuggingFaceConfig:
    """HuggingFace 镜像配置（解决国内网络无法访问 huggingface.co）"""
    ENDPOINT: str = os.getenv("HF_ENDPOINT", "")
    # 国内常用镜像：https://hf-mirror.com


class LLMConfig:
    """核心大语言模型（DeepSeek）配置"""
    API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    # 主模型：用于情感融合分析、干预决策
    CHAT_MODEL: str = "deepseek-chat"
    # 推理模型：用于复杂心理分析（如果需要）
    REASONER_MODEL: str = "deepseek-reasoner"
    TEMPERATURE: float = 0.5  # 适中温度，平衡多样性与稳定性
    MAX_TOKENS: int = 2048
    TIMEOUT: int = 30  # 秒


class QwenConfig:
    """多模态大模型（Qwen-VL）配置"""
    API_KEY: str = os.getenv("QWEN_API_KEY", "")
    BASE_URL: str = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    VL_MODEL: str = "qwen-vl-max"
    TEMPERATURE: float = 0.5
    MAX_TOKENS: int = 1024


# ==============================================================================
# 存储配置
# ==============================================================================
class RedisConfig:
    """Redis 短期记忆配置"""
    HOST: str = os.getenv("REDIS_HOST", "localhost")
    PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    DB: int = int(os.getenv("REDIS_DB", "0"))
    PASSWORD: str | None = os.getenv("REDIS_PASSWORD", None) or None
    DECODE_RESPONSES: bool = True

    # 短期记忆参数
    MAX_HISTORY_MESSAGES: int = 20       # 保留最近N条原始对话
    SUMMARY_TRIGGER_COUNT: int = 20      # 达到此数量触发摘要压缩
    SUMMARY_KEEP_COUNT: int = 5          # 压缩后保留最近N条
    SESSION_TTL_SECONDS: int = 7200      # 会话默认2小时过期

    # Redis Key 模板
    @staticmethod
    def history_key(session_id: str) -> str:
        return f"session:{session_id}:history"

    @staticmethod
    def summary_key(session_id: str) -> str:
        return f"session:{session_id}:summary"

    @staticmethod
    def last_active_key(session_id: str) -> str:
        return f"session:{session_id}:last_active"

    @staticmethod
    def perception_key(session_id: str) -> str:
        return f"emotion:realtime:{session_id}"


class MySQLConfig:
    """MySQL 结构化记忆配置"""
    HOST: str = os.getenv("MYSQL_HOST", "localhost")
    PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    USER: str = os.getenv("MYSQL_USER", "root")
    PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    DATABASE: str = os.getenv("MYSQL_DATABASE", "wanqing_ai")
    CHARSET: str = "utf8mb4"

    @property
    def url(self) -> str:
        return (
            f"mysql+aiomysql://{self.USER}:{self.PASSWORD}"
            f"@{self.HOST}:{self.PORT}/{self.DATABASE}?charset={self.CHARSET}"
        )


class ChromaConfig:
    """Chroma 向量数据库配置"""
    PERSIST_DIR: str = str(CHROMA_DB_DIR)
    # 长期语义记忆集合
    LONG_TERM_COLLECTION: str = "long_term_memories"
    # RAG 心理学知识库集合
    RAG_COLLECTION: str = "psychology_knowledge"
    # 检索返回的最大数量
    DEFAULT_TOP_K: int = 3


class OSSConfig:
    """阿里云 OSS 冷存储配置"""
    ACCESS_KEY_ID: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    ACCESS_KEY_SECRET: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    ENDPOINT: str = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
    BUCKET: str = os.getenv("OSS_BUCKET", "camera-vedio-place")
    # 长期记忆归档路径前缀
    MEMORY_PREFIX: str = "long_patterns/"


class NotionConfig:
    """Notion API 配置（情绪日记 Tool Calling）"""
    API_KEY: str = os.getenv("NOTION_API_KEY", "")
    DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")


# ==============================================================================
# 感知模块配置
# ==============================================================================
class PerceptionConfig:
    """多模态感知参数"""

    # 感知服务端口（用于 WebSocket 广播 TTS 等消息）
    PERCEPTION_SERVICE_PORT: int = int(os.getenv("PERCEPTION_SERVICE_PORT", "8000"))

    # 走神模式 → 专注模式的触发阈值
    ATTENTION_TRIGGER_BLINK_RATE: float = 25.0   # 眨眼频率 > 25次/分
    ATTENTION_TRIGGER_HEAD_PITCH: float = -40.0  # 低头角度 > 40度（严重低头才判定为走神）
    ATTENTION_TRIGGER_CONFIDENCE: float = 0.6    # 小模型置信度阈值

    # 专注模式持续时间
    FOCUS_MODE_DURATION_SECONDS: int = 30

    # 感知数据写入频率
    PERCEPTION_WRITE_HZ: float = 10.0  # 10Hz 写入 Redis

    # 图像分析间隔（Qwen-VL 调用间隔）
    QWEN_ANALYSIS_INTERVAL_SECONDS: int = 15

    # 音频参数
    AUDIO_CHUNK: int = 1024
    AUDIO_CHANNELS: int = 1
    AUDIO_RATE: int = 16000

    # focus_level 计算权重（用户调整：提高头部稳定性权重，降低眨眼频率权重）
    FOCUS_HEAD_STABILITY_WEIGHT: float = 0.65   # 头部姿态稳定性权重
    FOCUS_BLINK_RATE_WEIGHT: float = 0.15        # 眨眼频率权重
    FOCUS_GAZE_DEVIATION_WEIGHT: float = 0.20   # 视线偏移权重
    FOCUS_BLINK_NORMAL_RATE: float = 15.0       # 正常眨眼频率（次/分）


# ==============================================================================
# 情感分析配置
# ==============================================================================
class EmotionConfig:
    """情感识别与分析参数"""

    # Plutchik 8维基础情绪（向量空间）
    PLUTCHIK_EMOTIONS: list[str] = [
        "喜悦", "信任", "恐惧", "惊讶",
        "悲伤", "厌恶", "愤怒", "期待"
    ]

    # Agent 使用的10类情绪标签（DeepSeek输出枚举）
    EMOTION_LABELS: list[str] = [
        "焦虑", "沮丧", "平静", "开心",
        "疲惫", "愤怒", "恐惧", "厌恶", "惊讶", "中性"
    ]

    # 认知扭曲类型（CBT标准）
    COGNITIVE_DISTORTION_TYPES: list[str] = [
        "灾难化", "读心术", "非黑即白", "过度概括",
        "情绪推理", "贴标签", "个人化", "应该陈述"
    ]

    # 情绪优先级映射（用于干预决策评分）
    # 1.0 = 高优先级，0.5 = 中优先级，0.0 = 低优先级
    EMOTION_PRIORITY: dict[str, float] = {
        "愤怒": 1.0,
        "恐惧": 1.0,
        "焦虑": 0.8,
        "沮丧": 0.5,
        "疲惫": 0.3,
        "厌恶": 0.3,
        "惊讶": 0.2,
        "中性": 0.0,
        "平静": 0.0,
        "开心": 0.0,
    }

    # 大五人格（OCEAN）参数 —— 影响情绪惯性和衰减
    PERSONALITY_PROFILE: dict[str, float] = {
        "O": 0.5,  # 开放性
        "C": 0.8,  # 尽责性
        "E": 0.6,  # 外向性
        "A": 0.9,  # 宜人性
        "N": 0.4,  # 神经质
    }

    @classmethod
    def emotion_inertia(cls) -> float:
        """动态计算情绪惯性系数（N越高→惯性越小→情绪越容易波动）"""
        n = cls.PERSONALITY_PROFILE["N"]
        return max(0.1, 0.8 - 0.5 * n)

    @classmethod
    def homeostatic_decay(cls) -> float:
        """动态计算情绪稳态衰减率（E越高→恢复越快）"""
        e = cls.PERSONALITY_PROFILE["E"]
        return 0.05 + 0.05 * e

    # AU 阈值（供 Prompt 注入参考，不做硬编码判断）
    AU_THRESHOLDS: dict[str, float] = {
        "AU4": 0.6,   # 皱眉：>0.6 表示高强度负面情绪
        "AU12": 0.4,  # 嘴角上扬：>0.4 表示积极情绪（降低阈值提高灵敏度）
        "AU15": 0.5,  # 嘴角下垂：>0.5 表示悲伤/沮丧
    }


# ==============================================================================
# 干预决策配置
# ==============================================================================
class InterventionConfig:
    """干预决策参数"""

    # 干预倾向分数权重
    WEIGHT_INTENSITY: float = 0.5
    WEIGHT_EMOTION_PRIORITY: float = 0.3
    WEIGHT_INTERRUPT_COST: float = 0.4   # 负项
    WEIGHT_TREND: float = 0.2
    WEIGHT_CONFIDENCE: float = 0.1

    # 趋势因子
    TREND_RISING_FACTOR: float = 0.2
    TREND_FALLING_FACTOR: float = -0.1
    TREND_STABLE_FACTOR: float = 0.0

    # 决策阈值
    INTERVENE_THRESHOLD: float = 0.8    # >= 此值 → intervene
    SUBTLE_THRESHOLD: float = 0.6       # >= 此值 → subtle

    # 打扰成本阈值（超过此值强制silent）
    HIGH_INTERRUPT_COST: float = 0.6

    # 情绪强度最低触发线（低于此值直接silent）
    MIN_INTENSITY_FOR_INTERVENTION: float = 0.4

    # 用户主动发消息时触发深度干预（RAG）的情绪强度门限（任务3）
    # 当用户主动倾诉且 intensity >= 此值时，允许启用 INTERVENE 路径
    HIGH_INTENSITY_THRESHOLD_FOR_USER_INITIATED: float = 0.7

    # 冷却期配置（秒）
    COOLDOWN_BASE_SECONDS: int = 120
    # 突破冷却期的紧急条件
    EMERGENCY_INTENSITY_THRESHOLD: float = 0.9

    # 历史趋势分析窗口（分钟）
    TREND_ANALYSIS_WINDOW_MINUTES: int = 30
    TREND_MIN_DATA_POINTS: int = 3

    # 置信度修正
    LLM_CONFIDENCE_ALPHA: float = 0.6   # LLM置信度权重
    # 1 - alpha = 0.4 为多模态一致性权重

    # UI 指令映射
    UI_INSTRUCTION_MAP: dict[str, dict] = {
        "silent": {"color": "neutral", "pulse": "slow"},
        "subtle": {"color": "blue", "pulse": "medium"},
        "intervene_anxiety": {"color": "blue", "pulse": "fast"},
        "intervene_sad": {"color": "orange", "pulse": "medium"},
        "intervene_angry": {"color": "purple", "pulse": "fast"},
        "intervene_default": {"color": "green", "pulse": "medium"},
    }


# ==============================================================================
# 记忆系统配置
# ==============================================================================
class MemoryConfig:
    """记忆系统参数"""

    # 长期记忆触发检索的情绪强度阈值
    LONG_TERM_RETRIEVAL_INTENSITY_THRESHOLD: float = 0.6

    # 情绪时序分析（历史查询时间窗口，小时）
    EMOTION_HISTORY_QUERY_HOURS: int = 1

    # 会话洞察生成（会话结束时触发）
    SESSION_INSIGHT_ENABLED: bool = True

    # 长期记忆压缩配置
    COMPRESSION_AGE_DAYS: int = 90       # 超过90天的记忆触发压缩
    COMPRESSION_SCHEDULE: str = "weekly" # 压缩调度频率

    # 每日情绪总结调度
    DAILY_SUMMARY_HOUR: int = 17
    DAILY_SUMMARY_MINUTE: int = 30


# ==============================================================================
# RAG 知识库配置
# ==============================================================================
class RAGConfig:
    """RAG 心理学知识库参数"""

    # Embedding 模型（用于向量化知识卡片和查询）
    # 备选-1（英文，通用）：all-MiniLM-L6-v2
    # 备选-2（多语言，含中文，推荐）：paraphrase-multilingual-MiniLM-L12-v2
    # 注意：更换模型后需要清库重建（维度不同会导致检索错误）
    EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    # 备选：使用 DeepSeek/OpenAI Embedding API
    USE_OPENAI_EMBEDDING: bool = False
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # 检索参数
    TOP_K: int = 3               # 检索返回的最大卡片数
    SIMILARITY_THRESHOLD: float = 0.5  # 相似度最低阈值

    # 是否启用重排序
    RERANKER_ENABLED: bool = False


# ==============================================================================
# 火山引擎 TTS 配置
# ==============================================================================
class VolcengineConfig:
    """火山引擎豆包语音合成配置"""
    # Access Token 认证方式（推荐，直接使用）
    ACCESS_TOKEN: str = os.getenv("VOLC_ACCESS_TOKEN", "")
    # Access Key 认证方式（备选，需调用 GetToken API）
    ACCESS_KEY_ID: str = os.getenv("VOLC_ACCESS_KEY_ID", "")
    SECRET_ACCESS_KEY: str = os.getenv("VOLC_SECRET_ACCESS_KEY", "")
    # App ID
    APP_ID: str = os.getenv("VOLC_APP_ID", "")
    # TTS 集群，通常为 volcengine_tts
    TTS_CLUSTER: str = os.getenv("VOLC_TTS_CLUSTER", "volcengine_tts")
    # 默认音色（邻家女孩2.0）
    TTS_VOICE: str = os.getenv("VOLC_TTS_VOICE", "zh_female_linjianvhai_uranus_bigtts")
    # TTS 音频格式 (mp3, pcm, wav, ogg_opus)
    TTS_FORMAT: str = os.getenv("VOLC_TTS_FORMAT", "mp3")
    # TTS 采样率 (8000, 16000, 22050, 24000, 32000, 44100, 48000)
    TTS_SAMPLE_RATE: int = int(os.getenv("VOLC_TTS_SAMPLE_RATE", "24000"))


# ==============================================================================
# TTS / ASR 配置
# ==============================================================================
class AudioConfig:
    """语音合成与识别配置"""
    # TTS 提供商：edge | volcengine | dashscope
    # edge: Microsoft Edge TTS（免费、低延迟，推荐）
    # volcengine: 火山引擎豆包语音
    # dashscope: 阿里 DashScope
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "edge")
    TTS_MODEL: str = os.getenv("TTS_MODEL", "cosyvoice-v1")
    TTS_VOICE: str = os.getenv("TTS_VOICE", "longwan")
    # Edge TTS 专用音色（仅当 TTS_PROVIDER=edge 时生效）
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    ASR_MODEL_DIR: str = os.getenv("ASR_MODEL_DIR", "iic/SenseVoiceSmall")


class JavaCallbackConfig:
    """
    Java 后端回调配置（会话日志持久化）

    架构约定：Python AI 服务不直连 MySQL，由 Java 层负责落库。
    Python Agent 每轮对话结束后，通过此配置回调 Java 接口写入 session_logs。

    数据流：log_session_node → HTTP POST /internal/conversation/log → Java → MySQL
    """
    # Java Spring Boot 后端地址（默认本机 localhost:8080）
    BASE_URL: str = os.getenv("JAVA_CALLBACK_URL", "http://localhost:8080")
    # 回调接口路径（ConversationController）
    CONVERSATION_LOG_PATH: str = "/internal/conversation/log"
    # HTTP 超时（秒）
    TIMEOUT: float = 10.0


# ==============================================================================
# 日志配置
# ==============================================================================
class LogConfig:
    """日志参数"""
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = str(LOGS_DIR / "wanqing.log")
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "7 days"
    LOG_FORMAT: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )


# ==============================================================================
# 全局配置实例（直接导入使用）
# ==============================================================================
huggingface_config = HuggingFaceConfig()
llm_config = LLMConfig()
qwen_config = QwenConfig()
redis_config = RedisConfig()
mysql_config = MySQLConfig()
chroma_config = ChromaConfig()
oss_config = OSSConfig()
perception_config = PerceptionConfig()
emotion_config = EmotionConfig()
intervention_config = InterventionConfig()
memory_config = MemoryConfig()
rag_config = RAGConfig()
volcengine_config = VolcengineConfig()
audio_config = AudioConfig()
log_config = LogConfig()
notion_config = NotionConfig()
java_callback_config = JavaCallbackConfig()