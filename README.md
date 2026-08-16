# Wanqing-AI：主动式桌面情感智能体（基于多模态感知与状态机决策的主动式桌面情感智能体研究）

> **婉情AI V2.0** — 实时感知 + 大模型推理 + 主动关怀的新一代情感陪伴智能体

开发者：阳溢涛及其"Book思议"小组

计算机设计大赛提交文件：通过网盘分享的文件：2026019490 主文件夹 链接: https://pan.baidu.com/s/1no2pNWRJkylLUUx1PaV1fg?pwd=1234 提取码: 1234


bilibili视频简要讲解和展示：

【自用-202604061749-04 技术架构的简单说明】 https://www.bilibili.com/video/BV1GNDFBmEXh/?share_source=copy_web&vd_source=2f399e1ad6d1eb7b171529fe4cb3bb4b

【自用-2026019490-04 实际快速演示】 https://www.bilibili.com/video/BV1QTDFBLEGw/?share_source=copy_web&vd_source=2f399e1ad6d1eb7b171529fe4cb3bb4b

【自用-2026019490-04演示视频-快速暂时五大核心功能】 https://www.bilibili.com/video/BV12aSoBhE28/?share_source=copy_web&vd_source=2f399e1ad6d1eb7b171529fe4cb3bb4b




---

## 项目概述

婉情AI 是一款 B/S 架构的情感智能体，能够通过摄像头和麦克风实时感知用户的面部表情、语音特征，结合 DeepSeek 大模型进行 OCC 情感分析，并基于五因子干预决策模型决定是否主动介入对话，提供情感陪伴和心理学引导。

### 五大核心功能

| # | 功能 | 技术实现 |
|---|------|----------|
| 1 | 多模态情感融合 | DeepSeek LLM + OCC 八维情感向量 + MediaPipe AU 检测 + openSMILE 音频特征 |
| 2 | 主动关怀决策 | 五因子加权评分模型（强度 / 优先级 / 打扰成本 / 趋势 / 置信度）|
| 3 | RAG 知识库检索 | ChromaDB 向量数据库 + sentence-transformers 语义检索 + CBT/ACT 心理学卡片 |
| 4 | Notion 情绪日记 | 情绪强度 ≥ 0.6 时自动写入 Notion，形成用户情绪档案 |
| 5 | 三层记忆系统 | Redis 短期 / MySQL 中期 / ChromaDB 长期，跨 session 理解用户情绪模式 |


---


### 核心技术亮点

#### 🎯 1. 多模态情感融合（Multimodal Emotion Fusion）

婉情AI 创新性地融合了**三大感知源**与**大模型推理**，突破单一模态的情感识别局限：

```
                    ┌─────────────────────────────────────────┐
                    │           多模态感知融合引擎              │
                    │                                        │
  ┌─────────────┐  │  ┌─────────────────────────────────┐  │
  │  MediaPipe   │  │  │                                 │  │
  │  面部动作单元 │──┼─▶│  AU4(皱眉)  AU12(嘴角)  AU6(颧骨) │  │
  │  (40+ 关键点) │  │  │  → 恐惧/愤怒/悲伤/喜悦          │  │
  └─────────────┘  │  └───────────────┬─────────────────┘  │
                        │              │                    │
  ┌─────────────┐  │  ┌───────────────▼─────────────────┐  │
  │  openSMILE  │  │  │                                 │  │
  │  音频声学特征 │──┼─▶│  pitch(音调)  energy(能量)      │  │
  │ (39+ 底层特征)│  │  │  → 焦虑/沮丧/疲惫/平静          │  │
  └─────────────┘  │  └───────────────┬─────────────────┘  │
                        │              │                    │
  ┌─────────────┐  │  ┌───────────────▼─────────────────┐  │
  │  Qwen-VL    │  │  │                                 │  │
  │  视觉理解    │──┼─▶│  面部表情整体评估 + 场景上下文    │  │
  │  (阿里通义)  │  │  │  → 深度情绪理解                  │  │
  └─────────────┘  │  └───────────────┬─────────────────┘  │
                        │              │                    │
                        └──────────────┼────────────────────┘
                                      ▼
                    ┌─────────────────────────────────────────┐
                    │      DeepSeek LLM 情感推理引擎           │
                    │                                         │
                    │   输入: AU向量 + 音频特征 + Qwen分析    │
                    │   输出: OCC 八维情感向量 + 情绪强度     │
                    │                                         │
                    │   喜悦  信任  恐惧  惊讶                │
                    │   悲伤  厌恶  愤怒  期待                │
                    └─────────────────────────────────────────┘
```

