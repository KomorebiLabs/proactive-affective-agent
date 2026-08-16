package com.wanqing.ai.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.time.LocalDateTime;

/**
 * 用户会话实体类
 */
@Data
@Accessors(chain = true)
@TableName("experiment_session")
public class UserSession {

    /**
     * 主键，存储生成的 UUID (session_id)
     */
    @TableId(type = IdType.INPUT)
    private String id;

    /**
     * 用户姓名（映射：subject_name）
     */
    @TableField("subject_name")
    private String subjectName;

    /**
     * 用户分组/等级（映射：experiment_group）
     */
    @TableField("experiment_group")
    private String experimentGroup;

    /**
     * 会话状态
     */
    private String status;

    /**
     * 创建时间（映射：create_time）
     */
    @TableField("create_time")
    private LocalDateTime createTime;

    /**
     * 更新时间（映射：update_time）
     */
    @TableField("update_time")
    private LocalDateTime updateTime;
}
