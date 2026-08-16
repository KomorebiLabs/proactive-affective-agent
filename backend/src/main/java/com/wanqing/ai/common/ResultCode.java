package com.wanqing.ai.common;

import lombok.AllArgsConstructor;
import lombok.Getter;

/**
 * 全局统一响应状态码枚举
 *
 * 核心职责：
 *   定义系统中所有 HTTP 响应状态的标准化状态码，供 Result.fail() 使用
 *
 * 依赖关系：
 *   - 被 Result 类的 fail() 工厂方法引用
 */
@Getter
@AllArgsConstructor
public enum ResultCode {
    
    SUCCESS(200, "success"),
    BAD_REQUEST(400, "bad request parameter"),
    UNAUTHORIZED(401, "unauthorized access"),
    FORBIDDEN(403, "access forbidden"),
    NOT_FOUND(404, "resource not found"),
    SYSTEM_ERROR(500, "system internal error");

    private final int code;
    private final String message;
}