**技术突破**：
- **多源投票机制**：面部动作单元（AU）、音频特征、视觉整体评估三方证据交叉验证，任一来源置信度 > 0.6 即触发关注
- **OCC 情感模型**：基于 Ortony, Clore & Collins 经典情感理论，将情绪映射到 8 维正交向量空间，支持复合情绪识别（如"又惊又喜"）
- **Qwen-VL 深度理解**（可选）：专注模式下调用阿里通义千问，从图像整体视角理解用户情绪状态，弥补 AU 检测的局部盲区

#### 🧠 2. 主动关怀决策引擎（Proactive Care Decision Engine）

婉情AI 不是被动响应，而是**主动感知 + 智能决策**。当检测到负面情绪信号时，AI 内部会启动一套五因子加权评分系统，决定是否打扰用户：

```
         ┌──────────────────────────────────────────────┐
         │           五因子干预决策模型                    │
         │                                              │
         │   决策分数 =                                   │
         │                                              │
         │   + 0.5 × 情绪强度   (当前有多难受？)           │
         │   + 0.3 × 情绪优先级  (愤怒/恐惧 > 焦虑 > 沮丧)  │
         │   - 0.4 × 打扰成本    (用户是否正在专注做事？)    │
         │   + 0.2 × 情绪趋势    (正在恶化还是好转？)       │
         │   + 0.1 × 置信度      (多模态感知是否一致？)     │
         │                                              │
         └──────────────────────┬───────────────────────┘
                               ▼
          ┌────────────────────┼───────────────────────┐
          │   分数 ≥ 0.8        │   分数 ≥ 0.6         │ 分数 < 0.6
          ▼                    ▼                      ▼
    ┌──────────┐        ┌──────────┐           ┌──────────┐
    │ 深度干预  │        │ 轻度关怀  │           │ 静默观察  │
    │(CBT引导) │        │(一句问候) │           │(不打扰)   │
    └──────────┘        └──────────┘           └──────────┘
```

**关键设计**：
- **打扰成本量化**：综合 focus_level（摄像头感知专注度）+ 消息频率，判断用户是否正在专注状态
- **情绪冷却期**：每次干预后进入 120 秒冷却期，避免过度打扰；仅当情绪强度 ≥ 0.9（紧急情况）才突破冷却
- **干预分级**：区分"轻度关怀"（一句话问候）和"深度干预"（CBT 苏格拉底式引导），由分数阈值决定

#### 📚 3. RAG 心理学知识库检索

婉情AI 内置了**基于 CBT（认知行为疗法）和 ACT（接纳承诺疗法）的心理学知识库**，通过 ChromaDB 向量数据库实现语义检索：

```
   用户情绪状态 ──▶ 情绪标签("焦虑") + 场景描述
                        │
                        ▼
   ┌───────────────────────────────────────┐
   │         ChromaDB 向量数据库             │
   │                                        │
   │  [CBT卡片-001] 认知扭曲类型与识别方法   │
   │  [CBT卡片-002] 5-4-3-2-1 着陆技术      │
   │  [ACT卡片-001] 接纳承诺疗法核心概念     │
   │  [ACT卡片-002] 价值导向行为激活        │
   │  ...                                    │
   │                                        │
   │  sentence-transformers (多语言模型)     │
   │  向量化存储 + 余弦相似度检索             │
   └────────────────────┬────────────────────┘
                        ▼
              top-3 最相关的心理学卡片
                        │
                        ▼
              注入到 DeepSeek Prompt
              ─────────────────────
              "用户当前处于焦虑状态，
               以下是适合的干预策略..."
```

