package com.wanqing.ai.service;

import java.util.Map;

/**
 * 用户干预反馈服务接口
 *
 * 核心职责：
 *   1. 写入 MySQL（user_feedback 表），持久化存储每次干预弹窗的用户选择
 *   2. 同步写入 Redis（feedback:stats:{session_id}），供 Python Agent 实时读取反馈统计
 *   3. 查询会话的反馈统计数据（accepted/rejected/ignored 计数及拒绝率）
 *
 * 依赖关系：
 *   - 被 FeedbackController 调用
 *   - 被 ChatController 依赖（读取反馈统计计算 user_rejection_penalty）
 *   - 实现类：FeedbackServiceImpl
 */
public interface FeedbackService {

    /**
     * 记录用户对干预弹窗的反馈
     *
     * @param sessionId      会话ID
     * @param choice         用户选择：accepted / rejected / ignored
     * @param emotionVector  反馈时的 OCC 八维情感向量
     * @param currentEmotion 反馈时的情绪标签
     */
    void recordFeedback(String sessionId, String choice,
                        Map<String, Double> emotionVector,
                        String currentEmotion);

    /**
     * 查询会话的反馈统计数据
     *
     * @param sessionId 会话ID
     * @return 统计数据 Map，包含：
     *         accepted（long）、rejected（long）、ignored（long）、
     *         rejection_rate（double）、last_choice（String）、last_updated（long）
     */
    Map<String, Object> getFeedbackStats(String sessionId);
}
