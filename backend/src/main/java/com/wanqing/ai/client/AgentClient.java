package com.wanqing.ai.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.wanqing.ai.dto.request.AgentInvokeReq;
import com.wanqing.ai.dto.response.AgentInvokeResp;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Flux;
import reactor.util.retry.Retry;

import java.time.Duration;

/**
 * 与 Python Agent 引擎通信的专用客户端。
 *
 * SSE 协议说明：
 *   Python Agent 通过 /internal/v1/agent/invoke 返回 SSE 流（text/event-stream）。
 *   每帧格式为：data: {"chunk": "...", "is_end": true, ...}\n\n
 *   Java WebClient 使用 exchangeToFlux 直接处理原始 SSE 文本，
 *   逐行解析并去掉 "data: " 前缀，再将 JSON 反序列化为 AgentInvokeResp。
 *
 * 架构说明：
 *   Java(8080) → Python Agent(8001) [LangGraph 状态机推理]
 *   Java(8080) → Python 感知服务(8000) [仅用于 session 切换通知]
 *
 * 降级说明：
 *   当 Python Agent 不可用时，通过 onErrorResume 返回一条错误响应帧，
 *   前端会收到一条 is_end=true 的错误消息。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentClient {

    private final ObjectMapper objectMapper;

    @Value("${agent.engine.url:http://localhost:8001}")
    private String agentEngineUrl;

    /** SSE 单次请求超时（秒） */
    @Value("${agent.engine.timeout:60}")
    private int agentTimeout;

    /**
     * 发起调用并接收由 Python Agent 返回的 SSE 数据流。
     */
    public Flux<AgentInvokeResp> callAgentStream(AgentInvokeReq request) {

        log.info("【AgentClient】调用 Python Agent: URL={}, session={}, timeout={}s",
                agentEngineUrl, request.getSessionId(), agentTimeout);

        WebClient webClient = WebClient.builder()
                .baseUrl(agentEngineUrl)
                .defaultHeader("Accept", "text/event-stream")
                .defaultHeader("Cache-Control", "no-cache")
                .build();

        // 使用 exchangeToFlux 获得对响应的完全控制
        return webClient.post()
                .uri("/internal/v1/agent/invoke")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Cache-Control", "no-cache")
                .header("Accept", "text/event-stream")
                .bodyValue(request)
                .exchangeToFlux(clientResponse -> {
                    if (clientResponse.statusCode().is2xxSuccessful()) {
                        log.info("【AgentClient】收到 200 OK，开始处理 SSE 流");
                        return clientResponse.bodyToFlux(String.class);
                    } else {
                        log.error("【AgentClient】Agent 返回错误状态码: {}", clientResponse.statusCode());
                        return Flux.error(new RuntimeException("Agent 返回错误状态: " + clientResponse.statusCode()));
                    }
                })
                .doOnNext(line -> {
                    long receiveTime = System.currentTimeMillis();
                    log.info("【AgentClient 原始行】收到时间={}, 内容='{}...'", receiveTime, line.length() > 50 ? line.substring(0, 50) : line);
                })
                // 过滤空行和注释行（: 开头的是 SSE 注释）
                .filter(line -> line != null && !line.trim().isEmpty() && !line.trim().startsWith(":"))
                // 逐行解析 SSE 帧（兼容 "data: " 和 "data:" 两种格式）
                .map(line -> {
                    String jsonStr = line.trim();
                    if (jsonStr.startsWith("data: ")) {
                        jsonStr = jsonStr.substring("data: ".length()).trim();
                    } else if (jsonStr.startsWith("data:")) {
                        jsonStr = jsonStr.substring("data:".length()).trim();
                    }
                    if (jsonStr.isEmpty()) {
                        return null;
                    }
                    try {
                        AgentInvokeResp resp = objectMapper.readValue(jsonStr, AgentInvokeResp.class);
                        log.info("【AgentClient Chunk】 chunk='{}' | is_end={} | action={} | urgency={}",
                                resp.getChunk(), resp.getIsEnd(), resp.getAction(), resp.getUrgency());
                        return resp;
                    } catch (Exception e) {
                        log.warn("【AgentClient】SSE JSON 解析失败（已跳过该帧）: {} | raw='{}'",
                                e.getMessage(),
                                jsonStr.length() > 80 ? jsonStr.substring(0, 80) + "..." : jsonStr);
                        return null;
                    }
                })
                .filter(resp -> resp != null)
                // 设置超时
                .timeout(Duration.ofSeconds(agentTimeout))
                // 最多重试 2 次，每次间隔 1 秒
                .retryWhen(Retry.backoff(2, Duration.ofSeconds(1))
                        .filter(ex -> ex instanceof WebClientResponseException
                                || ex instanceof java.net.ConnectException
                                || ex instanceof java.net.SocketTimeoutException)
                        .doBeforeRetry(signal -> log.warn(
                                "【AgentClient】Agent 连接失败（第 {} 次重试）: {}",
                                signal.totalRetries() + 1,
                                signal.failure().getMessage())))
                // 重试全部失败时，返回降级错误帧
                .onErrorResume(ex -> {
                    log.error("【AgentClient】Agent 调用最终失败（已重试 2 次），返回降级响应: {}",
                            ex.getMessage());
                    AgentInvokeResp fallback = AgentInvokeResp.builder()
                            .isEnd(true)
                            .reply("婉晴暂时无法回复（Agent 服务不可用），请稍后重试。")
                            .build();
                    return Flux.just(fallback);
                })
                .doOnError(e -> log.error("【AgentClient】调用 Python Agent 发生未捕获异常: ", e));
    }
}