**知识库规模**：内置 20+ 张心理学干预技术卡片，覆盖常见情绪场景（焦虑、愤怒、悲伤、压力等）

#### 📓 4. Notion 情绪日记（自动归档）

当情绪强度 ≥ 0.6 且用户主动倾诉时，婉情AI 会自动将情绪数据写入用户 Notion 数据库，形成**个人情绪档案**：

```json
{
  "情绪": "焦虑",
  "强度": 0.73,
  "时间": "2026-04-08 14:30",
  "触发事件": "工作汇报压力",
  "干预策略": "5-4-3-2-1 着陆技术",
  "用户反馈": "感觉好多了",
  "会话摘要": "..."
}
```

这使得用户可以**回顾情绪模式**，识别反复出现的认知扭曲，实现心理健康的长期自我觉察。

#### 🧬 5. 三层记忆系统（跨会话理解）

婉情AI 拥有类似人类记忆的**三级架构**，既能感知当下，也能理解长期：

```
  ┌─────────────────────────────────────────────────────┐
  │                    三层记忆架构                      │
  │                                                      │
  │  【短期】Redis（秒级，10Hz 实时感知）                 │
  │  ├── 面部 AU 向量（最近 1 分钟）                      │
  │  ├── 音频特征（pitch, energy）                        │
  │  ├── focus_level（专注度）                            │
  │  └── 会话历史消息（最近 20 条）                        │
  │  TTL: 2 小时，过期自动清理                           │
  │                                                      │
  │  【中期】MySQL（结构化存储，跨会话）                   │
  │  ├── session_logs（每日会话记录）                     │
  │  ├── emotion_trends（情绪趋势统计）                  │
  │  └── user_profiles（用户画像）                       │
  │  用于：历史情绪查询、每日总结、用户偏好学习             │
  │                                                      │
  │  【长期】ChromaDB（向量语义，永久积累）                │
  │  ├── 会话摘要语义化存储                               │
  │  ├── 情绪模式向量                                   │
  │  └── 心理学知识库卡片                                │
  │  用于：长期记忆检索、用户情绪人格画像                  │
  │                                                      │
  └─────────────────────────────────────────────────────┘
```

**典型应用**：
- 短期："用户刚才情绪急剧下降（强度 +0.3），但现在已稳定，不需要再干预"
- 中期："用户这周有 3 次焦虑情绪，且都与工作汇报相关，建议生成周报总结"
- 长期："用户长期情绪波动较大（神经质人格 N=0.7），应采用更温和的干预策略"

---



## 系统架构

本项目由 **4 个独立服务** 组成（进程独立、端口隔离）：

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              用户浏览器                                   │
│                         http://localhost:5173                            │
│                           (Vue 3 + ECharts)                             │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │ HTTP/WebSocket/SSE
┌──────────────────────────▼───────────────────────────────────────────────┐
│                    Java Spring Boot（端口 8080）                          │
│                         业务编排层                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │ ChatController│  │SessionService │  │  MySQL 存储  │                  │
│  │   SSE 流式    │  │  会话管理    │  │  中期记忆    │                  │
│  └──────────────┘  └──────────────┘  └──────────────┘                  │
└──────┬──────────────────────────┬───────────────────────────────────────┘
       │ HTTP/SSE                  │ HTTP POST
┌──────▼──────────┐       ┌────────▼────────┐
│ Python Agent     │       │ Python 感知服务   │
│ （端口 8001）    │       │  （端口 8000）   │
│ LangGraph 决策引擎│       │ FastAPI + WS    │
│ DeepSeek LLM     │       │ MediaPipe       │
│ ChromaDB RAG     │       │ openSMILE       │
│ Notion 写入      │       │ 10Hz 写 Redis   │
│ 三层记忆系统      │       │                 │
└──────────────────┘       └────────┬────────┘
                                     │
                              ┌──────▼──────┐
                              │    Redis     │
                              │ 短期记忆     │
                              │ 感知数据缓存 │
                              └─────────────┘
