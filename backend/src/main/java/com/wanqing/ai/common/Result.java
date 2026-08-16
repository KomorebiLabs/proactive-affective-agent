package com.wanqing.ai.common;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 全局统一响应返回泛型包装类
 *
 * 核心职责：
 *   1. 统一所有 Controller 接口的响应格式，避免各接口返回格式不一致
 *   2. 提供 success / fail 工厂方法，简化 Controller 代码
 *
 * 依赖关系：
 *   - 被所有 @RestController 返回值使用
 *   - 依赖 ResultCode 提供标准状态码
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class Result<T> {

    private int code;
    private String message;
    private T data;

    /**
     * 成功响应（无数据返回）
     * @return Result
     */
    public static <T> Result<T> success() {
        return new Result<>(ResultCode.SUCCESS.getCode(), ResultCode.SUCCESS.getMessage(), null);
    }

    /**
     * 成功响应（带数据返回）
     * @param data 返回的数据
     * @return Result
     */
    public static <T> Result<T> success(T data) {
        return new Result<>(ResultCode.SUCCESS.getCode(), ResultCode.SUCCESS.getMessage(), data);
    }

    /**
     * 失败响应（默认系统错误）
     * @return Result
     */
    public static <T> Result<T> fail() {
        return new Result<>(ResultCode.SYSTEM_ERROR.getCode(), ResultCode.SYSTEM_ERROR.getMessage(), null);
    }

    /**
     * 失败响应（指定状态码）
     * @param resultCode 状态码枚举
     * @return Result
     */
    public static <T> Result<T> fail(ResultCode resultCode) {
        return new Result<>(resultCode.getCode(), resultCode.getMessage(), null);
    }

    /**
     * 失败响应（自定义状态码与消息）
     * @param code 状态代码
     * @param message 错误信息
     * @return Result
     */
    public static <T> Result<T> fail(int code, String message) {
        return new Result<>(code, message, null);
    }
}
