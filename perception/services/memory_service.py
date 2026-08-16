# perception/services/memory_service.py
import os
import json
import numpy as np
from datetime import datetime

class MemoryService:
    """
    【记忆服务中心】
    职责：负责所有感官数据的持久化存储（写日志）与历史回溯（读记忆）。
    存储路径：perception/storage/logs/
    """
    def __init__(self):
        # 确定存储根目录
        self.base_path = os.path.join(os.path.dirname(__file__), "..", "storage", "logs")
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

    def _get_today_file_path(self):
        """获取今天的日志文件路径"""
        today_str = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.base_path, f"observation_log_{today_str}.jsonl")

    # === [功能 1] 接收并存储新数据 (由 MonitorService 调用) ===
    def save_log(self, data: dict):
        """
        将单条观察记录追加到本地 JSONL 文件
        """
        file_path = self._get_today_file_path()
        try:
            # 确保时间戳是字符串格式
            if 'timestamp' in data and not isinstance(data['timestamp'], str):
                data['timestamp'] = data['timestamp'].isoformat()

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f" [Memory] 写入日志失败: {e}")

    # === [功能 2] 提取最近行为记录 (由 ChatService 调用) ===
    # 注意：这里的 limit 参数就是你想要调整的地方！
    def get_recent_logs(self, limit=10): 
        """
        读取最近的 N 条记录，用于构建对话上下文。
        参数 limit: 默认为 10，你可以在调用处修改它。
        """
        file_path = self._get_today_file_path()
        if not os.path.exists(file_path):
            return "（今日暂无观察记录）"

        recent_data = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 提取最后 limit 条
                # 如果总数少于 limit，则取出全部
                target_lines = lines[-limit:]
                
                for line in target_lines:
                    item = json.loads(line.strip())
                    time_str = item.get('timestamp', '')[11:19] # 截取 HH:MM:SS
                    behavior = item.get('behavior_desc', item.get('behavior', '未知'))
                    emotion = item.get('emotion', '未知')
                    recent_data.append(f"[{time_str}] 行为: {behavior}, 状态: {emotion}")

            return "\n".join(recent_data)
        except Exception as e:
            print(f" [Memory] 读取日志失败: {e}")
            return "（记忆提取失败）"

    # === [功能 3] 计算全天统计数据 (用于每日总结) ===
    def get_daily_stats(self):
        """
        聚合全天数据，计算平均唤醒度 (Arousal) 和高频行为
        """
        file_path = self._get_today_file_path()
        if not os.path.exists(file_path):
            return None

        arousal_values = []
        behavior_counts = {}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    item = json.loads(line.strip())
                    # 1. 提取 Arousal (唤醒度)
                    # 归一化 L2 范数：norm / sqrt(8)，确保结果在 [0, 1] 范围
                    vector = item.get('vector', {})
                    if vector:
                        vals = list(vector.values())
                        if vals:
                            current_arousal = float(np.linalg.norm(vals)) / (len(vals) ** 0.5)
                            arousal_values.append(current_arousal)
                    
                    # 2. 统计行为
                    bh = item.get('behavior_desc', '未知')
                    behavior_counts[bh] = behavior_counts.get(bh, 0) + 1

            if not arousal_values:
                return None

            avg_arousal = sum(arousal_values) / len(arousal_values)
            # 找到最频繁的行为
            top_behavior = max(behavior_counts, key=behavior_counts.get)

            return {
                "avg_arousal": round(avg_arousal, 2),
                "top_behavior": top_behavior,
                "total_records": len(arousal_values),
                "summary_text": f"今日平均压力值: {round(avg_arousal, 2)}/10，主要行为是: {top_behavior}，共记录 {len(arousal_values)} 次观察。"
            }
        except Exception as e:
            print(f" [Memory] 计算统计数据失败: {e}")
            return None
    

    
    def get_full_daily_report(self):
        """聚合全天数据，生成深度心理报告所需素材"""
        file_path = self._get_today_file_path()
        if not os.path.exists(file_path): return None

        records = []
        arousal_list = []
        behavior_map = {} # 统计行为频率
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    records.append(data)
                    # 计算唤醒度（归一化 L2 范数，确保 [0, 1] 范围）
                    vec = data.get('vector', {})
                    if vec:
                        vals = list(vec.values())
                        if vals:
                            a = float(np.linalg.norm(vals)) / (len(vals) ** 0.5)
                            arousal_list.append(a)
                    # 统计行为
                    b = data.get('behavior_desc', '未知')
                    behavior_map[b] = behavior_map.get(b, 0) + 1

            if not records: return None

            avg_a = sum(arousal_list)/len(arousal_list) if arousal_list else 0
            # 找出最频繁的3个行为
            top_behaviors = sorted(behavior_map.items(), key=lambda x: x[1], reverse=True)[:3]
            
            return {
                "total_count": len(records),
                "avg_arousal": round(avg_a, 2),
                "top_behaviors": top_behaviors,
                "is_stressful": avg_a > 6.0 # 压力预警
            }
        except Exception as e:
            print(f" [Memory] 生成报告素材失败: {e}")
            return None

# 单例导出
memory_service = MemoryService()