```

### 服务详解

#### Python Agent（端口 8001）— AI 大脑
- `Agent/main.py`：服务入口，监听 `http://localhost:8001`
- `Agent/src/agent/graph.py`：LangGraph 状态机（感知采集 → 情感融合 → 干预决策 → 关怀回复）
- `Agent/src/emotion/`：OCC 向量生成、情感趋势计算
- `Agent/src/rag/`：ChromaDB 知识库同步与检索
- `Agent/src/memory/`：三层记忆系统（短期/中期/长期）
- `Agent/src/agent/tools/notion_tool.py`：Notion 情绪日记写入
- `Agent/demo/demo_all.py`：**一键演示脚本**（无需外部依赖，Mock 运行）
- `Agent/.env`：**API Key 配置**（必须配置 `DEEPSEEK_API_KEY`）

#### Python 感知服务（端口 8000）— 眼睛和耳朵
- `perception/main.py`：FastAPI 服务入口，监听 `http://localhost:8000`
- `perception/api/websocket.py`：WebSocket 广播（视频帧 + 情感 → 前端实时展示）
- `perception/services/monitor_service.py`：摄像头 + 麦克风采集（10Hz 写 Redis）
- `perception/ai_assistant/core/perception_engine.py`：MediaPipe + openSMILE 核心算法
- `perception/.env`：API Key 配置（DeepSeek / 火山 TTS 等）

#### Java Spring Boot（端口 8080）— 业务编排
- `backend/src/main/java/com/wanqing/ai/`：Java 业务代码
- `controller/ChatController.java`：SSE 流式对话入口（转发到 Agent）
- `controller/ConversationController.java`：会话管理
- `client/AgentClient.java`：HTTP SSE 转发到 Python Agent
- `service/impl/SessionServiceImpl.java`：MySQL 会话存储 + 通知感知服务

#### Vue 前端（端口 5173）— 用户界面
- `frontend/src/App.vue`：WebSocket + SSE 连接管理
- `frontend/src/components/ChatWindow.vue`：对话窗口（含语音按钮，已临时禁用）
- `frontend/src/components/EmotionRadar.vue`：OCC 情感雷达图（ECharts）
- `frontend/src/components/PortraitBox.vue`：面部特征可视化
- `frontend/src/components/VisualSignal.vue`：情感强度实时曲线

---

## 快速开始

### 方式一：一键启动（推荐，Windows）

双击或运行项目根目录下的 `start_all.ps1`：

```powershell
cd "C:\Users\你的路径\Wanqing"
.\start_all.ps1
```

> 首次启动约需等待 3~5 分钟（Maven 下载 Java 依赖）。脚本会自动检查 Python / Node.js / Redis / 配置文件，并依次启动所有服务。

### 方式二：分步启动

#### Step 1：安装 Python 依赖

```bash
# 在项目根目录
pip install -r requirements.txt

# 如遇中文编码错误，先关闭 VPN，并确认 requirements.txt 为 UTF-8 无 BOM 编码
```

#### Step 2：配置 API Key（必需）

复制配置文件模板，并填入真实密钥：

```bash
# Agent 配置
copy Agent\.env.example Agent\.env

# Backend 配置
copy backend\.env.example backend\.env
```

然后分别编辑 `Agent/.env` 和 `backend/.env`，填入以下密钥：

