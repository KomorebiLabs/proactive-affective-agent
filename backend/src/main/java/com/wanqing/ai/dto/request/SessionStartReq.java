package com.wanqing.ai.dto.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 用户会话初始化请求 DTO
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "前端发起的会话初始化请求")
public class SessionStartReq {

    @JsonProperty("subject_name")
    @Schema(description = "用户姓名", example = "张三")
    @NotBlank(message = "用户姓名不能为空")
    private String subjectName;

    @JsonProperty("experiment_group")
    @Schema(description = "用户分组标识", example = "A_Group")
    @NotBlank(message = "用户分组不能为空")
    private String experimentGroup;
}
