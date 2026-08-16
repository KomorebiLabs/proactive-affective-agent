package com.wanqing.ai.service.impl;

import com.wanqing.ai.service.KnowledgeService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.multipart.MultipartFile;

//import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * 知识库管理服务实现类
 *
 * 核心职责：
 *   1. 接收 Java 控制器转发的文件上传请求
 *   2. 通过 HTTP multipart/form-data 转发到 Python Agent 的 /internal/v1/rag/upload 接口
 *   3. Python Agent 负责文件落盘和 ChromaDB 向量化重建
 *   4. 返回 Python Agent 的向量化结果（chunks_inserted）
 *
 * 依赖关系：
 *   - 被 KnowledgeController 调用
 *   - 依赖 Spring WebClient 向 Python Agent 发送请求
 *   - 依赖 agent.engine.url 配置项
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeServiceImpl implements KnowledgeService {

    private final WebClient.Builder webClientBuilder;

    @Value("${agent.engine.url:http://localhost:8001}")
    private String agentEngineUrl;

    @Override
    public Map<String, Object> uploadKnowledgeBase(MultipartFile file, String category) {
        String originalFilename = file.getOriginalFilename();
        long fileSize = file.getSize();

        log.info("【KnowledgeService】开始上传知识库文件: filename={}, size={} bytes, category={}",
                originalFilename, fileSize, category);

        try {
            // 构造 multipart/form-data 请求体
            MultiValueMap<String, Object> body = new org.springframework.util.LinkedMultiValueMap<>();
            body.add("file", new MultipartByteArrayResource(
                    file.getBytes(), originalFilename) {
                @Override
                public String getFilename() {
                    return originalFilename;
                }
            });
            body.add("category", category != null ? category : "");

            // 调用 Python Agent 的 RAG 上传接口
            @SuppressWarnings("unchecked")
            Map<String, Object> result = webClientBuilder.baseUrl(agentEngineUrl).build()
                    .post()
                    .uri("/internal/v1/rag/upload")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();

            if (result == null) {
                result = Map.of(
                        "file_name", originalFilename,
                        "chunks_inserted", 0,
                        "status", "response_null"
                );
            }

            log.info("【KnowledgeService】Python Agent RAG 向量化完成: file={}, chunks_inserted={}",
                    originalFilename, result.get("chunks_inserted"));

            return result;

        } catch (Exception e) {
            log.error("【KnowledgeService】RAG 上传转发失败: {}", e.getMessage(), e);

            // 降级：记录失败但不抛异常（保证主流程继续）
            return Map.of(
                    "file_name", originalFilename,
                    "chunks_inserted", 0,
                    "status", "error",
                    "error_message", e.getMessage()
            );
        }
    }

    /**
     * Multipart 文件包装类，将 MultipartFile 包装为 Spring WebClient 可识别的 Resource
     */
    private static class MultipartByteArrayResource extends ByteArrayResource {
        private final String filename;

        public MultipartByteArrayResource(byte[] byteArray, String filename) {
            super(byteArray);
            this.filename = filename;
        }

        @Override
        public String getFilename() {
            return this.filename;
        }
    }
}
