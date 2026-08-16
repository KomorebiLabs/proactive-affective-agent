package com.wanqing.ai.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.wanqing.ai.entity.SessionLog;
import org.apache.ibatis.annotations.Mapper;

/**
 * 会话对话日志 Mapper
 * 继承 MyBatis-Plus BaseMapper，自动获得 CRUD 能力。
 */
@Mapper
public interface SessionLogMapper extends BaseMapper<SessionLog> {
}
