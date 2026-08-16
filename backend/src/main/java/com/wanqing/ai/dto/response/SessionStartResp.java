package com.wanqing.ai.dto.response;

import com.fasterxml.jackson.annotation.JsonProperty;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 用户会话初始化响应 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "用户会话初始化响应结果")
public class SessionStartResp {

    @JsonProperty("session_id")
    @Schema(description = "生成的唯一会话 ID", example = "sess_123456789")
    private String sessionId;

    @JsonProperty("status")
    @Schema(description = "当前会话状态", example = "ready")
    private String status;

}
