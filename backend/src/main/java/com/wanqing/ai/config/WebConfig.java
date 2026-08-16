package com.wanqing.ai.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 跨域配置
 * 允许前端 (localhost:5173) 跨域访问后端 API
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                // 允许的来源：前端 Vite 开发服务器 (5173) + Python 感知微服务 (8000)
                // 使用 allowedOriginPatterns（而非 allowedOrigins）以便灵活匹配端口
                // 注意：allowedOriginPatterns 配合 allowCredentials(true) 是合法的，
                // 浏览器会自动将响应头 Origin 替换为实际来源（而非 *）
                .allowedOriginPatterns(
                        "http://localhost:*",
                        "http://127.0.0.1:*"
                )
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .allowCredentials(true)
                .maxAge(3600);
    }
}
