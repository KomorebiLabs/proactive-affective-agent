package com.wanqing.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.wanqing.ai.client.AgentClient;
import com.wanqing.ai.dto.request.AgentInvokeReq;
import com.wanqing.ai.dto.request.ChatMessageReq;
import com.wanqing.ai.dto.response.AgentInvokeResp;
import com.wanqing.ai.entity.UserSession;
import com.wanqing.ai.service.EmotionHistoryService;
import com.wanqing.ai.service.FeedbackService;
import com.wanqing.ai.service.SessionService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.PreDestroy;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 客户端聊天核心控制器
 *
 * 核心职责：
 *   1. 接收前端 SSE 流式聊天请求，转发给 Python Agent（/internal/v1/agent/invoke）
 *   2. 将 Python Agent 的 SSE 响应实时透传给前端
 *   3. 在 SSE 最终帧上注入干预弹窗信息（intervention_alert）
 *   4. 将 OCC 情感向量写入 Redis
 *
 * 数据流：前端 → ChatController → AgentClient → Python Agent → ChatController（SSE）→ 前端
 *
 * 实现说明：
 *   使用 SseEmitter 实现 SSE 流，保证每一帧都能实时推送到前端。
 *   SseEmitter 是 Spring MVC 的 SSE 实现，相比 Flux<T> 更适合这种场景。
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/chat")
@RequiredArgsConstructor
@Tag(name = "核心对话", description = "与婉晴进行文字交流的 SSE 流式接口")
public class ChatController {

    private final AgentClient agentClient;
    private final SessionService sessionService;
    private final EmotionHistoryService emotionHistoryService;
    private final FeedbackService feedbackService;
    private final ObjectMapper objectMapper;
    private final StringRedisTemplate redisTemplate;

    /** SSE 超时时间（毫秒）：5 分钟足够长，足够等待 LLM 生成回复 */
    private static final long SSE_TIMEOUT = 5 * 60 * 1000L;

    /** 线程池：用于异步发送 SSE 事件（有界，防止请求峰值下线程失控；随 Bean 生命周期关闭） */
    private final ExecutorService sseExecutor = Executors.newFixedThreadPool(
            Math.max(8, Runtime.getRuntime().availableProcessors() * 2));

    @PreDestroy
    void shutdownSseExecutor() {
        sseExecutor.shutdown();
    }

    /**
     * 前端发起的流式对话请求
     *
     * 使用 SseEmitter 实现 SSE，保证流式推送的实时性。
     *
     * @param sessionId 从 Header 获取的会话 ID
     * @param request   客户端发来的消息
     * @return SseEmitter（SSE 连接对象）
     */
    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @Operation(summary = "流式聊天响应 (SSE)", description = "接收客户端文本并逐字返回 AI 拼装的回复及 UI 动作")
    public ResponseEntity<ResponseBodyEmitter> chatStream(
            @RequestHeader(value = "Authorization", required = false) String sessionId,
            @Valid @RequestBody ChatMessageReq request) {

        // 空值检查
        if (sessionId == null || sessionId.isBlank()) {
            log.warn("【ChatController】Authorization Header 为空或缺失");
            return ResponseEntity.badRequest().build();
        }

        // 解析 Bearer token
        final String realSessionId = sessionId.trim().startsWith("Bearer ")
                ? sessionId.substring(7).trim()
                : sessionId.trim();

        log.info("【ChatController】收到前端消息 Session: [{}], Text: [{}]",
                realSessionId, request.getMessage());

        // 1. 验证会话是否存在
        UserSession session = sessionService.getSessionById(realSessionId);
        if (session == null) {
            log.warn("【ChatController】会话不存在: {}", realSessionId);
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }

        // 2. 构建 SSE Emitter
        // 超时时间设为 5 分钟足够等待 LLM 生成回复
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT);

        // 设置完成/错误的回调
        emitter.onCompletion(() -> log.info("【ChatController】SSE 连接完成: session={}", realSessionId));
        emitter.onTimeout(() -> log.warn("【ChatController】SSE 连接超时: session={}", realSessionId));
        emitter.onError(e -> log.error("【ChatController】SSE 连接异常: session={}, error={}", realSessionId, e.getMessage()));

