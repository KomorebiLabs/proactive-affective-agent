package com.wanqing.ai.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

/**
 * 内部请求 Agent 引擎的 DTO
 * 与 Python Agent 的 /internal/v1/agent/invoke 接口字段完全对齐
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentInvokeReq {

    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("user_id")
    @Builder.Default
    private String userId = "";

    @JsonProperty("user_message")
    private String userMessage;

    @Builder.Default
    @JsonProperty("history_limit")
    private Integer historyLimit = 10;

    @JsonProperty("task_phase")
    @Builder.Default
    private String taskPhase = "unknown";

    /**
     * 近期情感历史，供 Python Agent 进行趋势分析。
     * 每条记录含 timestamp(int, ms) / primary_emotion(string) / intensity(float)
     */
    @JsonProperty("emotion_history")
    @Builder.Default
    private List<Map<String, Object>> emotionHistory = List.of();

    /**
     * 用户拒绝惩罚系数，供 Python Agent 的 decide_intervention 节点调整打扰成本。
     * 计算方式：penalty = 1.0 + rejection_rate * 0.5，范围 [0.5, 1.5]。
     * rejection_rate = rejected / total（最近反馈中拒绝比例）。
     * Python 端：interrupt_cost = interrupt_cost * penalty（越大越保守）。
     */
    @JsonProperty("user_rejection_penalty")
    @Builder.Default
    private Double userRejectionPenalty = 1.0;

    /**
     * 对话历史，供 Python Agent 生成回复时提供上下文。
     * 每条记录是 JSON 字符串，含 role("user"/"ai") 和 content 字段。
     * 由 Java 在调用 Agent 前写入 Redis 并通过此字段传入。
     */
    @JsonProperty("conversation_history")
    @Builder.Default
    private List<String> conversationHistory = List.of();
}
