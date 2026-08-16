package com.wanqing.ai.dto.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * 内部接收 Python Agent SSE 响应的解析实体。
 * 字段与 Python main.py _stream_reply() 发出的 JSON 完全对齐。
 *
 * 序列化说明：
 * - 字段命名策略由 Spring Bean JacksonConfig 全局配置（PropertyNamingStrategies.SNAKE_CASE）
 * - 显式 @JsonProperty 用于控制 JSON→Java 解析时的字段映射
 * - 字段命名示例：isEnd → is_end, uiAction → ui_action, showPopup → show_popup
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentInvokeResp {

    @JsonProperty("chunk")
    private String chunk;

    @JsonProperty("is_end")
    private Boolean isEnd;

    @JsonProperty("reply")
    private String reply;

    @JsonProperty("ui_action")
    private UiAction uiAction;

    /**
     * OCC 八维情感向量（is_end=true 时有效）。
     * Map 键：喜悦/悲伤/愤怒/恐惧/厌恶/惊讶/踏实感/期待
     * Map 值：0.0~1.0 浮点数
     */
    @JsonProperty("vector")
    private Map<String, Double> vector;

    /**
     * 干预策略名称（如"5-4-3-2-1着陆技术"）
     */
    @JsonProperty("strategy")
    private String strategy;

    /**
     * 紧迫程度：low / medium / high
     */
    @JsonProperty("urgency")
    private String urgency;

    /**
     * 干预决策动作：silent / subtle / intervene
     * 用于前端和 Java 逻辑判断是否需要干预弹窗。
     */
    @JsonProperty("action")
    private String action;

    /**
     * 干预紧迫度评分（0.0 ~ 1.0），由 Agent 计算得出
     */
    @JsonProperty("intervention_score")
    private Double interventionScore;

    /**
     * 本次调用的唯一追踪 ID（Plan1-A）
     */
    @JsonProperty("trace_id")
    private String traceId;

    /**
     * 毫秒级时间戳（Plan1-A）
     */
    @JsonProperty("timestamp_ms")
    private Long timestampMs;

    /**
     * 当前会话 ID（Plan1-A）
     */
    @JsonProperty("session_id")
    private String sessionId;

    /**
     * 干预弹窗信息（is_end=true 且 needed=true 时携带）。
     * 若 show_popup=true，前端应弹出干预关怀弹窗。
     */
    @JsonProperty("intervention_alert")
    private InterventionAlert interventionAlert;

    // ==================== Plan1-E: 结构化错误帧字段 ====================
    /** 错误标记，true 表示本帧为错误帧 */
    @JsonProperty("is_error")
    private Boolean isError;

    /** 错误码，用于前端判断错误类型 */
    @JsonProperty("error_code")
    private String errorCode;

    /** 错误信息描述 */
    @JsonProperty("error_message")
    private String errorMessage;

    /** 是否可恢复，true=可重试，false=需人工介入 */
    @JsonProperty("recoverable")
    private Boolean recoverable;

    /** 干预弹窗数据（统一 snake_case） */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class InterventionAlert {
        /** 是否显示弹窗 */
        @JsonProperty("show_popup")
        private Boolean showPopup;
        /** 紧迫程度：low / medium / high */
        @JsonProperty("urgency")
        private String urgency;
        /** 弹窗文案 */
        @JsonProperty("message")
        private String message;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UiAction {
        /** 光晕颜色: blue / orange / green / purple / neutral */
        @JsonProperty("color")
        private String color;
        /** 脉冲频率: slow / medium / fast / very_fast */
        @JsonProperty("pulse")
        private String pulse;
    }
}
