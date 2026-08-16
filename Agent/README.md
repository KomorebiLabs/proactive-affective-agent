# 婉情AI 智能体 (Wanqing AI Agent)

> 基于 LangGraph 的主动式情感智能体 —— Python AI 层  
> 版本：v0.1.0-scaffold | 创建时间：2026-03-20

---

## 项目概述

婉情AI 是一个面向桌面场景的多模态情感陪伴智能体，通过持续感知用户的面部表情、音频特征和头部姿态，结合心理学知识库，在适当时机主动提供情感支持。

**架构分层：**
- **Python AI 层（本仓库）**：LangGraph 状态机，负责情感识别、干预决策、记忆管理和RAG检索
- **Java 业务层**：Spring Boot API 网关（单独仓库）
- **前端**：Vue3（单独仓库）

---

## 技术栈与版本记录

> ⚠️ 重要：所有依赖版本以此文档为准，详细 pin 版本见 `requirements.txt`

### 核心框架

| 组件 | 版本 | 说明 |
|------|------|------|
| **Python** | 3.10+ | 最低要求 3.10（使用了 `X \| Y` 类型语法） |
| **LangGraph** | 0.2.73 | Agent 状态机核心，节点/图/条件边 |
| **LangChain** | 0.3.21 | Prompt 模板、Parser、工具链 |
| **langchain-openai** | 0.3.11 | DeepSeek / Qwen OpenAI 兼容接口 |
| **Pydantic** | 2.11.1 | 数据模型验证（v2，非v1） |

### LLM API

| 组件 | 版本/型号 | 说明 |
|------|-----------|------|
| **DeepSeek** | deepseek-chat | 核心大脑：情感分析、干预决策、回复生成 |
| **Qwen-VL-Max** | qwen-vl-max | 多模态场景分析（按需调用） |
| **openai SDK** | 1.70.0 | 两个 API 均使用 OpenAI 兼容格式 |

### 感知模块

| 组件 | 版本 | 用途 |
|------|------|------|
| **mediapipe** | 0.10.21 | 面部关键点、头部姿态、眨眼频率 |
| **opensmile** | 2.5.0 | 音频特征提取（eGeMAPS 88维） |
| **transformers** | 4.50.3 | HuggingFace 轻量级 AU 情绪分类模型 |
| **torch** | 2.6.0 | 深度学习推理（CPU版本） |

### 存储

| 组件 | 版本 | 用途 |
|------|------|------|
| **Redis** | 7.x（服务端） | 短期工作记忆：最近20条对话 + 实时感知数据 |
| **redis-py** | 5.2.1 | Python Redis 客户端 |
| **MySQL** | 8.x（服务端） | 结构化记忆：用户画像 + 会话日志 |
| **SQLAlchemy** | 2.0.40 | ORM（异步模式） |
| **aiomysql** | 0.2.0 | MySQL 异步驱动 |
| **ChromaDB** | 0.6.3 | 向量数据库：长期语义记忆 + RAG知识库 |
| **sentence-transformers** | 3.4.1 | Embedding 模型（all-MiniLM-L6-v2） |
| **oss2** | 2.19.1 | 阿里云 OSS 冷存储 |

### 工具与日志

| 组件 | 版本 | 用途 |
|------|------|------|
| **loguru** | 0.7.3 | 结构化日志（替代标准 logging） |
| **python-dotenv** | 1.1.0 | .env 环境变量加载 |
| **numpy** | 2.2.4 | 数值计算 |
| **scipy** | 1.15.2 | 情绪趋势线性回归 |
| **PyYAML** | 6.0.2 | YAML 解析 |
| **python-frontmatter** | 1.1.0 | Markdown 知识卡片元数据解析 |

---

## 目录结构

