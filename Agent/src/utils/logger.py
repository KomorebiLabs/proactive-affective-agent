"""
婉情AI - 全局日志工具
====================
基于 Loguru，提供统一的日志格式和文件轮转。
使用方式：from src.utils.logger import logger
"""

import sys
from pathlib import Path

from loguru import logger

from config import log_config


def setup_logger() -> None:
    """初始化全局日志配置（应在程序入口调用一次）"""
    # 移除 Loguru 默认 handler
    logger.remove()

    # 控制台输出（彩色）
    logger.add(
        sys.stderr,
        format=log_config.LOG_FORMAT,
        level=log_config.LOG_LEVEL,
        colorize=True,
    )

    # 文件输出（自动轮转）
    logger.add(
        log_config.LOG_FILE,
        format=log_config.LOG_FORMAT,
        level=log_config.LOG_LEVEL,
        rotation=log_config.LOG_ROTATION,
        retention=log_config.LOG_RETENTION,
        encoding="utf-8",
    )

    logger.info("婉情AI 日志系统初始化完成")


# 启动时自动初始化
setup_logger()

# 导出 logger 供其他模块使用
__all__ = ["logger"]
