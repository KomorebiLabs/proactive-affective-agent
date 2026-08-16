import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { EMOTION_MAP, OCC_LABELS } from '../constants/emotions'

export const useAppStore = defineStore('app', () => {
  // === 全局基础状态 ===
  const isConnected = ref(false)
  const viewMode = ref('radar') // 'radar' | 'camera'
  const sessionId = ref(null)
  const theme = ref('dark') // 'dark' | 'light'

  // === 情感状态 ===
  const currentEmotion = ref('平静')
  const currentBehavior = ref('初始化中...')
  // OCC 八维情感向量（对应 EmotionRadar 雷达图，顺序固定）
  // 标签顺序必须与 EmotionRadar labels 完全一致
  const currentVector = ref([0, 0, 0, 0, 0, 0, 0, 0]) // 喜悦, 悲伤, 愤怒, 恐惧, 厌恶, 惊讶, 踏实感, 期待
  // Q3: 情感历史数组，仅由 WebSocket 实时通道（10Hz）驱动追加，最多保留60条
  const emotionHistory = ref([])
  const MAX_EMOTION_HISTORY = 60
  // Q4: 上次感知数据时间戳，用于避免 SSE 最终帧覆盖更新的 WebSocket 数据
  const lastPerceptionTimestamp = ref(0)
  // Q2: 当前干预动作和策略（来自 Agent SSE 最终帧，暂存于 store 供后续 UI 使用）
  const currentAction = ref('subtle')
  const currentStrategy = ref(null)
  // 【Plan1-B】干预评分
  const interventionScore = ref(0.0)
  // 【Plan1-D】已处理的 trace_id 集合（幂等去重）
  const processedTraceIds = ref(new Set())

  // === 模拟调试状态 ===
  const debugEmotionType = ref('neutral')
  const debugIntensity = ref(0.2)

  // === 媒体与对话数据 ===
  const videoFrameData = ref(null)

  const setVideoFrameData = (data) => {
    videoFrameData.value = data
  }
  const chatHistory = ref([
    { role: 'ai', text: '正在从 Java 后端建立感知映射...' }
  ])

  // === 计算属性 ===
  const currentPortraitPath = computed(() => {
    const map = {
      '开心': '/portraits/开心.png', '喜悦': '/portraits/开心.png',
      '生气': '/portraits/生气.png', '愤怒': '/portraits/生气.png',
      '悲伤': '/portraits/无奈.png', '无奈': '/portraits/无奈.png',
      '焦虑': '/portraits/害怕.png', '害怕': '/portraits/害怕.png',
      '恐惧': '/portraits/害怕.png', '惊讶': '/portraits/惊讶.png',
      '好奇': '/portraits/好奇.png', '害羞': '/portraits/害羞.png',
    }
    return map[currentEmotion.value] || '/portraits/正常.png'
  })

  // === Actions ===
  const addChatMessage = (role, text) => {
    chatHistory.value.push({ role, text })
  }

  // 更新聊天历史中最后一条 AI 消息内容（用于 SSE 流式拼字）
  const updateLastAIMessage = (text) => {
    const msgs = chatHistory.value
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'ai') {
        msgs[i].text = text
        break
      }
    }
  }

  // === OCC 八维情感标签顺序（OCC_LABELS 从 constants/emotions.js 导入，与 EmotionRadar 对齐）===

  const updatePerception = (data) => {
    // Q4: 时间戳保护 — 避免 SSE 最终帧覆盖更新的 WebSocket 实时数据
    const incomingTs = data._perceptionTimestamp || data.timestamp || Date.now()
    if (incomingTs < lastPerceptionTimestamp.value) {
      return // 丢弃比当前数据更旧的消息
    }

    if (data.emotion) currentEmotion.value = data.emotion
    if (data.behavior) currentBehavior.value = data.behavior

    if (data.vector && typeof data.vector === 'object') {
      // 新格式：后端 Agent 直接返回 OCC dict {"喜悦": 0.8, "悲伤": 0.3, ...}
      // 按 OCC_LABELS 固定顺序提取，保证雷达图轴对齐
      currentVector.value = OCC_LABELS.map(l => {
        const v = data.vector[l]
        // 兼容旧格式：如果 value 已是 0~1 直接用，否则 /10
        return (typeof v === 'number' && v >= 0) ? v : 0
      })
    } else if (Array.isArray(data.vector)) {
      // 旧格式：直接传入数组，按下标对应 OCC_LABELS
      currentVector.value = data.vector
    }

    // Q3: 追加到情感历史（仅 WebSocket 实时通道追加，SSE 最终帧不追加，避免 Agent OCC 融合向量污染）
    if (data._fromWebSocket) {
      emotionHistory.value.push({
        timestamp: incomingTs,
        vector: data.vector || currentVector.value
      })
      if (emotionHistory.value.length > MAX_EMOTION_HISTORY) {
        emotionHistory.value.shift()
      }
    }

    lastPerceptionTimestamp.value = incomingTs
  }

  /**
   * 【Plan1-B 唯一最终快照写入口】
   * 所有 SSE 最终帧的决策状态必须通过此方法更新。
   * 包含幂等去重和时间戳单调保护。
   */
  const applyFinalDecisionSnapshot = (payload) => {
    // 【Plan1-D 幂等去重】
    const traceId = payload.trace_id || payload.traceId
    if (traceId) {
      if (processedTraceIds.value.has(traceId)) {
        console.log(`[Store] 重复最终帧丢弃: trace_id=${traceId}`)
        return
      }
      processedTraceIds.value.add(traceId)
    }

    // 【Plan1-D 时间戳单调保护】
    const incomingTs = payload.timestamp_ms || payload.timestampMs || Date.now()
    if (incomingTs < lastPerceptionTimestamp.value) {
      console.warn(`[Store] 旧时间戳丢弃: incoming=${incomingTs}, current=${lastPerceptionTimestamp.value}`)
      return
    }
    lastPerceptionTimestamp.value = incomingTs

    // 更新干预决策状态
    if (payload.action) currentAction.value = payload.action
    if (payload.strategy) currentStrategy.value = payload.strategy
    if (typeof payload.intervention_score === 'number') {
      interventionScore.value = payload.intervention_score
    }

    // 更新情感向量
    if (payload.vector) {
      currentVector.value = OCC_LABELS.map(l => {
        const v = payload.vector[l]
        return (typeof v === 'number' && v >= 0) ? v : 0
      })
    }

    // 更新主要情绪标签（EMOTION_MAP 单源在 constants/emotions.js）
    if (payload.vector) {
      const entries = Object.entries(payload.vector)
      if (entries.length > 0) {
        const maxEntry = entries.reduce((a, b) => (b[1] > a[1] ? b : a))
        currentEmotion.value = EMOTION_MAP[maxEntry[0]] || '平静'
      }
    }

    console.log(`[Store] 最终快照已应用: action=${currentAction.value}, urgency=${payload.urgency}, score=${interventionScore.value}, trace=${traceId}`)
  }

  const setConnection = (status) => {
    isConnected.value = status
  }

  // === 干预弹窗状态 ===
  const showInterventionPopup = ref(false)
  const interventionPopupData = ref({
    urgency: 'low',   // 'low' | 'medium' | 'high'
    message: '婉晴感受到你可能心情有些不好，需要聊聊吗？',
    autoDismissSeconds: 10
  })

  const showIntervention = (data) => {
    interventionPopupData.value = {
      urgency: data.urgency || 'low',
      message: data.message || interventionPopupData.value.message,
      autoDismissSeconds: data.urgency === 'high' ? 15 : 8
    }
    showInterventionPopup.value = true
  }

  const hideIntervention = () => {
    showInterventionPopup.value = false
  }

  const toggleTheme = () => {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  return {
    isConnected,
    viewMode,
    sessionId,
    theme,
    currentEmotion,
    currentBehavior,
    currentVector,
    emotionHistory,
    lastPerceptionTimestamp,
    currentAction,
    currentStrategy,
    interventionScore,
    debugEmotionType,
    debugIntensity,
    videoFrameData,
    chatHistory,
    currentPortraitPath,
    addChatMessage,
    updateLastAIMessage,
    updatePerception,
    applyFinalDecisionSnapshot, // 【Plan1-B 唯一入口】
    setConnection,
    setVideoFrameData,
    showInterventionPopup,
    interventionPopupData,
    showIntervention,
    hideIntervention,
    toggleTheme
  }
})
