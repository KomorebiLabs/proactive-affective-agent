// 统一 API 入口：后端地址全部从这里取，组件里禁止再写裸 URL。
//
// 默认值对应本机开发拓扑（Java 8080 / 感知服务 8000）。
// 覆盖方式：frontend/.env.local 里写
//   VITE_API_BASE=http://192.168.x.x:8080
//   VITE_PERCEPTION_WS_URL=ws://192.168.x.x:8000/ws
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080'
export const PERCEPTION_WS_URL = import.meta.env.VITE_PERCEPTION_WS_URL || 'ws://localhost:8000/ws'

export const api = {
  sessionStart: `${API_BASE}/api/v1/session/start`,
  chatStream: `${API_BASE}/api/v1/chat/stream`,
  feedback: `${API_BASE}/api/v1/feedback`
}
