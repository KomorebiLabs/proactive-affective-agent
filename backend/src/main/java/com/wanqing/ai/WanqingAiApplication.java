package com.wanqing.ai;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 婉情AI Spring Boot 后端应用启动类
 *
 * 核心职责：
 *   1. 启动 Spring Boot 容器，扫描并注册所有 @Configuration / @Service / @RestController 等 Bean
 *   2. 扫描 com.wanqing.ai.mapper 包下的所有 Mapper 接口，交由 MyBatis-Plus 管理
 *
 * 依赖关系：
 *   - 依赖 Spring Boot 自动配置（DataSource、Redis、WebFlux 等）
 *   - 依赖 MyBatis-Plus MapperScan，将 Mapper 绑定到数据库表
 *   - 服务端口由 application.yml 的 server.port 配置项决定（默认 8080）
 */
@SpringBootApplication
@MapperScan("com.wanqing.ai.mapper")
public class WanqingAiApplication {

    public static void main(String[] args) {
        System.out.println("⚡ [System] Spring Boot 即将启动，开始联机婉晴的大脑...");
        SpringApplication.run(WanqingAiApplication.class, args);
        System.out.println("✅ [System] Java Spring Boot 核心服务启动完毕，监听端口 8080");
    }

}
