package com.wanqing.ai.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 全局异常统一捕获处理机制
 *
 * 核心目标：解决 SSE 流式接口（/chat/stream）的异常处理困境。
 *
 * 问题背景：
 *   SSE 端点返回 Content-Type: text/event-stream，当异常被 @ExceptionHandler 捕获后，
 *   若尝试返回 JSON 格式的 Result<Void>，Jackson 会将其序列化为 LinkedHashMap，
 *   导致 HttpMessageNotWritableException（没有 Map→SSE 的转换器）。
 *
 * 解决方案：
 *   检测到 SSE 相关端点的异常时，改为通过 SseEmitter 写入错误帧，
 *   不走普通 JSON 响应路径。
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /**
     * SSE 流式端点的统一异常处理入口。
     *
     * 当 SSE 端点抛出异常时，Spring MVC 会尝试通过 @ExceptionHandler 处理。
     * 此方法拦截 SSE 场景，返回一个特殊的 ResponseEntity<SseEmitter>，
     * 直接向客户端写入错误 SSE 帧并立即完成连接。
     *
     * 判断依据：方法返回类型是 ResponseEntity<?>
     * 且泛型为 SseEmitter 或 ResponseBodyEmitter
     *
     * 【已废弃此方案】改用 controller 内 try-catch 直接写入 emitter
     * 此方法仅作为最后的兜底保障
     */
    @ExceptionHandler(SseStreamingException.class)
    public ResponseEntity<SseEmitter> handleSseStreamingException(SseStreamingException e) {
        log.error("【SSE 全局异常】: {}", e.getMessage(), e);

        SseEmitter emitter = new SseEmitter(10_000L); // 10秒超时
        try {
            emitter.send(SseEmitter.event()
                    .name("error")
                    .data("{\"error\":\"服务处理异常，婉晴暂时无法回应，请稍后重试。\"}"));
        } catch (Exception sendErr) {
            log.warn("【SSE 全局异常】写入错误帧失败: {}", sendErr.getMessage());
        }
        emitter.complete();

        return ResponseEntity
                .status(HttpStatus.INTERNAL_SERVER_ERROR)
                .contentType(org.springframework.http.MediaType.TEXT_EVENT_STREAM)
                .body(emitter);
    }

    /**
     * 验证异常处理（参数校验失败时触发）
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<?> handleValidationException(MethodArgumentNotValidException e) {
        String message = e.getBindingResult().getFieldErrors().stream()
                .map(err -> err.getField() + ": " + err.getDefaultMessage())
                .findFirst()
                .orElse("参数校验失败");
        log.warn("【参数校验失败】: {}", message);
        return ResponseEntity.badRequest().body(Result.fail(400, message));
    }

    /**
     * 处理业务运行期异常（普通 JSON 接口）
     * @param e RuntimeException 异常对象
     * @return 统一错误响应包装附带详细信息
     */
    @ExceptionHandler(RuntimeException.class)
    public Result<Void> handleRuntimeException(RuntimeException e) {
        log.error("【系统运行时异常拦截】: ", e);
        // 若是 SSE 异常本身，直接返回 null 避免重复处理
        if (e instanceof SseStreamingException) {
            return null;
        }
        return Result.fail(ResultCode.SYSTEM_ERROR.getCode(), e.getMessage());
    }

    /**
     * 处理未知系统异常
     * @param e Exception 异常对象
     * @return 统一错误响应包装
     */
    @ExceptionHandler(Exception.class)
    public Result<Void> handleException(Exception e) {
        log.error("【系统全局异常拦截】 未预期异常: ", e);
        return Result.fail(ResultCode.SYSTEM_ERROR);
    }

    /**
     * SSE 流式接口专用的异常包装类型。
     * 当 SSE controller 内的异步线程抛出异常时，
     * 将其包装为此类型，由 GlobalExceptionHandler 的专用方法处理。
     */
    public static class SseStreamingException extends RuntimeException {
        public SseStreamingException(String message) {
            super(message);
        }
        public SseStreamingException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