| 密钥 | 必需 | 获取地址 | 用途说明 |
|------|------|----------|----------|
| `DEEPSEEK_API_KEY` | ✅ **必需** | [platform.deepseek.com](https://platform.deepseek.com/) → API Keys → 创建 | 情感分析 + 对话生成，婉情AI 的"大脑" |
| `QWEN_API_KEY` | ⚠️ 推荐 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) → API-KEYs | 视觉情绪检测（Qwen-VL）+ ASR 语音识别。若不配置则用 HuggingFace 模型替代 |
| `OSS_ACCESS_KEY_ID` | ⚠️ 推荐 | 阿里云控制台 → 账户中心 → AccessKey | ASR 语音识别时需先将音频上传到 OSS 获取公网 URL |
| `OSS_ACCESS_KEY_SECRET` | ⚠️ 推荐 | 同上 | OSS 密钥 |
| `OSS_BUCKET` | ⚠️ 推荐 | 阿里云 OSS → 创建 Bucket | OSS Bucket 名称 |
| `NOTION_API_KEY` | ❌ 可选 | [notion.so/my-integrations](https://www.notion.so/my-integrations) → 创建集成 | 情绪日记写入 Notion（不配置则 Mock 打印）|
| `VOLC_ACCESS_TOKEN` | ❌ 可选 | 火山引擎控制台 | 语音合成（不配置则用 Edge TTS 微软免费语音）|

> **密钥安全提示**：`.env` 文件已加入 `.gitignore`，不会提交到 GitHub。但不要将真实密钥分享给他人。

#### Step 3：安装前端依赖

```bash
cd frontend
npm install
```

#### Step 4：启动 Java Spring Boot（端口 8080）

```bash
cd backend
# 方式 A：使用 Maven Wrapper（推荐，无需安装 Maven）
.\mvnw.cmd spring-boot:run

# 方式 B：已安装 Maven
mvn spring-boot:run
```

#### Step 5：启动 Python 感知服务（端口 8000）

```bash
cd backend
python main.py
```

#### Step 6：启动 Python Agent（端口 8001）

```bash
cd Agent
python main.py
```

#### Step 7：启动 Vue 前端（端口 5173）

```bash
cd frontend
npm run dev
```

#### Step 8：访问

浏览器打开 **http://localhost:5173**，即可体验婉情AI。

---

## 一键演示脚本（无需任何外部依赖）

如果你只想演示核心 AI 能力，而不需要摄像头、麦克风、Redis 等环境，可以运行演示脚本：

```bash
cd Agent
python demo_all.py
```

演示脚本会：
- 用 **Mock 数据** 模拟摄像头、麦克风、Redis、Notion、MySQL
- 真实调用 **DeepSeek API** 生成 OCC 八维情感向量
- 真实调用 **decide_intervention_node** 五因子决策模型
- 真实调用 **ChromaDB RAG** 向量检索
- 展示 **5 个情绪场景**：焦虑 / 愤怒 / 走神 / 开心 / 悲伤

详见 [Agent/demo/](Agent/demo/) 目录。

---

## 环境准备（新手必读）

### 第一步：安装必需软件

婉情AI 依赖 5 个运行环境，请按以下顺序安装：

| # | 软件 | 安装说明 | 验证命令 |
|---|------|----------|----------|
| 1 | **Python 3.10+** | [python.org/downloads](https://www.python.org/downloads/) | `python --version` |
| 2 | **Node.js 18+** | [nodejs.org](https://nodejs.org/)（建议安装 LTS 版本）| `node --version` |
| 3 | **JDK 21** | [Oracle JDK](https://www.oracle.com/java/technologies/downloads/#java21)（勿用 JRE）| `java --version` |
| 4 | **MySQL 8.0+** | [MySQL Community](https://dev.mysql.com/downloads/mysql/) | `mysql --version` |
| 5 | **Git** | [git-scm.com](https://git-scm.com/download/win) | `git --version` |

> **安装顺序建议**：Python → Node.js → JDK → MySQL → Git。安装完 Python 和 Node.js 后，记得重启电脑或刷新环境变量。

### 第二步：创建 MySQL 数据库

婉情AI 需要 MySQL 存储会话记录和情绪日志，请先创建数据库：

```bash
# 登录 MySQL
mysql -u root -p

# 创建数据库（utf8mb4 支持 emoji）
CREATE DATABASE wanqing_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 创建用户（非 root 推荐）
CREATE USER 'wanqing'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON wanqing.* TO 'wanqing'@'localhost';
FLUSH PRIVILEGES;

# 确认数据库已创建
SHOW DATABASES;
```

> 退出 MySQL 后，需要在 `backend/src/main/resources/application.yml` 中配置数据库连接信息。

### 第三步：配置数据库连接

编辑 `backend/src/main/resources/application.yml`，确认以下配置与你的一致：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/wanqing?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
    username: wanqing           # 你的 MySQL 用户名
    password: your_password     # 你的 MySQL 密码
  jpa:
    hibernate:
      ddl-auto: update         # 启动时自动创建表结构
    show-sql: false
```

### 第四步：配置 API Key

详见下方「配置 API Key」章节。**至少需要配置 `DEEPSEEK_API_KEY`，否则 Agent 无法运行。**

### 第五步：验证环境

运行以下命令，确认所有依赖就绪：

```powershell
# 在项目根目录运行
python --version        # 应输出 Python 3.10+
node --version         # 应输出 v18+
java --version         # 应输出 21 或更高
mysql --version        # 应输出 8.0+
git --version          # 应输出任意版本

# 检查 Python 依赖是否完整
pip list | findstr deepseek  # 应输出 dashscope / openai 等包名
```

---

## 配置 API Key（详细指南）

> ⚠️ **重要**：`.env` 文件包含真实密钥，已加入 `.gitignore`，不会提交到 GitHub。

### 配置方法

```powershell
# 1. 复制配置文件模板
copy Agent\.env.example Agent\.env
copy backend\.env.example backend\.env

# 2. 用记事本打开编辑（路径中不要有中文和空格）
notepad Agent\.env
notepad backend\.env
```

### 密钥说明

| 密钥 | 必需 | 获取地址 | 用途说明 |
|------|------|----------|----------|
| `DEEPSEEK_API_KEY` | ✅ **必需** | [platform.deepseek.com](https://platform.deepseek.com/) → API Keys → 创建 | 情感分析 + 对话生成，婉情AI 的"大脑"。**没有此 Key，Agent 完全无法运行** |
| `QWEN_API_KEY` | ⚠️ 推荐 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/) → API-KEYs → 创建 | Qwen-VL 视觉理解（摄像头情绪识别）+ **ASR 语音识别**（Paraformer 模型）。不配置则用 HuggingFace 模型替代 |
| `OSS_ACCESS_KEY_ID` | ⚠️ 推荐 | 阿里云控制台 → 账户中心 → AccessKey → 创建 | ASR 语音识别需要将音频文件上传到 OSS 获取公网 URL |
| `OSS_ACCESS_KEY_SECRET` | ⚠️ 推荐 | 同上 | OSS 密钥 |
| `OSS_BUCKET` | ⚠️ 推荐 | 阿里云 OSS → 创建 Bucket | OSS Bucket 名称（建议与感知服务同地域，如 `oss-cn-beijing`）|
| `NOTION_API_KEY` | ❌ 可选 | [notion.so/my-integrations](https://www.notion.so/my-integrations) → 新建集成 → 复制 API Key | 情绪日记自动写入 Notion（不配置则 Mock 打印，不影响运行）|
| `VOLC_ACCESS_TOKEN` | ❌ 可选 | [ volcengine.com](https://www.volcengine.com/) → 语音合成 | 火山引擎 TTS 语音合成（不配置则用 **Edge TTS** 微软免费语音，推荐）|

### API Key 获取图解

#### DeepSeek API Key（必需）

1. 访问 [platform.deepseek.com](https://platform.deepseek.com/)
2. 注册并登录（支持微信登录）
3. 进入 **API Keys** 页面
4. 点击 **Create API Key**，复制生成的密钥（以 `sk-` 开头）
5. 将密钥粘贴到 `Agent/.env` 的 `DEEPSEEK_API_KEY=` 后

#### Qwen/DashScope API Key（推荐，用于视觉 + ASR）

1. 访问 [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/)
2. 登录阿里云账号
3. 进入 **API-KEYs** 页面
4. 点击 **创建 API Key**，复制密钥
5. 粘贴到 `Agent/.env` 和 `backend/.env` 的 `QWEN_API_KEY=` 后

#### 阿里云 OSS（推荐，用于 ASR 音频上传）

1. 访问 [oss.console.aliyun.com](https://oss.console.aliyun.com/)
2. 开通**对象存储 OSS** 服务
3. 点击 **Bucket 列表** → **创建 Bucket**（地域选择与你最近的，如 `华东-北京`）
4. 进入 **AccessKey 管理** → **创建 AccessKey**，复制 Key ID 和 Secret
5. 填入 `.env` 的 OSS 相关字段

### 配置降级说明（不配置可选 Key 时的行为）

| 未配置 | 系统行为 |
|--------|----------|
| 无 `QWEN_API_KEY` | 视觉情绪检测使用 HuggingFace 本地模型替代（CPU 运行，较慢） |
| 无 `OSS_*` | ASR 语音识别完全禁用，麦克风按钮不可用 |
| 无 `NOTION_API_KEY` | 情绪日记改为 Mock 打印（控制台输出），不影响其他功能 |
| 无 `VOLC_ACCESS_TOKEN` | 使用 Edge TTS（微软免费中文语音），音色自然，推荐使用 |

### 可选软件（不配置则使用降级方案）

| 软件 | 作用 | 不配置时的降级方案 |
|------|------|-------------------|
| Redis | 实时感知数据缓存、短期记忆 | Agent 使用本地规则引擎降级响应 |
| 摄像头 | 面部表情采集 | 使用 Mock 感知数据或文字对话驱动 |
| 麦克风 | 语音情感分析（已临时禁用） | 文字对话正常可用 |
| Notion | 情绪日记写入 | Mock 打印，不真实写入 |

### Python 依赖安装

所有 Python 依赖已汇总在项目根目录 `requirements.txt`，一键安装：

```bash
# 在项目根目录（不要在 Agent/ 或 backend/ 子目录运行）
pip install -r requirements.txt
```

> **常见问题**：
> - `Microsoft Visual C++ 14.0 is required` → 下载 [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/)，安装时勾选 **C++ 生成工具**
> - 安装过慢 → 切换国内镜像：`pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`
> - GPU 加速（可选）→ 卸载 CPU 版后执行：`pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121`

---

## 目录结构

```
Wanqing/
│
├── Agent/                          # Python AI 层（端口 8001）
│   ├── main.py                     # Agent 服务入口
│   ├── demo/                       # 一键演示脚本
│   │   ├── demo_all.py             # 主演示流程（5 个场景）
│   │   ├── scenarios.py            # 演示场景定义
│   │   ├── mocks.py                # Mock 层（Redis/Notion/ChromaDB）
│   │   └── display.py              # 终端彩色输出
│   ├── src/
│   │   ├── agent/
│   │   │   ├── graph.py            # LangGraph 状态机
│   │   │   ├── nodes/              # 各决策节点
│   │   │   └── tools/              # Notion / TTS 等工具
│   │   ├── emotion/                # OCC 模型 + 情感分析
│   │   ├── rag/                    # ChromaDB RAG 检索
│   │   └── memory/                 # 三层记忆系统
│   ├── corpus/                     # 心理学知识卡片（Markdown）
│   ├── .env                        # API Key 配置（勿提交 Git）
│   └── requirements.txt
│
├── backend/                        # Python 感知服务（端口 8000）
│   ├── main.py                     # FastAPI 服务入口
│   ├── api/websocket.py           # WebSocket 广播
│   ├── services/
│   │   └── monitor_service.py      # 摄像头 + 麦克风采集
│   ├── ai_assistant/core/
│   │   ├── perception_engine.py    # MediaPipe + openSMILE 核心
│   │   ├── perception_models.py   # 感知数据模型
│   │   └── audio_feature_extractor.py  # 音频特征提取
│   ├── src/                        # Java Spring Boot（端口 8080）
│   │   └── main/java/com/wanqing/ai/
│   ├── .env                        # Backend 配置（勿提交 Git）
│   ├── requirements.txt
│   └── pom.xml
│
├── frontend/                      # Vue 3 前端（端口 5173）
│   ├── src/
│   │   ├── App.vue                 # 根组件 + WebSocket/SSE
│   │   ├── components/
│   │   │   ├── ChatWindow.vue      # 对话窗口
│   │   │   ├── EmotionRadar.vue    # OCC 情感雷达图
│   │   │   ├── PortraitBox.vue     # 面部特征可视化
│   │   │   └── VisualSignal.vue    # 情感强度曲线
│   │   └── style.css
│   ├── package.json
│   └── vite.config.js
│
├── start_all.ps1                   # Windows 一键启动脚本
├── start_all.sh                    # Linux/macOS 一键启动脚本
├── requirements.txt                # 统一 Python 依赖清单
├── README.md                       # 本文件
└── LICENSE_NOTICE.md               # 版权声明
```

---

## 常见问题

### 没有 DeepSeek API Key，能运行吗？

**不能**。`DEEPSEEK_API_KEY` 是必需项，没有它 Agent 完全无法运行。获取方式：[platform.deepseek.com](https://platform.deepseek.com/) → API Keys → 创建。

### 摄像头/麦克风不工作怎么办？

摄像头和麦克风是**可选组件**，不配置时：
- 摄像头 → 使用 Mock 感知数据（虚拟表情信号）
- 麦克风 → ASR 语音识别不可用，但**文字对话正常可用**

如需启用，按以下步骤排查：
1. 摄像头被占用？关闭微信、QQ、腾讯会议等
2. 浏览器权限？Chrome 设置 → 隐私 → 摄像头/麦克风 → 允许
3. 权限提示没点？刷新页面，重新点击"允许"
4. 试试其他软件？打开 Windows 相机应用确认硬件正常

### 进网页后没声音？

浏览器默认静音。**进入网页后随便点击一下页面**，婉情才能开口说话。

### Agent 调用失败（提示 DeepSeek 错误）？

检查 `Agent/.env` 中的 `DEEPSEEK_API_KEY` 是否正确。若 Agent 不可用，感知服务会自动降级为**本地规则引擎**（基于关键字匹配的情感分析），对话功能仍可使用。

### Python 报找不到包（ImportError）？

1. 确认已激活虚拟环境（命令行前有 `(venv)` 或 `(base)` 字样）
2. 确认已执行 `pip install -r requirements.txt`
3. 确认 Python 版本为 3.10+

### Java 启动很慢？

首次启动需要下载大量 Maven 依赖（约 3~5 分钟），属于正常现象。后续启动会使用本地缓存，速度正常。

### Redis 连接失败？

Redis 是**可选组件**。不安装 Redis 时，Agent 会使用本地规则引擎降级，不影响核心对话功能。若需启用 Redis：

```bash
# Windows
redis-server

# macOS
brew install redis && redis-server

# Linux
sudo apt install redis-server && sudo systemctl start redis
```

### 前端修改后没有自动刷新？

确认 `npm run dev` 正在运行（终端显示 `ready in xxx ms`）。Vite 支持热模块替换（HMR），大多数修改会自动刷新。

### 修改后端代码后没有生效？

后端修改后需要 **Ctrl+C 停止并重启**对应服务。Python 和 Java 服务均不支持热加载。

---

## 技术栈清单

| 层级 | 技术 |
|------|------|
| **前端** | Vue 3, Vite, Tailwind CSS, ECharts（雷达图）, GSAP（动画）, Pinia（状态管理）|
| **Java 层** | Spring Boot, WebClient（非阻塞 HTTP）, MySQL |
| **Python 感知层** | FastAPI, Uvicorn, WebSocket, MediaPipe（面部关键点）, openSMILE（音频特征）, Redis |
| **Python AI 层** | LangGraph, DeepSeek（对话）, Qwen-VL-Max（视觉）, ChromaDB（向量库）, sentence-transformers, Notion API |
| **向量模型** | sentence-transformers, HuggingFace Transformers |
| **语音合成** | Edge TTS（火山引擎 TTS 已临时禁用）|

---

## 版权声明

本项目归阳溢涛及其"Book思议"小组所有，仅限学术交流使用。严禁未授权的商业扩散或任何形式的盗用。
