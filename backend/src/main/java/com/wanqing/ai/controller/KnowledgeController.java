package com.wanqing.ai.controller;

import com.wanqing.ai.common.Result;
import com.wanqing.ai.service.KnowledgeService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import java.util.Map;

/**
 * 知识库管理控制器
 *
 * 核心职责：
 *   接收前端上传的心理学 RAG 知识库文件（Markdown/TXT），转发给 KnowledgeService
 *   最终由 Python Agent 将文件追加写入 ChromaDB 向量库，触发 RAG 检索重建
 *
 * 依赖关系：
 *   - 被前端 HTTP POST /api/v1/knowledge/upload 调用
 *   - 依赖 KnowledgeService（WebClient）转发文件到 Python Agent
 */
@RestController
@RequestMapping("/api/v1/knowledge")
@RequiredArgsConstructor
@Tag(name = "知识库管理", description = "心理学 RAG 知识库上传与管理接口")
public class KnowledgeController {

    private final KnowledgeService knowledgeService;

    @PostMapping("/upload")
    @Operation(summary = "心理学 RAG 知识库上传", description = "上传提取好的 Markdown/PDF，后端转发 Python Agent 进行向量化")
    public Result<Map<String, Object>> uploadKnowledge(
            @Parameter(description = "需要向量化的文件", required = true) @RequestParam("file") MultipartFile file,
            @Parameter(description = "知识库分类标签", required = true) @RequestParam("category") String category) {
        
        Map<String, Object> responseData = knowledgeService.uploadKnowledgeBase(file, category);
        return Result.success(responseData);
    }
}
