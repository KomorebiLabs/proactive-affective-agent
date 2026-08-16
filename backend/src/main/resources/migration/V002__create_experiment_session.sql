-- ============================================================
-- 婉情AI - 用户会话表迁移脚本
-- ============================================================
-- 用途：记录每次用户会话的基本信息
--      包含会话ID、用户信息、分组、状态等
-- 执行：mysql -u root -p wanqing_ai < backend/src/main/resources/migration/V002__create_experiment_session.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS `experiment_session` (
    `id` VARCHAR(64) PRIMARY KEY COMMENT '主键，存储 session_id (sess_ 前缀 + UUID)',
    `subject_name` VARCHAR(64) NOT NULL COMMENT '用户姓名/匿名标识',
    `experiment_group` VARCHAR(32) NOT NULL COMMENT '实验分组标识',
    `status` VARCHAR(20) DEFAULT 'ready' COMMENT '会话状态：ready/active/completed',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_subject_name` (`subject_name`),
    INDEX `idx_experiment_group` (`experiment_group`),
    INDEX `idx_status` (`status`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户会话记录表';