        // 3. 异步执行 Agent 调用，结果通过 emitter 发送 SSE 事件
        sseExecutor.submit(() -> {
            try {
                // 3.1 先把用户消息写入 Redis 对话历史（修复上下文丢失问题）
                try {
                    String historyKey = "session:" + realSessionId + ":history";
                    Map<String, Object> userMsg = new java.util.HashMap<>();
                    userMsg.put("role", "user");
                    userMsg.put("content", request.getMessage());
                    userMsg.put("timestamp", System.currentTimeMillis());
                    String msgJson = objectMapper.writeValueAsString(userMsg);

                    // 写入用户消息
                    redisTemplate.opsForList().leftPush(historyKey, msgJson);
                    // 限制历史长度（保留最新20条）
                    redisTemplate.opsForList().trim(historyKey, 0, 19);
                    // 设置过期时间（2小时，与 Python 端保持一致）
                    redisTemplate.expire(historyKey, java.time.Duration.ofHours(2));

                    log.info("【ChatController】用户消息已写入 Redis 历史: {}", request.getMessage().substring(0, Math.min(20, request.getMessage().length())));
                } catch (Exception e) {
                    log.warn("【ChatController】写入用户消息到 Redis 失败: {}", e.getMessage());
                }

                // 3.2 读取对话历史（从 Redis，包含刚才写入的用户消息）
                String historyKey = "session:" + realSessionId + ":history";
                List<String> rawHistory = redisTemplate.opsForList().range(historyKey, 0, -1);
                // 翻转顺序：Redis LPUSH 是新在前，需要手动反转成时间正序（老→新）
                final List<String> conversationHistory;
                if (rawHistory != null && !rawHistory.isEmpty()) {
                    Collections.reverse(rawHistory);
                    conversationHistory = rawHistory;
                } else {
                    conversationHistory = Collections.emptyList();
                }

                // 3.3 构建 Agent 请求
                List<Map<String, Object>> emotionHistory =
                        emotionHistoryService.getEmotionHistory(realSessionId, 10);

                // 读取反馈统计
                double penalty = 1.0;
                try {
                    Map<String, Object> feedbackStats = feedbackService.getFeedbackStats(realSessionId);
                    if (feedbackStats != null && !feedbackStats.isEmpty()) {
                        Object rrObj = feedbackStats.get("rejection_rate");
                        if (rrObj instanceof Number) {
                            double rejectionRate = ((Number) rrObj).doubleValue();
                            penalty = Math.max(0.5, Math.min(1.5, 1.0 + rejectionRate * 0.5));
                        }
                    }
                } catch (Exception e) {
                    log.warn("【ChatController】读取反馈统计失败: {}", e.getMessage());
                }

                // 3.4 构建 Agent 请求（传入对话历史供 Agent 参考上下文）
                AgentInvokeReq agentReq = AgentInvokeReq.builder()
                        .sessionId(realSessionId)
                        .userId(session.getSubjectName())
                        .userMessage(request.getMessage())
                        .taskPhase(session.getStatus() != null ? session.getStatus() : "companion_task")
                        .emotionHistory(emotionHistory)
                        .conversationHistory(conversationHistory)
                        .historyLimit(10)
                        .userRejectionPenalty(penalty)
                        .build();

                // 调用 Agent 并处理 SSE 流
                long agentStartTime = System.currentTimeMillis();
                log.info("【ChatController】开始调用 Agent: {}", agentStartTime);
                agentClient.callAgentStream(agentReq)
                        .doOnNext(resp -> {
                            long now = System.currentTimeMillis();
                            try {
                                // 【Plan1-P0-2】单帧模式：只有最终帧才发送，干预弹窗信息合并到同一帧
                                if (!Boolean.TRUE.equals(resp.getIsEnd())) {
                                    // 非最终帧：直接透传
                                    String jsonData = objectMapper.writeValueAsString(resp);
                                    emitter.send(SseEmitter.event()
                                            .name("message")
                                            .data(jsonData));
                                    log.debug("【ChatController→前端】发送 SSE 帧: is_end=false, chunk={}",
                                            resp.getChunk());
                                } else {
                                    // 最终帧：构建包含干预弹窗信息的完整帧（只发送一次）
                                    // 【Plan1-C】语义对齐：silent 时 urgency=low, shouldPopup=false
                                    String action = resp.getAction() != null ? resp.getAction() : "subtle";
                                    String urgency = resp.getUrgency() != null ? resp.getUrgency() : "low";
                                    boolean isSilentAction = "silent".equalsIgnoreCase(action);
                                    boolean shouldPopup = !isSilentAction && !"low".equalsIgnoreCase(urgency);

                                    if (isSilentAction) {
                                        urgency = "low";
                                        shouldPopup = false;
                                    }

                                    String popupMessage = _generatePopupMessage(urgency, resp.getReply());

                                    // 构建单次最终帧（包含所有信息）
                                    AgentInvokeResp finalResp = AgentInvokeResp.builder()
                                            .chunk(resp.getChunk())
                                            .isEnd(true)
                                            .reply(resp.getReply())
                                            .uiAction(resp.getUiAction())
                                            .vector(resp.getVector())
                                            .action(action)
                                            .urgency(urgency)
                                            .strategy(resp.getStrategy())
                                            .interventionScore(resp.getInterventionScore())
                                            .traceId(resp.getTraceId())
                                            .timestampMs(now)
                                            .sessionId(realSessionId)
                                            .interventionAlert(AgentInvokeResp.InterventionAlert.builder()
                                                    .showPopup(shouldPopup)
                                                    .urgency(urgency)
                                                    .message(popupMessage)
                                                    .build())
                                            .build();

                                    String jsonData = objectMapper.writeValueAsString(finalResp);
                                    emitter.send(SseEmitter.event()
                                            .name("message")
                                            .data(jsonData));

                                    // 【Plan1-P1-3】统一追踪日志格式
                                    log.info("【ChatController→前端】最终帧: trace_id={}, session_id={}, action={}, urgency={}, is_end=true, 耗时={}ms",
                                            resp.getTraceId(), realSessionId, action, urgency, now - agentStartTime);

                                    // 5. 在流结束时写入情感历史到 Redis
                                    if (resp.getVector() != null) {
                                        try {
                                            String primaryEmotion = resp.getVector().entrySet().stream()
                                                    .max(Map.Entry.comparingByValue())
                                                    .map(Map.Entry::getKey)
                                                    .orElse("中性");
                                            double intensity = resp.getVector().values().stream()
                                                    .mapToDouble(Double::doubleValue)
                                                    .max()
                                                    .orElse(0.0);

                                            Map<String, Object> emotionEntry = Map.of(
                                                    "timestamp", now,
                                                    "primary_emotion", primaryEmotion,
                                                    "intensity", intensity
                                            );
                                            emotionHistoryService.appendEmotionHistory(realSessionId, emotionEntry);
                                            log.info("【ChatController】情感历史已写入 Redis: emotion={}, intensity={}",
                                                    primaryEmotion, intensity);
                                        } catch (Exception e) {
                                            log.warn("【ChatController】写入情感历史失败: {}", e.getMessage());
                                        }
                                    }
                                }

                            } catch (IOException e) {
                                log.error("【ChatController】SSE 发送失败: {}", e.getMessage());
                                emitter.completeWithError(e);
                            }
                        })
                        .doOnComplete(() -> {
                            try {
                                // 发送 SSE 结束事件
                                emitter.send(SseEmitter.event()
                                        .name("end")
                                        .comment("婉晴回复完毕"));
                                emitter.complete();
                                log.info("【ChatController】SSE 流推送完毕: session={}", realSessionId);
                            } catch (IOException e) {
                                log.warn("【ChatController】SSE 完成事件发送失败: {}", e.getMessage());
                                emitter.completeWithError(e);
                            }
                        })
                        .doOnError(e -> {
                            log.error("【ChatController】Agent SSE 流异常: {}", e.getMessage());
                            // 【Plan1-E/P1-1】结构化错误帧（包含 session_id）
                            try {
                                long now = System.currentTimeMillis();
                                AgentInvokeResp errorResp = AgentInvokeResp.builder()
                                        .isEnd(true)
                                        .reply("婉晴暂时无法回复，请稍后重试。")
                                        .action("subtle")
                                        .urgency("low")
                                        .traceId("error-sse-" + now)
                                        .timestampMs(now)
                                        .sessionId(realSessionId)
                                        .isError(true)
                                        .errorCode("AGENT_SSE_ERROR")
                                        .errorMessage("婉晴暂时无法回复，请稍后重试。")
                                        .recoverable(true)
                                        .build();
                                emitter.send(SseEmitter.event()
                                        .name("error")
                                        .data(objectMapper.writeValueAsString(errorResp)));
                            } catch (IOException ioEx) {
                                log.warn("【ChatController】SSE 错误事件发送失败: {}", ioEx.getMessage());
                            }
                            emitter.completeWithError(e);
                        })
                        .subscribe();

            } catch (Exception e) {
                log.error("【ChatController】Agent 调用前异常: {}", e.getMessage());
                // 【Plan1-E/P1-1】结构化错误帧（包含 session_id）
                try {
                    long now = System.currentTimeMillis();
                    AgentInvokeResp errorResp = AgentInvokeResp.builder()
                            .isEnd(true)
                            .reply("婉晴暂时无法回复，请稍后重试。")
                            .action("subtle")
                            .urgency("low")
                            .traceId("error-precall-" + now)
                            .timestampMs(now)
                            .sessionId(realSessionId)
                            .isError(true)
                            .errorCode("AGENT_PRE_CALL_ERROR")
                            .errorMessage("婉晴暂时无法回复，请稍后重试。")
                            .recoverable(true)
                            .build();
                    emitter.send(SseEmitter.event()
                            .name("error")
                            .data(objectMapper.writeValueAsString(errorResp)));
                } catch (IOException ioEx) {
                    log.warn("SSE 错误事件发送失败: {}", ioEx.getMessage());
                }
                emitter.completeWithError(e);
            }
        });

        // 返回 ResponseEntity with SseEmitter
        // Spring MVC 会自动处理 SseEmitter，将 SSE 事件流式发送给客户端
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType("text/event-stream"))
                .header("Cache-Control", "no-cache, no-transform")
                .header("X-Accel-Buffering", "no")  // 禁用 Nginx 缓冲
                .body(emitter);
    }

    /**
     * 根据 urgency 等级和 Agent 回复生成弹窗文案
     */
    private String _generatePopupMessage(String urgency, String agentReply) {
        if (agentReply != null && !agentReply.isBlank()) {
            return agentReply.length() > 30
                    ? agentReply.substring(0, 30) + "…"
                    : agentReply;
        }
        switch (urgency != null ? urgency.toLowerCase() : "low") {
            case "high":
                return "婉晴很担心你，现在方便聊一聊吗？";
            case "medium":
                return "婉晴感受到你可能心情有些不好，需要聊聊吗？";
            default:
                return "婉晴在这里，随时愿意倾听。";
        }
    }
}
