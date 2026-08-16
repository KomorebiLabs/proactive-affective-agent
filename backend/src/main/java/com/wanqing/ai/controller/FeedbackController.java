package com.wanqing.ai.controller;

import com.wanqing.ai.common.Result;
import com.wanqing.ai.dto.request.FeedbackRequest;
import com.wanqing.ai.service.FeedbackService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 用户反馈控制器
 *
 * 核心职责：
 *   接收前端干预弹窗的用户选择（接受/拒绝/忽略），写入 MySQL 并同步到 Redis
 *   Redis 中的统计数据由 ChatController 在调用 Python Agent 前读取，用于计算 user_rejection_penalty
 *
 * 依赖关系：
 *   - 被前端 HTTP POST /api/v1/feedback 调用
 *   - 依赖 FeedbackService 执行具体业务逻辑
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/feedback")
@RequiredArgsConstructor
@Tag(name = "用户反馈", description = "干预弹窗用户反馈相关接口")
public class FeedbackController {

    private final FeedbackService feedbackService;

    @PostMapping
    @Operation(
        summary = "记录用户反馈",
        description = "接收前端干预弹窗的用户选择（接受/拒绝/忽略），写入 MySQL 并同步 Redis 供 Python Agent 调整干预策略"
    )
    public Result<Void> recordFeedback(@RequestBody FeedbackRequest request) {
        if (request.getSessionId() == null || request.getSessionId().isBlank()) {
            return Result.fail(400, "session_id 不能为空");
        }
        String choice = request.getChoice();
        if (choice == null || (!choice.equals("accepted") && !choice.equals("rejected") && !choice.equals("ignored"))) {
            return Result.fail(400, "choice 必须为 accepted / rejected / ignored 之一");
        }

        feedbackService.recordFeedback(
                request.getSessionId(),
                choice,
                request.getEmotionVector(),
                request.getCurrentEmotion()
        );

        return Result.success(null);
    }
}
