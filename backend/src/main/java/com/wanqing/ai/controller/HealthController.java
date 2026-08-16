package com.wanqing.ai.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.Map;

/**
 * 健康检查控制器
 *
 * 核心职责：
 *   1. 提供 /health 端点，供启动脚本和监控服务检查后端状态
 *   2. 提供 /api/v1/info 端点，返回后端版本和状态信息
 */
@RestController
@RequestMapping("/")
public class HealthController {

    @GetMapping("health")
    public Map<String, Object> health() {
        return Map.of(
            "status", "online",
            "service", "wanqing-ai-backend",
            "timestamp", Instant.now().toString()
        );
    }

    @GetMapping("api/v1/info")
    public Map<String, Object> info() {
        return Map.of(
            "service", "wanqing-ai-backend",
            "version", "1.0.0",
            "status", "running",
            "timestamp", Instant.now().toString()
        );
    }
}