```
Agent/
├── config.py                  # 统一配置管理（从.env读取）
├── requirements.txt           # 锁版本依赖
├── main.py                    # 程序入口
├── README.md                  # 本文件
├── .env                       # 环境变量（不提交Git）
│
├── src/
│   ├── agent/                 # LangGraph 状态机
│   │   ├── state.py           # AgentState 定义（全局状态容器）
│   │   ├── graph.py           # 图结构（节点注册、边连接）[待实现]
│   │   └── nodes/             # 各处理节点
│   │       ├── fuse_emotion.py        # 情感融合节点 [待实现]
│   │       ├── decide_intervention.py # 干预决策节点 [待实现]
│   │       ├── generate_reply.py      # 回复生成节点 [待实现]
│   │       └── route.py               # 路由逻辑 [待实现]
│   │
│   ├── emotion/               # 情感识别模块
│   │   ├── perception.py      # 感知数据处理（Redis读写）[待实现]
│   │   └── analyzer.py        # 多模态分析工具（Qwen-VL调用）[待实现]
│   │
│   ├── memory/                # 三层记忆系统
│   │   ├── short_term.py      # Redis 短期工作记忆 [待实现]
│   │   ├── structured.py      # MySQL 结构化记忆 [待实现]
│   │   └── long_term.py       # Chroma 长期语义记忆 + OSS [待实现]
│   │
│   ├── rag/                   # RAG 心理学知识库
│   │   ├── knowledge_base.py  # 知识卡片向量化与存储 [待实现]
│   │   └── retriever.py       # 混合检索器 [待实现]
│   │
│   ├── models/
│   │   └── schemas.py         # 全局 Pydantic 数据模型 ✅
│   │
│   └── utils/
│       └── logger.py          # 日志工具 ✅
│
├── knowledge_cards/           # 心理学知识卡片（Markdown + YAML）
│   └── CBT-ANX-001.md         # 示例：5-4-3-2-1着陆技术 ✅
│
├── chroma_db/                 # ChromaDB 本地持久化目录（自动创建）
├── logs/                      # 日志文件（自动创建）
└── context-docs/              # 设计文档（只读，不提交代码）
```

---

## 快速开始

### 1. 创建并激活虚拟环境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

> **注意 PyTorch**：此配置为 CPU 版本。如有 NVIDIA GPU，请先卸载再安装 CUDA 版本：
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cu121
> ```

### 3. 配置环境变量

编辑 `.env` 文件，填入 API Keys 和数据库连接信息。

**必填项：**
```env
DEEPSEEK_API_KEY=sk-xxxxx
QWEN_API_KEY=sk-xxxxx
```

**可选（本地开发默认值通常够用）：**
```env
REDIS_HOST=localhost
REDIS_PORT=6379
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=wanqing_ai
```

### 4. 启动 Redis 和 MySQL

确保本地服务正在运行：
```bash
# Redis
redis-server

# MySQL（创建数据库）
mysql -u root -p -e "CREATE DATABASE wanqing_ai CHARACTER SET utf8mb4;"
```

### 5. 运行

```bash
python main.py
```

---

## 模块开发状态

| 模块 | 状态 | 负责节点 |
|------|------|---------|
| 项目脚手架 | ✅ 完成 | - |
| 情感识别（fuse_emotion） | 🔜 下一步 | `src/agent/nodes/fuse_emotion.py` |
| 干预决策（decide_intervention） | ⏳ 待开发 | `src/agent/nodes/decide_intervention.py` |
| 三层记忆系统 | ⏳ 待开发 | `src/memory/` |
| RAG 知识库 | ⏳ 待开发 | `src/rag/` |
| LangGraph 图整合 | ⏳ 待开发 | `src/agent/graph.py` |

---

## 数据流说明

```
[感知微服务] → Redis (emotion:realtime:{session_id})
                    ↓
             [fuse_emotion 节点]
             读取感知数据 + Qwen分析(按需) + 历史情感
             → DeepSeek 融合分析
             → EmotionVector（存入state + 写入MySQL日志）
                    ↓
          [decide_intervention 节点]
          计算干预评分 = 0.5×intensity + 0.3×emotion_priority
                      - 0.4×interrupt_cost + 0.2×trend + 0.1×confidence
          检查冷却期（120秒）
          → InterventionDecision（silent / subtle / intervene）
                    ↓
           [generate_reply 节点]（仅 intervene 时执行）
           检索 RAG 知识库（Chroma）
           检索长期记忆（Chroma）
           → DeepSeek 生成回复
           → 写入 Redis（对话历史）+ MySQL（会话日志）
                    ↓
          [WebSocket] → Java Spring Boot → Vue3 前端
```

---

## 核心设计决策记录

| 决策点 | 方案 | 原因 |
|--------|------|------|
| 情绪标签体系 | 10类中文枚举 | 前端+知识卡片统一映射 |
| 打扰成本计算 | `focus_level × (1-arousal)` | 无需系统级监控，从感知数据估算 |
| LLM 置信度修正 | `0.6×llm_conf + 0.4×consistency` | 纯LLM自评不可靠，加入多模态一致性 |
| 短期记忆 | Redis List + LTRIM | 高频读写，TTL自动清理 |
| 向量模型 | all-MiniLM-L6-v2（本地） | 无API成本，延迟低，效果够用 |
| 干预冷却期 | 120秒，高危可突破 | 避免骚扰，高危紧急优先 |

---

## .gitignore 建议

```
.env
venv/
chroma_db/
logs/
__pycache__/
*.pyc
.DS_Store
```
