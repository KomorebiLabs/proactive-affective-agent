# perception/socket_manager.py
import asyncio
import json
import traceback
import time
from fastapi import WebSocket
from typing import List, Dict
from dataclasses import dataclass
from enum import IntEnum

class MessagePriority(IntEnum):
    HIGH = 1   # 语音消息
    NORMAL = 2  # 普通消息
    LOW = 3     # 视频帧

@dataclass
class QueuedMessage:
    priority: MessagePriority
    connection: WebSocket
    message: str
    enqueue_time: float

class ConnectionManager:
    def __init__(self, max_queue_size: int = 1000):
        # 【修复1】分离式队列：高优先级（语音）和低优先级（视频）
        self.high_priority_queue: asyncio.Queue[QueuedMessage] = asyncio.Queue(maxsize=max_queue_size)
        self.low_priority_queue: asyncio.Queue[QueuedMessage] = asyncio.Queue(maxsize=max_queue_size * 2)

        # 活跃连接列表（修复：之前缺失！）
        self.active_connections: List[WebSocket] = []
        
        # 【TTS重构】区分 Agent 连接和前端连接
        self.agent_connections: List[WebSocket] = []  # Agent 连接列表
        self.frontend_connections: List[WebSocket] = []  # 前端连接列表

        # 每个连接独立的发送Task，实现并行发送
        self.connection_tasks: Dict[WebSocket, asyncio.Task] = {}

        # 【TTS重构】TTS 专用通道
        self.tts_connection: WebSocket = None  # TTS 专用连接
        self.tts_send_lock = asyncio.Lock()     # TTS 发送锁

        # 心跳配置
        self.heartbeat_interval = 30  # 30秒发送一次心跳
        self.heartbeat_timeout = 10   # 10秒内必须收到pong
        self.last_pong_time: Dict[WebSocket, float] = {}

        # 队列监控
        self.high_queue_size = max_queue_size
        self.low_queue_size = max_queue_size * 2

        # Worker状态
        self.high_priority_worker: asyncio.Task = None
        self.low_priority_worker: asyncio.Task = None
        self.heartbeat_task: asyncio.Task = None

        print(f" [Socket] 初始化完成，高优先级队列容量: {max_queue_size}，低优先级队列容量: {max_queue_size * 2}")

    def start_sender_workers(self):
        """【修复1】启动多个独立Worker"""
        print(" [Socket] 启动并行广播Worker...")
        self.high_priority_worker = asyncio.create_task(self._high_priority_worker())
        self.low_priority_worker = asyncio.create_task(self._low_priority_worker())
        self.heartbeat_task = asyncio.create_task(self._heartbeat_worker())
        print(" [Socket] Worker启动完成（高优先级/低优先级/心跳）")

    async def _high_priority_worker(self):
        """高优先级Worker：处理语音等重要消息，快速发送"""
        while True:
            try:
                item = await asyncio.wait_for(
                    self.high_priority_queue.get(),
                    timeout=1.0
                )
                await self._send_with_timeout(item.connection, item.message)
                self.high_priority_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                # 【修复4】异常后短暂暂停（100ms），快速恢复
                traceback.print_exc()
                await asyncio.sleep(0.1)

    async def _low_priority_worker(self):
        """低优先级Worker：处理视频帧等大量数据"""
        while True:
            try:
                item = await asyncio.wait_for(
                    self.low_priority_queue.get(),
                    timeout=1.0
                )
                await self._send_with_timeout(item.connection, item.message)
                self.low_priority_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                traceback.print_exc()
                await asyncio.sleep(0.1)

    async def _send_with_timeout(self, connection: WebSocket, message: str, timeout: float = 5.0):
        """带超时的发送，防止慢连接阻塞"""
        try:
            await asyncio.wait_for(connection.send_text(message), timeout=timeout)
        except asyncio.TimeoutError:
            print(f" [Socket] 发送超时，断开连接")
            self.disconnect(connection)
        except Exception:
            self.disconnect(connection)

    async def _heartbeat_worker(self):
        """【TTS重构修复】心跳只发给前端连接，不发给 Agent"""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                now = time.time()
                dead_connections = []

                for connection in list(self.active_connections):
                    last_pong = self.last_pong_time.get(id(connection), now)
                    if now - last_pong > self.heartbeat_interval + self.heartbeat_timeout:
                        print(f" [Socket] 连接心跳超时: {id(connection)}")
                        dead_connections.append(connection)

                # 断开死连接
                for conn in dead_connections:
                    self.disconnect(conn)

                # 【TTS重构】心跳只发送给前端连接，Agent 不需要
                for connection in list(self.frontend_connections):
                    if connection not in dead_connections:
                        try:
                            await connection.send_text(json.dumps({"type": "ping", "timestamp": int(now * 1000)}))
                        except Exception:
                            self.disconnect(connection)

            except asyncio.CancelledError:
                break
            except Exception:
                traceback.print_exc()
                await asyncio.sleep(1)

    async def connect(self, websocket: WebSocket, connection_type: str = "frontend"):
        """
        WebSocket连接处理
        
        Args:
            websocket: WebSocket 连接
            connection_type: 连接类型，"frontend" 或 "agent"
        """
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            self.last_pong_time[id(websocket)] = time.time()
            
            # 【TTS重构】区分连接类型
            if connection_type == "agent":
                self.agent_connections.append(websocket)
                print(f"[Socket] Agent 连接已添加。当前 Agent: {len(self.agent_connections)}, 前端: {len(self.frontend_connections)}")
            else:
                self.frontend_connections.append(websocket)
                print(f"[Socket] 前端连接已添加。当前 Agent: {len(self.agent_connections)}, 前端: {len(self.frontend_connections)}")
            
            print(f"[Socket] 连接成功。当前在线: {len(self.active_connections)}")
            return True
        except Exception as e:
            print(f"[Socket] 握手阶段失败: {e}")
            return False

    def mark_agent_connection(self, websocket: WebSocket):
        """标记为 Agent 连接，同时从前端连接列表移除"""
        if websocket not in self.agent_connections:
            self.agent_connections.append(websocket)
        
        # 【TTS重构】从前端连接列表移除（Agent 不应该收到发给前端的消息）
        if websocket in self.frontend_connections:
            self.frontend_connections.remove(websocket)
        
        print(f"[Socket] Agent 连接已标记。当前 Agent: {len(self.agent_connections)}, 前端: {len(self.frontend_connections)}")

    def disconnect(self, websocket: WebSocket):
        """安全断开连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            # 清理心跳记录
            if id(websocket) in self.last_pong_time:
                del self.last_pong_time[id(websocket)]
            print(f"[Socket] 连接已断开。剩余在线: {len(self.active_connections)}")
        
        # 【TTS重构】清理 Agent 连接
        if websocket in self.agent_connections:
            self.agent_connections.remove(websocket)
            print(f"[Socket] Agent 连接已移除。剩余 Agent: {len(self.agent_connections)}")
        
        # 【TTS重构】清理前端连接
        if websocket in self.frontend_connections:
            self.frontend_connections.remove(websocket)
            print(f"[Socket] 前端连接已移除。剩余前端: {len(self.frontend_connections)}")
        
        # 【TTS重构】清理 TTS 专用连接
        if self.tts_connection is websocket:
            self.tts_connection = None
            print("[Socket] TTS 专用通道已关闭")

    def receive_pong(self, websocket: WebSocket):
        """前端响应pong，更新心跳时间"""
        self.last_pong_time[id(websocket)] = time.time()

    def broadcast(self, message: dict, priority: MessagePriority = MessagePriority.NORMAL):
        """
        广播消息到所有前端连接。

        【注意】已废弃 queue 机制，直接广播给所有前端连接。
        TTS 消息应使用 send_to_tts()。

        【高频调用】不打印日志，避免 ~10fps 视频帧广播导致刷屏。
        """
        # 【TTS重构】直接广播给所有前端连接，不再使用队列
        for connection in list(self.frontend_connections):
            self.send_to_connection(connection, message, priority)

    def send_to_connection(self, connection: WebSocket, message: dict, priority: MessagePriority = MessagePriority.NORMAL):
        """【修复1】向指定连接发送消息，使用独立Task实现并行"""
        json_str = json.dumps(message, ensure_ascii=False)

        # 如果该连接已有发送任务，取消它（防止积压）
        if connection in self.connection_tasks and not self.connection_tasks[connection].done():
            self.connection_tasks[connection].cancel()

        # 创建新的发送任务
        task = asyncio.create_task(self._send_with_timeout(connection, json_str))
        self.connection_tasks[connection] = task

    def broadcast_to_all(self, message: dict, priority: MessagePriority = MessagePriority.NORMAL):
        """向所有连接并行发送消息"""
        json_str = json.dumps(message, ensure_ascii=False)
        for connection in list(self.active_connections):
            self.send_to_connection(connection, message, priority)

    def broadcast_except(self, sender: WebSocket, message: dict, priority: MessagePriority = MessagePriority.NORMAL):
        """广播给除sender外的所有连接"""
        json_str = json.dumps(message, ensure_ascii=False)
        for connection in list(self.active_connections):
            if connection is not sender:
                self.send_to_connection(connection, message, priority)

    def broadcast_to_frontend(self, message: dict):
        """
        【TTS重构】只广播给前端连接，不发给 Agent。
        用于 Agent 的非 TTS 语音消息。
        """
        json_str = json.dumps(message, ensure_ascii=False)
        for connection in list(self.frontend_connections):
            self.send_to_connection(connection, message, MessagePriority.HIGH)

    # ============================================================
    # 【TTS重构】TTS 专用通道方法
    # ============================================================

    def mark_tts_connection(self, websocket: WebSocket):
        """
        标记 TTS 专用连接。
        当 Agent 发送 tts_stream_start 消息时调用。
        """
        self.tts_connection = websocket
        self.mark_agent_connection(websocket)  # TTS 连接也是 Agent 连接
        print(f"[Socket] TTS 专用通道已建立: {id(websocket)}, 前端连接数: {len(self.frontend_connections)}")

    def is_tts_connection(self, websocket: WebSocket) -> bool:
        """检查是否是 TTS 专用连接"""
        return websocket is self.tts_connection

    def send_to_tts(self, sender: WebSocket, message: dict):
        """
        TTS 消息直接发送给所有前端连接。
        
        【关键设计】
        - sender: Agent 的 TTS 连接（发送者）
        - 接收者: 所有前端连接（frontend_connections）
        
        这样 TTS 消息走独立通道，不与视频帧共享带宽。
        """
        asyncio.create_task(self._tts_broadcast_to_frontend(sender, message))

    async def _tts_broadcast_to_frontend(self, sender: WebSocket, message: dict):
        """
        TTS 消息广播给所有前端连接。
        
        【关键设计】
        - 不经过任何队列
        - 直接发送到所有前端连接
        - 使用锁保证消息顺序
        """
        async with self.tts_send_lock:
            json_str = json.dumps(message, ensure_ascii=False)
            
            # 发送给所有前端连接
            failed_connections = []
            for connection in list(self.frontend_connections):
                try:
                    await asyncio.wait_for(
                        connection.send_text(json_str),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    print(f" [Socket] TTS 发送超时，断开连接")
                    failed_connections.append(connection)
                except Exception as e:
                    print(f" [Socket] TTS 发送失败: {e}")
                    failed_connections.append(connection)
            
            # 清理失败的连接
            for conn in failed_connections:
                self.disconnect(conn)

    def get_queue_status(self) -> dict:
        """获取队列状态（用于监控）"""
        return {
            "high_priority_size": self.high_priority_queue.qsize(),
            "high_priority_capacity": self.high_queue_size,
            "low_priority_size": self.low_priority_queue.qsize(),
            "low_priority_capacity": self.low_queue_size,
            "active_connections": len(self.active_connections),
            "agent_connections": len(self.agent_connections),
            "frontend_connections": len(self.frontend_connections)
        }

    async def shutdown(self):
        """优雅关闭"""
        print(" [Socket] 开始关闭...")
        if self.high_priority_worker:
            self.high_priority_worker.cancel()
        if self.low_priority_worker:
            self.low_priority_worker.cancel()
        if self.heartbeat_task:
            self.heartbeat_task.cancel()

        # 取消所有连接任务
        for task in self.connection_tasks.values():
            task.cancel()

        print(" [Socket] 关闭完成")

# 全局单例
manager = ConnectionManager(max_queue_size=1000)
