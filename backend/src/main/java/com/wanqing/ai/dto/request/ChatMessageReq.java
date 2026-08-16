package com.wanqing.ai.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 客户端前端发起的聊天请求
 */
@Data
@NoArgsConstructor
@Schema(description = "前端发起的聊天请求")
public class ChatMessageReq {

    @Schema(description = "用户输入的文本消息", example = "我今天真的很难受，代码一直报错。")
    @NotBlank(message = "消息内容不能为空")
    @JsonProperty("message")
    private String message;
}
