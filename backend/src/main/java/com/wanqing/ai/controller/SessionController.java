package com.wanqing.ai.controller;

import com.wanqing.ai.common.Result;
import com.wanqing.ai.dto.request.SessionStartReq;
import com.wanqing.ai.dto.response.SessionStartResp;
import com.wanqing.ai.service.SessionService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 会话管理控制器
 *
 * 核心职责：
 *   1. 接收前端会话初始化请求，调用 SessionService 创建会话
 *   2. 返回唯一 session_id，供前端在后续请求的 Authorization Header 中使用
 *
 * 依赖关系：
 *   - 被前端 HTTP POST /api/v1/session/start 调用
 *   - 依赖 SessionService 执行具体业务逻辑
 */
@RestController
@RequestMapping("/api/v1/session")
@RequiredArgsConstructor
@Tag(name = "会话管理", description = "用户会话相关的基础接口")
public class SessionController {

    private final SessionService sessionService;

    @PostMapping("/start")
    @Operation(summary = "初始化用户会话", description = "记录用户信息，生成唯一会话 ID")
    public Result<SessionStartResp> startSession(@Valid @RequestBody SessionStartReq request) {
        SessionStartResp response = sessionService.startSession(request);
        return Result.success(response);
    }
}
