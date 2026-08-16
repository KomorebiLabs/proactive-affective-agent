package com.wanqing.ai.service.impl;

import com.wanqing.ai.dto.request.SessionStartReq;
import com.wanqing.ai.dto.response.SessionStartResp;
import com.wanqing.ai.entity.UserSession;
import com.wanqing.ai.mapper.UserSessionMapper;
import com.wanqing.ai.service.SessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.UUID;

/**
 * 用户会话服务实现类
 *
 * 核心职责：
 *   1. 创建会话：生成唯一 session_id（sess_ 前缀），写入 MySQL user_session 表
 *   2. 通知 Python 感知微服务切换 session_id（通过 WebClient POST /internal/v1/session/update）
 *   3. 查询会话：根据 session_id 返回会话实体，供 ChatController 验证会话合法性
 *
 * 依赖关系：
 *   - 被 SessionController 调用（/api/v1/session/start）
 *   - 依赖 UserSessionMapper（MyBatis-Plus → MySQL）
 *   - 依赖 WebClient 向 Python 感知微服务发送 session 切换通知
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SessionServiceImpl implements SessionService {

    private final UserSessionMapper userSessionMapper;
    private final WebClient.Builder webClientBuilder;

    @Value("${perception.service.url:http://localhost:8000}")
    private String perceptionServiceUrl;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionStartResp startSession(SessionStartReq request) {
        log.info("接收到新用户会话初始化请求: subject_name={}, group={}",
                 request.getSubjectName(), request.getExperimentGroup());

        // 1. 生成唯一 Session ID，这里按约定加个前缀更清晰
        String sessionId = "sess_" + UUID.randomUUID().toString().replace("-", "");

        // 2. 构建实体类
        UserSession session = new UserSession()
                .setId(sessionId)
                .setSubjectName(request.getSubjectName())
                .setExperimentGroup(request.getExperimentGroup())
                .setStatus("ready")
                .setCreateTime(LocalDateTime.now())
                .setUpdateTime(LocalDateTime.now());

        // 3. 调用 MyBatis-Plus 保存到 MySQL 数据库
        userSessionMapper.insert(session);
        log.info("用户会话已成功持久化至数据库, session_id={}", sessionId);

        // 4. 通知 Python 感知微服务切换 session_id（数据隔离的关键步骤）
        notifyPerceptionServiceSessionUpdate(sessionId, request.getSubjectName());

        // 5. 组装返回 DTO
        return SessionStartResp.builder()
                .sessionId(sessionId)
                .status("ready")
                .build();
    }

    private void notifyPerceptionServiceSessionUpdate(String sessionId, String subjectName) {
        try {
            webClientBuilder.baseUrl(perceptionServiceUrl).build()
                    .post()
                    .uri("/internal/v1/session/update")
                    .bodyValue(java.util.Map.of(
                            "session_id", sessionId,
                            "user_id", subjectName != null ? subjectName : ""
                    ))
                    .retrieve()
                    .toBodilessEntity()
                    .block(Duration.ofSeconds(5));  // 5秒超时，防止阻塞
            log.info("Python 感知服务会话切换成功: session={}", sessionId);
        } catch (Exception e) {
            // 感知服务不可用不影响主流程，只打警告
            log.warn("通知 Python 感知服务会话切换失败（不影响主流程）: session={}, error={}", sessionId, e.getMessage());
        }
    }

    @Override
    public UserSession getSessionById(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return null;
        }
        return userSessionMapper.selectById(sessionId);
    }
}
