-- =============================================================================
-- 婉情AI - 数据库初始化脚本
-- =============================================================================
-- 运行方式：在 DataGrip 中新建 Query Console，执行以下全部 SQL
-- 数据库：wanqing_ai
-- =============================================================================

-- 1. 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS wanqing_ai
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

-- 切换到数据库
USE wanqing_ai;

-- =============================================================================
-- 2. 实验会话表 (experiment_session)
-- 用途：存储每次用户会话的元信息
-- Java 实体：com.wanqing.ai.entity.UserSession
-- =============================================================================

DROP TABLE IF EXISTS experiment_session;

CREATE TABLE experiment_session (
    id              VARCHAR(64)     NOT NULL COMMENT '会话ID (主键)',
    subject_name    VARCHAR(128)   NOT NULL COMMENT '用户姓名',
    experiment_group VARCHAR(64)   NOT NULL COMMENT '实验分组',
    status          VARCHAR(32)   DEFAULT 'ready' COMMENT '会话状态: ready/active/completed',
    create_time     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    INDEX idx_subject_name (subject_name),
    INDEX idx_experiment_group (experiment_group),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='实验会话表';

-- =============================================================================
-- 3. 用户反馈表 (user_feedback)
-- 用途：记录用户对干预弹窗的选择（接受/拒绝/忽略）
-- Java 实体：com.wanqing.ai.entity.UserFeedback
-- =============================================================================

DROP TABLE IF EXISTS user_feedback;

CREATE TABLE user_feedback (
    id                BIGINT       NOT NULL AUTO_INCREMENT COMMENT '反馈ID (主键,自增)',
    session_id        VARCHAR(64)  NOT NULL COMMENT '所属会话ID (关联 experiment_session.id)',
    choice            VARCHAR(32)   NOT NULL COMMENT '用户选择: accepted/rejected/ignored',
    emotion_snapshot  TEXT          COMMENT '反馈时的OCC情感向量JSON',
    current_emotion   VARCHAR(64)  COMMENT '反馈时的情绪标签',
    feedback_time     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '反馈时间',
    PRIMARY KEY (id),
    INDEX idx_session_id (session_id),
    INDEX idx_feedback_time (feedback_time),
    FOREIGN KEY (session_id) REFERENCES experiment_session(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户反馈记录表';

-- =============================================================================
-- 3. 会话对话日志表 (session_logs)
-- 用途：记录每轮对话的完整数据（用户消息、AI 回复、情感状态、干预决策）
-- 来源：Python Agent 通过 /internal/conversation 接口回调 Java 后端写入
-- Java 实体：com.wanqing.ai.entity.SessionLog
-- =============================================================================

DROP TABLE IF EXISTS session_logs;

CREATE TABLE session_logs (
    id                  BIGINT         NOT NULL AUTO_INCREMENT COMMENT '日志ID (主键,自增)',
    session_id         VARCHAR(64)     NOT NULL COMMENT '所属会话ID (关联 experiment_session.id)',
    turn_index          INT            NOT NULL DEFAULT 0 COMMENT '本轮对话序号',

    -- 用户消息
    user_message        TEXT           COMMENT '用户输入的原始消息',

    -- AI 回复
    ai_reply            TEXT           COMMENT '婉晴生成的回复内容',

    -- 干预决策
    intervention_action VARCHAR(32)    COMMENT '干预动作: silent/subtle/intervene',
    intervention_urgency VARCHAR(16)   COMMENT '紧迫度: low/medium/high',
    intervention_score  DECIMAL(5,4)   COMMENT '干预综合分数 [0,1]',

    -- 感知快照（JSON 字段）
    perception_snapshot JSON           COMMENT '感知数据快照（focus_level 等）',

    -- 情感向量（JSON 字段，OCC 八维 + 元信息）
    emotion_vector      JSON           COMMENT '情感融合结果，包含 OCC 八维和 primary_emotion/intensity/arousal/valence/confidence',

    -- 决策详情（JSON 字段）
    decision_detail     JSON           COMMENT '干预决策详情，含打扰成本、策略建议、UI 指令',

    -- 知识检索（JSON 字段，仅 intervene 路径有值）
    retrieved_knowledge JSON           COMMENT 'RAG 检索到的心理学知识卡片',

    -- 元信息
    log_time            DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '本轮决策时间',

    PRIMARY KEY (id),
    INDEX idx_session_id (session_id),
    INDEX idx_log_time (log_time),
    FOREIGN KEY (session_id) REFERENCES experiment_session(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话对话日志表';

-- =============================================================================
-- 4. 验证表结构
-- =============================================================================

SHOW TABLES;

DESCRIBE experiment_session;
DESCRIBE user_feedback;
DESCRIBE session_logs;

-- =============================================================================
-- 5. 测试数据（可选，用于开发测试）
-- =============================================================================

-- 插入一条测试会话
INSERT INTO experiment_session (id, subject_name, experiment_group, status)
VALUES ('sess_test_001', '测试用户', 'test_group', 'ready');

-- 插入一条测试反馈
INSERT INTO user_feedback (session_id, choice, emotion_snapshot, current_emotion)
VALUES ('sess_test_001', 'ignored', '{"喜悦":0.3,"悲伤":0.5,"愤怒":0.1}', '悲伤');

-- 验证
SELECT * FROM experiment_session;
SELECT * FROM user_feedback;

-- =============================================================================
-- 完成！
-- =============================================================================
