package com.wanqing.ai.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.wanqing.ai.entity.UserFeedback;
import org.apache.ibatis.annotations.Mapper;

/**
 * 用户反馈 Mapper 接口
 */
@Mapper
public interface UserFeedbackMapper extends BaseMapper<UserFeedback> {
}
