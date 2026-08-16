package com.wanqing.ai.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * 前端反馈请求 DTO
 *
 * 核心职责：
 *   接收前端干预弹窗的用户反馈数据，对应 POST /api/v1/feedback 接口
 *
 * 依赖关系：
 *   - 被 FeedbackController 解析后调用 FeedbackService
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FeedbackRequest {

    /**
     * 会话ID，对应 user_session.id
     */
    @JsonProperty("session_id")
    private String sessionId;

    /**
     * 用户选择：accepted（接受）/ rejected（拒绝）/ ignored（忽略）
     */
    @JsonProperty("choice")
    private String choice;

    /**
     * 反馈时的 OCC 八维情感快照（可选）
     * Map<String, Double>：{"喜悦":0.2, "悲伤":0.8, ...}
     */
    @JsonProperty("emotion_vector")
    @Builder.Default
    private Map<String, Double> emotionVector = Map.of();

    /**
     * 反馈时的情绪标签（可选）
     */
    @JsonProperty("current_emotion")
    @Builder.Default
    private String currentEmotion = "";
}
