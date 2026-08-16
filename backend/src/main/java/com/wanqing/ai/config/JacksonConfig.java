package com.wanqing.ai.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

/**
 * Jackson 全局序列化配置。
 *
 * 核心目标：Java → JSON 时统一使用 snake_case 字段命名，与前端 / Python Agent 协议对齐。
 *
 * 解决方案：
 * - @JsonProperty("is_end") 控制 JSON→Java（Python→Java）解析
 * - PropertyNamingStrategies.SNAKE_CASE 控制 Java→JSON（SSE 输出到前端）
 * - 两者配合，确保双向字段名一致
 *
 * Jackson 优先级规则（Jackson 2.x）：
 * - 显式 @JsonProperty 标注的字段 → 使用 @JsonProperty 指定的名字
 * - 未标注 @JsonProperty 的字段 → 应用全局 PropertyNamingStrategy
 *
 * 因此 AgentInvokeResp 中所有字段都标注了 @JsonProperty("xxx")，
 * 最终输出的 JSON 键名完全由 @JsonProperty 决定，JacksonConfig 全局策略兜底。
 */
@Configuration
public class JacksonConfig {

    @Bean
    @Primary
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = JsonMapper.builder()
                .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .build()
                .registerModule(new JavaTimeModule());
        return mapper;
    }
}
