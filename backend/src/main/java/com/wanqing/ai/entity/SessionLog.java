package com.wanqing.ai.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 会话对话日志实体类
 *
 * 记录每轮对话的完整数据（用户消息、AI 回复、情感状态、干预决策）。
 * 数据来源：Python Agent 通过 /internal/conversation 接口回调 Java 后端写入。
 *
 * 关联表：experiment_session（会话元信息）
 */
@Data
@Accessors(chain = true)
@TableName("session_logs")
public class SessionLog {

    /**
     * 主键，自增
     */
    @TableId(type = IdType.AUTO)
    private Long id;

    /**
     * 所属会话 ID，关联 experiment_session.id
     */
    @TableField("session_id")
    private String sessionId;

    /**
     * 本轮对话序号（同一会话内按顺序递增）
     */
    @TableField("turn_index")
    private Integer turnIndex;

    /**
     * 用户输入的原始消息
     */
    @TableField("user_message")
    private String userMessage;

    /**
     * 婉晴生成的回复内容
     */
    @TableField("ai_reply")
    private String aiReply;

    /**
     * 干预动作：silent / subtle / intervene
     */
    @TableField("intervention_action")
    private String interventionAction;

    /**
     * 紧迫度：low / medium / high
     */
    @TableField("intervention_urgency")
    private String interventionUrgency;

    /**
     * 干预综合分数 [0,1]，4位小数精度
     */
    @TableField("intervention_score")
    private BigDecimal interventionScore;

    /**
     * 感知数据快照（JSON）
     */
    @TableField("perception_snapshot")
    private String perceptionSnapshot;

    /**
     * 情感融合结果（OCC 八维 + 元信息，JSON）
     */
    @TableField("emotion_vector")
    private String emotionVector;

    /**
     * 干预决策详情（JSON，含打扰成本、策略建议、UI 指令）
     */
    @TableField("decision_detail")
    private String decisionDetail;

    /**
     * RAG 检索到的心理学知识卡片（JSON，仅 intervene 路径有值）
     */
    @TableField("retrieved_knowledge")
    private String retrievedKnowledge;

    /**
     * 本轮决策时间
     */
    @TableField("log_time")
    private LocalDateTime logTime;
}
