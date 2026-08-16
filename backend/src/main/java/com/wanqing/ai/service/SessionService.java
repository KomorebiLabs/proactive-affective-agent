package com.wanqing.ai.service;

import com.wanqing.ai.dto.request.SessionStartReq;
import com.wanqing.ai.dto.response.SessionStartResp;
import com.wanqing.ai.entity.UserSession;

/**
 * 用户会话服务接口
 *
 * 核心职责：
 *   1. 创建会话：生成 session_id，写入 MySQL，通知 Python 感知微服务切换会话
 *   2. 查询会话：根据 session_id 返回会话实体
 *
 * 依赖关系：
 *   - 被 SessionController 调用
 *   - 实现类：SessionServiceImpl
 */
public interface SessionService {

    /**
     * 初始化用户会话
     * @param request 会话开始请求参数
     * @return 包含 sessionId 的响应
     */
    SessionStartResp startSession(SessionStartReq request);

    /**
     * 根据 sessionId 查询会话
     * @param sessionId 会话ID
     * @return 会话实体，若不存在返回 null
     */
    UserSession getSessionById(String sessionId);
}
