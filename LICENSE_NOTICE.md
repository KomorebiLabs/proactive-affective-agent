# 开源代码与组件使用情况说明

## 项目概述

婉情 AI是一款面向心理健康的实时多模态感知与对话智能体，基于 **Python AI Agent + Java Spring Boot 后端 + Vue 3 前端** 三层架构开发。本项目坚持优先使用开源组件，API 调用仅用于 LLM 推理和多模态感知两个核心模块。

---

## 前端（`/frontend`）

| 组件 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| **Vue.js** | 3.5 | MIT | UI 框架 |
| **Vite** | 7.2 | MIT | 构建工具 |
| **Pinia** | 3.0 | MIT | 状态管理 |
| **ECharts** | 6.0 | Apache-2.0 | 情绪雷达图可视化 |
| **GSAP** | 3.14 | MIT | 界面动画 |
| **Tailwind CSS** | 3.4 | MIT | CSS 原子化框架 |
| **Autoprefixer / PostCSS** | — | MIT | CSS 后处理 |

---

## 后端 Java（`/backend`）

| 组件 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| **Spring Boot** | 3.2 | Apache-2.0 | Web 框架 |
| **MyBatis-Plus** | 3.5 | LGPL-3.0 | ORM 持久层 |
| **MySQL Connector** | — | GPL-2.0 | MySQL 驱动 |
| **Lombok** | 1.18 | MIT | Java 注解简化 |
| **Spring Data Redis** | — | Apache-2.0 | Redis 缓存接入 |

---

## AI Agent Python（`/Agent`）

### 核心框架

| 组件 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| **LangGraph** | 0.2 | MIT | Agent 决策图框架 |
| **LangChain** / langchain-core / langchain-community | 0.3 | MIT | LLM 工具链 |
| **LangChain OpenAI** | 0.3 | MIT | OpenAI 兼容接口 |
| **openai** | 1.70 | Apache-2.0 | API 调用客户端 |

### LLM 推理（需要自行申请 API Key）

| 服务 | 用途 | 官网 |
|------|------|------|
| **DeepSeek** | 情感分析 + 干预决策 LLM | https://platform.deepseek.com |
| **Qwen-VL-Max**（阿里云 DashScope） | 多模态图像理解（摄像头画面分析） | https://dashscope.console.aliyun.com |

### 感知模块

| 组件 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| **MediaPipe** | 0.10 | Apache-2.0 | 人脸关键点（眨眼 / 视线 / 头部姿态）|
| **openSMILE** | 2.5 | openSMILE 授权 | 音频情感特征提取（音量 / 语速 / 基频）|
| **HuggingFace Transformers** | 4.50 | Apache-2.0 | 情绪分类 / AU 检测模型推理 |
| **PyTorch** | 2.6 | BSD-3-Clause | 深度学习推理引擎 |
| **sentence-transformers** | 3.4 | Apache-2.0 | 知识卡片向量化嵌入 |

### 存储与缓存

| 组件 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| **ChromaDB** | 0.6 | Apache-2.0 | 向量数据库（长期语义记忆 + RAG 知识库）|
| **Redis** | 5.2 | BSD-3-Clause | 实时感知数据缓存 + 会话短期记忆 |
| **SQLAlchemy** + **aiomysql** | — | MIT / GPL | MySQL 异步持久化（会话日志）|
| **Alembic** | 1.15 | MIT | 数据库迁移 |
| **oss2**（阿里云 OSS） | 2.19 | BSD-3-Clause | 长期记忆归档对象存储 |

### TTS 语音合成

| 组件 | 版本 | 许可证 | 用途 |
|------|------|--------|------|
| **edge-tts** | 6.1 | MIT | 主力 TTS（微软 Edge 语音，实时流式，免费）|
| **dashscope** | ≥1.20 | 阿里云商用授权 | 后端 Java 服务语音合成（可选）|

### 其他工具库

| 组件 | 用途 |
|------|------|
| **pydantic** / pydantic-settings | 数据验证与配置管理 |
| **loguru** | 结构化日志 |
| **httpx** | 异步 HTTP 客户端 |
| **aiofiles** | 异步文件 I/O |
| **python-dotenv** | .env 环境变量加载 |
| **PyYAML** | YAML 配置解析 |
| **python-frontmatter** | Markdown 元数据解析 |
| **notion-client** | Notion 情绪日记写入（可选功能）|
| **websockets** | WebSocket 实时通信 |
| **numpy** / **scipy** | 数值计算与信号处理 |
| **pytest** / pytest-asyncio | 单元测试 |
| **black** / **ruff** | 代码格式化与检查 |

---

## 声明

1. **本项目整体**采用 **MIT 许可证**开源，但你有义务在使用前自行检查并遵守上述各组件的许可证要求。
2. **DeepSeek API** 和 **阿里云 DashScope（Qwen-VL / 阿里云 TTS）** 为商业 API 服务，需自行注册账号并承担调用费用，本项目不对此承担任何责任。
3. **阿里云 OSS** 的使用同样需要自行开通阿里云 OSS 服务并承担存储费用。
4. **openSMILE** 采用 openSMILE 官方授权协议，请访问 [openSMILE 官网](https://wwwaudeeringcom/technology/opensmile) 确认授权范围。
5. 本项目引用的第三方模型（如 HuggingFace 上的情绪分类模型）受其各自模型的许可证约束，请在使用前阅读对应 LICENSE。
6. 本项目不收集任何用户数据，所有 API 密钥由使用者自行配置在 `.env` 文件中，且该文件已通过 `.gitignore` 排除。
