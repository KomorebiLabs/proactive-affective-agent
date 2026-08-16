-- ============================================================
-- 婉情AI - 用户反馈表迁移脚本
-- ============================================================
-- 用途：记录用户对干预弹窗的选择（接受/拒绝/忽略）
--      数据用于：(1) 持久化存储；(2) 同步 Redis 供 Python Agent 实时读取
-- 执行：mysql -u root -p wanqing_ai < backend/src/main/resources/migration/V001__create_user_feedback.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS `user_feedback` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    `session_id` VARCHAR(64) NOT NULL COMMENT '所属会话 ID，关联 user_session.id',
    `choice` VARCHAR(20) NOT NULL COMMENT '用户选择：accepted / rejected / ignored',
    `emotion_snapshot` TEXT COMMENT '反馈时的 OCC 八维情感向量（JSON 字符串），示例：{"喜悦":0.2,"悲伤":0.8,...}',
    `current_emotion` VARCHAR(20) DEFAULT '' COMMENT '反馈时的情绪标签（如"焦虑"、"悲伤"）',
    `feedback_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '反馈时间',
    INDEX `idx_session_id` (`session_id`),
    INDEX `idx_feedback_time` (`feedback_time`),
    INDEX `idx_choice` (`choice`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户干预反馈记录表';
