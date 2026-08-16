package com.wanqing.ai.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.wanqing.ai.entity.UserSession;
import org.apache.ibatis.annotations.Mapper;

/**
 * 用户会话 Mapper 接口
 */
@Mapper
public interface UserSessionMapper extends BaseMapper<UserSession> {
}
