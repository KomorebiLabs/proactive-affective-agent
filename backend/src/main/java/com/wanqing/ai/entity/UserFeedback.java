package com.wanqing.ai.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.time.LocalDateTime;

/**
 * 用户干预反馈记录
 * 记录每次干预弹窗的用户选择（接受/拒绝/忽略），用于动态调整干预决策参数
 */
@Data
@Accessors(chain = true)
@TableName("user_feedback")
public class UserFeedback {

    /**
     * 主键，自增
     */
    @TableId(type = IdType.AUTO)
    private Long id;

    /**
     * 所属会话 ID，关联 user_session.id（映射：session_id）
     */
    @TableField("session_id")
    private String sessionId;

    /**
     * 用户选择：accepted / rejected / ignored
     */
    private String choice;

    /**
     * 反馈时的 OCC 八维情感向量（JSON 字符串，映射：emotion_snapshot）
     * 示例：{"喜悦":0.2,"悲伤":0.8,...}
     */
    @TableField("emotion_snapshot")
    private String emotionSnapshot;

    /**
     * 反馈时的情绪标签（映射：current_emotion）
     */
    @TableField("current_emotion")
    private String currentEmotion;

    /**
     * 反馈时间（映射：feedback_time）
     */
    @TableField("feedback_time")
    private LocalDateTime feedbackTime;
}
