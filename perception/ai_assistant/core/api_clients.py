# ai_assistant/core/api_clients.py
# ==============================================================================
# Wanqing Backend - 云 API 客户端（第二代架构）
# ==============================================================================
# 职责：
#   1. DeepSeek Client — 对话服务（供 chat_service 调用）
#   2. Qwen-VL Client — 视觉语言模型（供 perception_engine 中的图像分析调用）
#   3. DashScope TTS — 语音合成（供 voice_service 调用）
#   4. OSS Bucket — 阿里云对象存储（截图/音频文件上传）
#
# 注意：ASR 语音识别由阿里云 DashScope API 远程处理，不在此初始化本地模型。
# ==============================================================================

import os

# --- 清除代理环境变量（确保 SDK 请求不被本地代理拦截）---
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('ALL_PROXY', None)

import httpx
from openai import OpenAI
import oss2
import dashscope

from ai_assistant.utils import config

# DeepSeek Client（对话）
deepseek_client = OpenAI(
    api_key=config.DEEPSEEK_API_KEY,
    base_url=config.DEEPSEEK_BASE_URL,
)

# Qwen-VL Client（视觉语言模型）
qwen_client = OpenAI(
    api_key=config.QWEN_API_KEY,
    base_url=config.QWEN_BASE_URL,
)

# TTS API Key（复用 Qwen 的 key）
dashscope.api_key = config.QWEN_API_KEY
# OSS Bucket
auth = oss2.Auth(config.OSS_ACCESS_KEY_ID, config.OSS_ACCESS_KEY_SECRET)
oss_bucket = oss2.Bucket(auth, config.OSS_ENDPOINT, config.OSS_BUCKET)

