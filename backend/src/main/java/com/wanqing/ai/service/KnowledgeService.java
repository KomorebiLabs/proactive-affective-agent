package com.wanqing.ai.service;

import org.springframework.web.multipart.MultipartFile;
import java.util.Map;

/**
 * 知识库管理服务接口
 */
public interface KnowledgeService {

    /**
     * 上传知识库文件以进行向量化处理
     * @param file 用户上传的文件
     * @param category 知识库分类标签
     * @return 包含文件名和插入块数的响应信息
     */
    Map<String, Object> uploadKnowledgeBase(MultipartFile file, String category);
}
