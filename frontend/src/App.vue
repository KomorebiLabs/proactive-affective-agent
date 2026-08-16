<template>
  <div :class="['relative w-screen h-screen overflow-hidden font-sans selection:bg-cyan-500/30', appStore.theme === 'dark' ? 'bg-slate-950' : 'bg-slate-100']">

    <!-- 沉浸式背景纹理层 -->
    <div class="fixed inset-0 pointer-events-none opacity-30 dark:opacity-20">
      <div class="absolute inset-0 bg-gradient-to-br from-cyan-900/20 via-transparent to-purple-900/10 dark:block hidden"></div>
      <div class="absolute inset-0 noise-texture"></div>
    </div>

    <!-- 光晕层 -->
    <div
      ref="haloRef"
      class="fixed inset-0 pointer-events-none mix-blend-screen transition-all duration-1000 halo-bg"
      :style="haloStyle"
    ></div>

    <!-- 主题切换按钮 -->
    <button
      @click="appStore.toggleTheme"
      class="absolute top-6 right-6 z-50 p-2.5 rounded-xl border backdrop-blur-md transition-all duration-300 hover:scale-110 active:scale-95"
      :class="appStore.theme === 'dark'
        ? 'bg-white/10 border-white/20 text-slate-300 hover:bg-white/20'
        : 'bg-black/5 border-black/10 text-slate-600 hover:bg-black/10'"
      :title="appStore.theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'"
    >
      <svg v-if="appStore.theme === 'dark'" xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
      </svg>
      <svg v-else xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
      </svg>
    </button>

    <div class="relative z-10 flex h-full w-full max-w-[1600px] mx-auto p-6 gap-6">

      <div class="w-2/5 flex flex-col gap-6">
        <PortraitBox
          :portrait-path="appStore.currentPortraitPath"
          :emotion="appStore.currentEmotion"
          :behavior="appStore.currentBehavior"
          :intensity="appStore.debugIntensity"
          :theme="appStore.theme"
        />
        <VisualSignal
          :radar-vector="appStore.currentVector"
          :video-frame="appStore.videoFrameData"
          :intensity="appStore.debugIntensity"
          :theme="appStore.theme"
        />
      </div>

      <ChatWindow
        :messages="appStore.chatHistory"
        :is-connected="appStore.isConnected"
        :theme="appStore.theme"
        @send="handleUserMsg"
        @voice-input="handleVoiceInput"
      />
    </div>

    <!-- DebugPanel 已暂时撤下（保留代码以便日后恢复） -->
    <!-- <DebugPanel ... /> -->

    <!-- 干预弹窗（固定在最上层） -->
    <InterventionPopup
      :visible="appStore.showInterventionPopup"
      :message="appStore.interventionPopupData.message"
      :urgency="appStore.interventionPopupData.urgency"
      :auto-dismiss-seconds="appStore.interventionPopupData.autoDismissSeconds"
      :theme="appStore.theme"
      @accepted="handleInterventionAccepted"
      @rejected="handleInterventionRejected"
      @dismissed="handleInterventionDismissed"
    />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, watch, nextTick, computed, ref, defineExpose } from 'vue'
import { useAppStore } from './store/appStore'
import gsap from 'gsap'
import { PULSE_MAP } from './constants/emotions'
import { api, PERCEPTION_WS_URL } from './api'

import PortraitBox from './components/PortraitBox.vue'
import VisualSignal from './components/VisualSignal.vue'
import ChatWindow from './components/ChatWindow.vue'
import DebugPanel from './components/DebugPanel.vue'
import InterventionPopup from './components/InterventionPopup.vue'

const appStore = useAppStore()
const haloRef = ref(null)

// ─────────────────────────────────────────────────────────────────────────────
// 颜色映射
// ─────────────────────────────────────────────────────────────────────────────
const EMOTION_COLORS = {
  negative_anger: 'rgb(255, 77, 77)',
  negative_sad:   'rgb(74, 144, 226)',
  positive_joy:   'rgb(255, 179, 71)',
  neutral:        'rgb(226, 232, 240)'
}

// colorMap: Python ui_action.color → 前端光晕 emotionType
// orange 修复为 positive_joy（暖色对应积极情绪）
const COLOR_MAP = {
  blue:    'negative_sad',
  orange:  'positive_joy',   // 修复：orange → 积极/开心
  green:   'positive_joy',
  purple:  'negative_anger',
  neutral: 'neutral'
}

const haloStyle = computed(() => {
  // 浅色模式：去掉光晕，保持简洁的纯色背景
  if (appStore.theme !== 'dark') {
    return { display: 'none' }
  }
  return {
    willChange: 'box-shadow',
    transform: 'translateZ(0)',
    mixBlendMode: 'screen',
    display: 'block'
  }
})

// ─────────────────────────────────────────────────────────────────────────────
// 光晕动画
// ─────────────────────────────────────────────────────────────────────────────
const updateHaloAnimation = () => {
  if (!haloRef.value) return

  // 浅色模式：光晕层已在 haloStyle 中设为 display:none，直接返回
  if (appStore.theme !== 'dark') return

  const type = appStore.debugEmotionType
  const t = appStore.debugIntensity

  // neutral 模式：完全隐藏光晕（不在前端层面显示任何效果）
  if (type === 'neutral') {
    gsap.killTweensOf(haloRef.value)
    haloRef.value.style.opacity = '0'
    return
  }

  const targetColor = EMOTION_COLORS[type] || EMOTION_COLORS.positive_joy
  // 峰值绝对上限 0.75：t=1.0 → 0.75，t=0 → 0.3（base），脉冲时透明度 -0.25
  const targetOpacity = Math.min(0.3 + t * 0.75, 0.75)

  gsap.killTweensOf(haloRef.value)
  haloRef.value.style.opacity = '1'

  const targetShadow = `inset 0 0 150px 50px ${targetColor.replace('rgb(', 'rgba(').replace(')', `, ${targetOpacity})`)}`
  gsap.to(haloRef.value, {
    duration: 1.5,
    boxShadow: targetShadow,
    ease: 'power2.out',
    onComplete: () => {
      const pulseDuration = 5.0 - (t * 3.5)
      // 脉冲时透明度下降 0.25，最低不低于 0.05
      const pulseShadow = `inset 0 0 150px 50px ${targetColor.replace('rgb(', 'rgba(').replace(')', `, ${Math.max(0.05, targetOpacity - 0.25)})`)}`
      gsap.to(haloRef.value, {
        duration: Math.max(0.6, pulseDuration),
        boxShadow: pulseShadow,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut'
      })
    }
  })
}

watch(() => [appStore.debugEmotionType, appStore.debugIntensity], () => {
  updateHaloAnimation()
})

// ─────────────────────────────────────────────────────────────────────────────
// 用户会话初始化（带重试，等待 Java 后端启动）
// ─────────────────────────────────────────────────────────────────────────────
const MAX_INIT_RETRIES = 20
const INIT_RETRY_DELAY = 3000

const initSession = async () => {
  let lastError = null
  for (let attempt = 1; attempt <= MAX_INIT_RETRIES; attempt++) {
    try {
      const resp = await fetch(api.sessionStart, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject_name: 'anonymous', experiment_group: 'default' })
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const json = await resp.json()
      const realSessionId = json?.data?.session_id  // Java 使用 @JsonProperty("session_id") 返回 snake_case
      if (realSessionId) {
        appStore.sessionId = realSessionId
        appStore.addChatMessage('ai', `婉晴感知系统已就绪。会话ID: ${realSessionId.substring(0, 16)}...`)
        return
      }
    } catch (e) {
      lastError = e
      console.warn(`[App] 会话初始化失败（${attempt}/${MAX_INIT_RETRIES}）: ${e.message}`)
      if (attempt === 1) {
        appStore.addChatMessage('ai', '婉晴感知系统正在启动中，请稍等...')
      }
    }
    if (attempt < MAX_INIT_RETRIES) {
      await new Promise(resolve => setTimeout(resolve, INIT_RETRY_DELAY))
    }
  }
  console.error('[App] 会话初始化最终失败:', lastError)
  appStore.addChatMessage('ai', '婉晴感知系统启动超时，请检查后端服务是否正常运行。')
}

// ─────────────────────────────────────────────────────────────────────────────
// 麦克风语音采集（按压说话 → ASR → 转文字）
// 两种模式：
//   1. voice_capture 模式：长连接，持续向 openSMILE 发送音频（用于情感分析）
//   2. voice_input 模式：按压说话，松开后发送给后端 ASR → 返回识别文字
// ─────────────────────────────────────────────────────────────────────────────

// MediaRecorder 实例（用于两种模式）
let mediaRecorder = null
// 音频 chunks 缓冲区
let audioChunks = []
// 是否正在采集（情感分析模式）
let isCapturingAudio = false
// 是否正在进行按压说话
let isVoiceInputMode = false
// 当前按压说话的音频数据（所有 chunks 合并后的 PCM bytes）
let voiceInputPcmData = null

// 按压说话的采集定时器（与情感分析共用 500ms 间隔）
const AUDIO_CHUNK_INTERVAL_MS = 500
let audioChunkTimer = null

/**
 * 简单的线性插值重采样
 * @param {Float32Array} input - 输入 PCM 数据
 * @param {number} inputRate - 输入采样率
 * @param {number} outputRate - 输出采样率
 * @returns {Float32Array}
 */
const resampleAudio = (input, inputRate, outputRate) => {
  if (inputRate === outputRate) return input

  const ratio = inputRate / outputRate
  const newLength = Math.round(input.length / ratio)
  const output = new Float32Array(newLength)

  for (let i = 0; i < newLength; i++) {
    const srcIdx = i * ratio
    const srcIdxFloor = Math.floor(srcIdx)
    const srcIdxCeil = Math.min(Math.ceil(srcIdx), input.length - 1)
    const t = srcIdx - srcIdxFloor
    // 线性插值
    output[i] = input[srcIdxFloor] * (1 - t) + input[srcIdxCeil] * t
  }
  return output
}

/**
 * 将 WebM/Opus 音频数据解码为 16-bit PCM Float32Array
 * @param {Uint8Array} webmData - WebM 格式原始字节
 * @returns {Promise<{pcmBytes: Uint8Array, sampleRate: number}>} - PCM 字节及实际采样率
 */
const decodeWebmToPcm = (webmData) => {
  return new Promise(async (resolve, reject) => {
    try {
      // 确保 AudioContext 处于运行状态（浏览器自动播放策略）
      initAudioContext()
      if (audioContext.state === 'suspended') {
        await audioContext.resume()
      }

      const audioBuffer = await audioContext.decodeAudioData(
        webmData.buffer.slice(webmData.byteOffset, webmData.byteOffset + webmData.byteLength)
      )
      let floatData = audioBuffer.getChannelData(0)
      const actualSampleRate = audioBuffer.sampleRate

      // ── 阿里云 ASR 要求 16000Hz，重采样处理 ──
      const TARGET_RATE = 16000
      if (actualSampleRate !== TARGET_RATE) {
        console.log(`[VoiceInput] 重采样: ${actualSampleRate}Hz → ${TARGET_RATE}Hz`)
        floatData = resampleAudio(floatData, actualSampleRate, TARGET_RATE)
      }

      console.log(`[VoiceInput] 解码完成: ${floatData.length} 采样点, 采样率 ${TARGET_RATE}Hz`)

      // Float32 → Int16 PCM
      const pcmBytes = new Uint8Array(floatData.length * 2)
      const view = new DataView(pcmBytes.buffer)
      for (let i = 0; i < floatData.length; i++) {
        const s = Math.max(-1, Math.min(1, floatData[i]))
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
      }
      resolve({ pcmBytes, sampleRate: TARGET_RATE })
    } catch (e) {
      reject(e)
    }
  })
}

/**
 * 构建 WAV 字节流（添加 RIFF/WAVE header）
 * @param {Int8Array|Uint8Array} pcmData - 原始 PCM 数据
 * @param {number} sampleRate - 采样率，默认 16000
 * @param {number} channels - 声道数，默认 1
 */
const buildWavBlob = (pcmData, sampleRate = 16000, channels = 1) => {
  const bits = 16
  const byteRate = sampleRate * channels * (bits / 8)
  const blockAlign = channels * (bits / 8)
  const dataSize = pcmData.byteLength

  // WAV header: 44 bytes
  const header = new ArrayBuffer(44)
  const view = new DataView(header)

  // RIFF chunk descriptor
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(view, 8, 'WAVE')
  // fmt sub-chunk
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)       // Subchunk1Size (16 for PCM)
  view.setUint16(20, 1, true)        // AudioFormat (1 = PCM)
  view.setUint16(22, channels, true)  // NumChannels
  view.setUint32(24, sampleRate, true) // SampleRate
  view.setUint32(28, byteRate, true) // ByteRate
  view.setUint16(32, blockAlign, true) // BlockAlign
  view.setUint16(34, bits, true)     // BitsPerSample
  // data sub-chunk
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  const wav = new Uint8Array(header.byteLength + pcmData.byteLength)
  wav.set(new Uint8Array(header), 0)
  wav.set(new Uint8Array(pcmData), header.byteLength)
  return wav.buffer
}

const writeString = (view, offset, str) => {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i))
  }
}

/**
 * 启动按压说话模式（voice_input）
 * 按下按钮时开始采集，松开时结束采集并发送 ASR 请求
 */
const startVoiceInput = async () => {
  if (isVoiceInputMode) return

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    })

    // 使用 audio/webm 格式（兼容性最好）
    const options = { mimeType: 'audio/webm' }
    if (!MediaRecorder.isTypeSupported(options.mimeType)) {
      console.warn('[VoiceInput] 浏览器不支持 audio/webm')
      return
    }

    mediaRecorder = new MediaRecorder(stream, options)
    audioChunks = []
    voiceInputPcmData = null

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        audioChunks.push(event.data)
      }
    }

    mediaRecorder.onerror = (err) => {
      console.error('[VoiceInput] MediaRecorder 错误:', err)
      stopVoiceInput()
    }

    mediaRecorder.start()
    isVoiceInputMode = true
    console.log('[VoiceInput] 按压说话采集已启动（audio/webm）')

  } catch (err) {
    if (err.name === 'NotAllowedError') {
      console.warn('[VoiceInput] 麦克风权限被拒绝，请允许麦克风访问')
    } else if (err.name === 'NotFoundError') {
      console.warn('[VoiceInput] 未找到麦克风设备')
    } else {
      console.error('[VoiceInput] 启动失败:', err)
    }
  }
}

/**
 * 停止按压说话并发送 ASR 请求
 */
const stopVoiceInputAndSend = () => {
  if (!isVoiceInputMode || !mediaRecorder) return

  isVoiceInputMode = false

  if (audioChunkTimer) {
    clearInterval(audioChunkTimer)
    audioChunkTimer = null
  }

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    // 请求最后一次 dataavailable（Chrome 需要）
    mediaRecorder.stop()
    mediaRecorder.stream.getTracks().forEach(t => t.stop())
  }

  // 等待最后的 chunk 到达
  setTimeout(async () => {
    if (audioChunks.length === 0) {
      console.warn('[VoiceInput] 无音频数据')
      mediaRecorder = null
      audioChunks = []
      return
    }

    // 合并所有 Blob → ArrayBuffer
    let totalSize = 0
    const chunkBuffers = []
    for (const chunk of audioChunks) {
      const buf = await chunk.arrayBuffer()
      chunkBuffers.push(new Uint8Array(buf))
      totalSize += buf.byteLength
    }

    if (totalSize === 0) {
      console.warn('[VoiceInput] 音频数据为空')
      mediaRecorder = null
      audioChunks = []
      return
    }

    // 合并 webm 数据
    const merged = new Uint8Array(totalSize)
    let offset = 0
    for (const buf of chunkBuffers) {
      merged.set(buf, offset)
      offset += buf.byteLength
    }

    // audio/webm → PCM 解码
    let pcmResult
    try {
      pcmResult = await decodeWebmToPcm(merged)
    } catch (e) {
      console.error('[VoiceInput] WebM 解码失败:', e)
      appStore.addChatMessage('ai', '（婉晴没听清楚你说的，可以再试一次吗？）')
      mediaRecorder = null
      audioChunks = []
      return
    }

    if (!pcmResult || !pcmResult.pcmBytes || pcmResult.pcmBytes.byteLength === 0) {
      console.warn('[VoiceInput] PCM 解码结果为空')
      appStore.addChatMessage('ai', '（婉晴没听清楚你说的，可以再试一次吗？）')
      mediaRecorder = null
      audioChunks = []
      return
    }

    const { pcmBytes, sampleRate } = pcmResult
    // ── 调试：验证 PCM 数据完整性 ──
    console.log(`[VoiceInput] PCM 数据: ${pcmBytes.byteLength} bytes, 采样点 ${pcmBytes.byteLength / 2}, 时长 ${(pcmBytes.byteLength / 2 / sampleRate).toFixed(2)}s`)
    console.log(`[VoiceInput] PCM 前8字节(hex): ${Array.from(new Uint8Array(pcmBytes.buffer.slice(0, 8))).map(b => b.toString(16).padStart(2, '0')).join(' ')}`)

    // PCM → WAV
    const wavBuffer = buildWavBlob(pcmBytes, sampleRate, 1)

    // ── 调试：验证 WAV header ──
    const wavView = new DataView(wavBuffer)
    const riff = String.fromCharCode(wavView.getUint8(0), wavView.getUint8(1), wavView.getUint8(2), wavView.getUint8(3))
    const wave = String.fromCharCode(wavView.getUint8(8), wavView.getUint8(9), wavView.getUint8(10), wavView.getUint8(11))
    const fmt = String.fromCharCode(wavView.getUint8(12), wavView.getUint8(13), wavView.getUint8(14), wavView.getUint8(15))
    const data = String.fromCharCode(wavView.getUint8(36), wavView.getUint8(37), wavView.getUint8(38), wavView.getUint8(39))
    const actualSampleRate = wavView.getUint32(24, true)
    const bitsPerSample = wavView.getUint16(34, true)
    const dataSize = wavView.getUint32(40, true)

    console.log(`[VoiceInput] WAV Header 验证: RIFF=${riff}, WAVE=${wave}, fmt=${fmt}, data=${data}`)
    console.log(`[VoiceInput] WAV 参数: 采样率=${actualSampleRate}Hz, 位深=${bitsPerSample}bit, 数据大小=${dataSize}bytes`)
    console.log(`[VoiceInput] 发送 ASR 请求: ${wavBuffer.byteLength} bytes, 采样率 ${sampleRate}Hz (${(pcmBytes.byteLength / 2 / sampleRate).toFixed(2)}s 音频)`)
    sendVoiceInput(wavBuffer)

    mediaRecorder = null
    audioChunks = []
  }, 200)
}

/**
 * 取消按压说话（不发送）
 */
const cancelVoiceInput = () => {
  if (!isVoiceInputMode) return
  isVoiceInputMode = false

  if (audioChunkTimer) {
    clearInterval(audioChunkTimer)
    audioChunkTimer = null
  }

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
    mediaRecorder.stream.getTracks().forEach(t => t.stop())
  }

  mediaRecorder = null
  audioChunks = []
  console.log('[VoiceInput] 取消按压说话')
}

/**
 * 将 ArrayBuffer / Uint8Array 分块转为 base64（避免栈溢出和内存问题）
 * @param {ArrayBuffer|Uint8Array} buffer
 * @returns {string}
 */
const arrayBufferToBase64 = (buffer) => {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const CHUNK = 8192  // 每次处理 8KB，避免 String.fromCharCode 栈溢出
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const chunk = bytes.subarray(i, Math.min(i + CHUNK, bytes.length))
    let sub = ''
    for (let j = 0; j < chunk.length; j++) {
      sub += String.fromCharCode(chunk[j])
    }
    binary += sub
  }
  return btoa(binary)
}

/**
 * 通过 WebSocket 发送语音输入（ASR 请求）
 * @param {ArrayBuffer} wavBuffer - WAV 格式音频数据
 */
const sendVoiceInput = (wavBuffer) => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    console.warn('[VoiceInput] WebSocket 未连接，无法发送')
    return
  }
  const base64Wav = arrayBufferToBase64(wavBuffer)
  socket.send(JSON.stringify({
    type: 'voice_input',
    data: base64Wav,
    sampleRate: 16000,
    channels: 1,
    timestamp: Date.now(),
  }))
}

/**
 * 处理后端返回的 ASR 识别结果
 */
const handleVoiceInputResult = (text) => {
  if (!text || !text.trim()) return
  // 将识别文字填入 ChatWindow 并继续对话
  handleUserMsg(text.trim())
}

/**
 * 对外暴露：供 ChatWindow 调用
 */
const onVoiceButtonDown = () => { startVoiceInput() }
const onVoiceButtonUp = () => { stopVoiceInputAndSend() }
const onVoiceButtonCancel = () => { cancelVoiceInput() }

defineExpose({ onVoiceButtonDown, onVoiceButtonUp, onVoiceButtonCancel })

// ─────────────────────────────────────────────────────────────────────────────
// 流式音频播放状态（多队列方案：按 stream_id 隔离不同音频流）
// ─────────────────────────────────────────────────────────────────────────────
let socket = null
let wsReconnectTimer = null   // 跟踪 WS 重连定时器

// 流式音频播放状态（多队列方案：按 stream_id 隔离不同音频流）
const audioStreams = new Map()  // stream_id -> { chunks: Uint8Array[], startTime: number, audio: Audio | null, receivedEnd: boolean, mediaSource: MediaSource | null, sourceBuffer: SourceBuffer | null }

// 【修复8】流数据内存保护：每个流最大 chunks 数和总大小限制
const MAX_CHUNKS_PER_STREAM = 500
const MAX_BYTES_PER_STREAM = 50 * 1024 * 1024  // 50MB
const STREAM_CLEANUP_TIMEOUT = 120000  // 2分钟无更新则清理

// 【修复7】voice_stream_end 兜底定时器：防止 end 消息丢失导致音频延迟
const streamEndTimers = new Map()  // stream_id -> timeout_id

// 【修复11】心跳机制
const HEARTBEAT_INTERVAL = 25000  // 25秒发送一次心跳
const HEARTBEAT_TIMEOUT = 35000   // 35秒没响应则认为连接假死
let lastPongTime = Date.now()
let heartbeatTimer = null

// 流式播放 Web Audio API 上下文（用于边收边播）
let audioContext = null
// 流式播放用的 MediaSource（可追加 chunk）
let activeMediaSource = null

// 初始化 Web Audio API 上下文
const initAudioContext = () => {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)()
    console.log('[App] Web Audio API 上下文已初始化')
  }
  return audioContext
}

// ============================================================
// 统一音频播放管理器
// 核心设计：
// 1. 只有一套播放逻辑：playStreamById
// 2. 播放失败后不再重试，而是直接清理
// 3. playNextInQueue 只在没有任何流播放时调用
// ============================================================

// 当前正在播放的流 ID（防止重复播放）
let currentlyPlayingId = null

// 流式播放结束回调（统一播放入口）
// 使用 MediaSource API：首个 chunk 建立 MediaSource，后续 chunk 实时追加
const playStreamById = (streamId) => {
  const stream = audioStreams.get(streamId)
  if (!stream) {
    console.warn(`[App] playStreamById: 找不到流 (${streamId})`)
    return
  }
  if (stream.chunks.length === 0) {
    console.warn(`[App] playStreamById: 流 (${streamId}) 无音频数据，跳过播放`)
    audioStreams.delete(streamId)
    return
  }

  // 【关键】防止重复播放同一个流
  if (currentlyPlayingId === streamId) {
    console.log(`[App] playStreamById: 流 (${streamId}) 正在播放，跳过`)
    return
  }

  console.log(`[App] ★ 开始播放音频 (${streamId}): ${stream.chunks.length} chunks`)

  // 验证音频数据
  const firstBytes = stream.chunks[0].slice(0, 10)
  const firstBytesHex = Array.from(firstBytes).map(b => b.toString(16).padStart(2, '0')).join(' ')
  console.log(`[App] 流 (${streamId}) 音频头 (hex): ${firstBytesHex}, 总大小: ${stream.chunks.reduce((a, c) => a + c.length, 0)} bytes`)

  // 使用 MediaSource API，支持实时追加 chunk
  const mime = 'audio/mpeg'
  if (!MediaSource.isTypeSupported(mime)) {
    console.error(`[App] 浏览器不支持 audio/mpeg，fallback 到 Audio 元素`)
    _playWithAudioElement(stream, streamId)
    return
  }

  const mediaSource = new MediaSource()
  const blobUrl = URL.createObjectURL(mediaSource)
  const audio = new Audio(blobUrl)
  audio.volume = 1.0
  stream.audio = audio
  stream.blobUrl = blobUrl
  stream.isPlaying = true
  stream.ms = mediaSource
  stream.sourceBuffer = null
  stream.pendingChunks = []
  stream.msReady = false
  currentlyPlayingId = streamId

  let sourceBuffer = null

  mediaSource.addEventListener('sourceopen', () => {
    if (stream.sourceBuffer) return
    try {
      sourceBuffer = mediaSource.addSourceBuffer(mime)
      sourceBuffer.addEventListener('updateend', () => {
        stream.msReady = true
        // 追加所有待处理 chunk
        while (stream.pendingChunks.length > 0) {
          const pending = stream.pendingChunks.shift()
          if (!sourceBuffer.updating) {
            sourceBuffer.appendBuffer(pending)
          }
        }
      })
      sourceBuffer.addEventListener('error', (e) => {
        console.error(`[App] 流 (${streamId}) SourceBuffer error:`, e)
        _finishAndPlayNext(streamId, 'SourceBuffer错误')
      })
      stream.sourceBuffer = sourceBuffer

      // 追加已有的 chunks
      if (stream.chunks.length > 0 && !sourceBuffer.updating) {
        const merged = _mergeChunks(stream.chunks)
        sourceBuffer.appendBuffer(merged)
        stream.chunks = []  // 追加后清空，避免重复
      }

      // 播放
      audio.play().catch(e => {
        console.error(`[App] 流 (${streamId}) play() 失败: ${e.message}`)
        _finishAndPlayNext(streamId, 'play失败')
      })
    } catch (e) {
      console.error(`[App] MediaSource setup 失败，回退: ${e}`)
      URL.revokeObjectURL(blobUrl)
      mediaSource.close()
      stream.isPlaying = false
      currentlyPlayingId = null
      stream.audio = null
      stream.blobUrl = null
      stream.ms = null
      _playWithAudioElement(stream, streamId)
    }
  })

  // 设置回调
  audio.onended = () => {
    console.log(`[App] 流 (${streamId}) onended`)
    clearTimeout(stream._timeoutId)
    _finishAndPlayNext(streamId, '正常结束')
  }
  audio.onerror = (e) => {
    console.error(`[App] 流 (${streamId}) onerror: ${audio.error?.message || 'unknown'}`)
    clearTimeout(stream._timeoutId)
    _finishAndPlayNext(streamId, '播放失败')
  }
  stream._timeoutId = setTimeout(() => {
    console.warn(`[App] 流 (${streamId}) 30秒超时，强制结束`)
    _finishAndPlayNext(streamId, '超时')
  }, 30000)
}

// 统一的流结束处理（清理 MediaSource + 播放队列下一条）
const _finishAndPlayNext = (streamId, reason) => {
  const stream = audioStreams.get(streamId)
  if (!stream) return
  console.log(`[App] finishPlayback (${streamId}): ${reason}`)

  if (currentlyPlayingId === streamId) currentlyPlayingId = null
  stream.isPlaying = false

  if (stream.blobUrl) {
    try { URL.revokeObjectURL(stream.blobUrl) } catch (e) {}
    stream.blobUrl = null
  }
  if (stream.ms) {
    try { stream.ms.close() } catch (e) {}
    stream.ms = null
  }
  stream.audio = null

  audioStreams.delete(streamId)
  playNextInQueue()
}

// 追加 chunk 到正在播放的流（实时追加）
const _appendChunkToStream = (streamId, chunk) => {
  const stream = audioStreams.get(streamId)
  if (!stream) return

  if (stream.sourceBuffer && !stream.sourceBuffer.updating) {
    try {
      stream.sourceBuffer.appendBuffer(chunk)
      return
    } catch (e) {
      console.warn(`[App] SourceBuffer appendBuffer 失败: ${e}，放入待处理`)
    }
  }
  // sourceBuffer 正忙或未就绪，放入待处理
  stream.pendingChunks.push(chunk)
}

// fallback：用 Audio 元素播放（MediaSource 不可用时）
const _playWithAudioElement = (stream, streamId) => {
  if (stream.chunks.length === 0) {
    audioStreams.delete(streamId)
    playNextInQueue()
    return
  }
  const merged = _mergeChunks(stream.chunks)
  if (merged.length === 0) {
    audioStreams.delete(streamId)
    playNextInQueue()
    return
  }
  const blob = new Blob([merged], { type: 'audio/mpeg' })
  const blobUrl = URL.createObjectURL(blob)
  const audio = new Audio(blobUrl)
  audio.volume = 1.0
  stream.audio = audio
  stream.blobUrl = blobUrl
  stream.isPlaying = true
  currentlyPlayingId = streamId

  audio.onended = () => {
    console.log(`[App] 流 (${streamId}) onended (Audio fallback)`)
    clearTimeout(stream._timeoutId)
    _finishAndPlayNext(streamId, '正常结束')
  }
  audio.onerror = () => {
    console.error(`[App] 流 (${streamId}) onerror (Audio fallback)`)
    clearTimeout(stream._timeoutId)
    _finishAndPlayNext(streamId, '播放失败')
  }
  stream._timeoutId = setTimeout(() => {
    console.warn(`[App] 流 (${streamId}) 30秒超时`)
    _finishAndPlayNext(streamId, '超时')
  }, 30000)

  audio.play().catch(e => {
    console.error(`[App] 流 (${streamId}) play() 失败: ${e.message}`)
    _finishAndPlayNext(streamId, 'play失败')
  })
}

// 合并多个 chunk
const _mergeChunks = (chunks) => {
  const total = chunks.reduce((a, c) => a + c.length, 0)
  const result = new Uint8Array(total)
  let offset = 0
  for (const c of chunks) { result.set(c, offset); offset += c.length }
  return result
}

// 播放队列中下一条音频
const playNextInQueue = () => {
  console.log(`[App] playNextInQueue 被调用，当前队列: ${audioStreams.size} 个流`)

  if (audioStreams.size === 0) {
    console.log(`[App] 播放队列为空`)
    return
  }

  // 如果已经有流在播放，不重复播放
  if (currentlyPlayingId !== null) {
    console.log(`[App] 已有流 (${currentlyPlayingId}) 在播放，跳过 playNextInQueue`)
    return
  }

  // 列出所有流的状态
  for (const [id, stream] of audioStreams) {
    console.log(`[App] 流状态: ${id}, chunks: ${stream.chunks.length}, audio: ${stream.audio ? '有' : '无'}, ms: ${stream.ms ? '有' : '无'}, receivedEnd: ${stream.receivedEnd}`)
  }

  // 找到最早开始的、尚未播放的音频
  let earliest = null
  let earliestId = null
  for (const [id, stream] of audioStreams) {
    if (stream.audio === null) {  // 尚未播放
      if (!earliest || stream.startTime < earliest.startTime) {
        earliest = stream
        earliestId = id
      }
    }
  }

  if (earliestId) {
    console.log(`[App] playNextInQueue 找到下一条: ${earliestId}，开始播放...`)
    playStreamById(earliestId)
  } else {
    console.log(`[App] 所有音频都在播放中或已完成，无可播放流`)
  }
}

// ============================================================
// WebSocket 感知总线
// ============================================================
const connectPerceptionBus = () => {
  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) return

  socket = new WebSocket(PERCEPTION_WS_URL)

  socket.onopen = () => {
    appStore.setConnection(true)
  }

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      const recvTime = Date.now()
      
      // 【TTS重构】延迟监控
      if (msg.type === 'voice_stream' && msg.send_timestamp) {
        const delay = recvTime - msg.send_timestamp
        console.log(`[App] TTS 延迟: ${delay}ms (stream_id=${msg.stream_id})`)
        if (delay > 1000) {
          console.warn(`[App] ⚠️ TTS 消息延迟异常: ${delay}ms`)
        }
      }
      
      if (msg.type === 'video_frame') {
        appStore.setVideoFrameData(msg.data)
      } else if (msg.type === 'perception_update') {
        // Q4: 使用 timestamp_ms（整数毫秒）与 SSE 的 Date.now() 对齐
        const wsTimestamp = msg.data.timestamp_ms || 0
        // Q3: 标记为 WebSocket 实时通道，驱动 emotionHistory 追加
        appStore.updatePerception({ ...msg.data, _fromWebSocket: true, _perceptionTimestamp: wsTimestamp })
      } else if (msg.type === 'voice_play') {
        // voice_play 现在只接收 Base64 内嵌数据（data:audio/mp3;base64,...）
        // 不再支持外部 URL，从根本上消除 SSRF 风险
        if (typeof msg.data === 'string' && msg.data.startsWith('data:audio')) {
          new Audio(msg.data).play().catch(e => console.warn('[App] 音频播放失败:', e.message))
        } else {
          console.warn('[App] voice_play 收到无效格式，已拒绝:', msg.data)
        }
      } else if (msg.type === 'voice_stream') {
        // 流式音频块：按 stream_id 路由到对应队列
        // 【核心改动】移除 pendingChunks 依赖，每个消息的音频独立播放
        let activeStreamId = msg.stream_id || 'default'
        console.log(`[App] 收到 voice_stream (${activeStreamId}) 时间=${recvTime}, is_first=${msg.is_first}`)
        
        // 【关键】每个 stream_id 应该对应独立的音频流
        // 如果收到 is_first=true，但该 stream_id 已存在：
        // 1. 如果旧流不在播放：直接删除，创建新流
        // 2. 如果旧流正在播放：保留旧流，让它播完
        //    新音频需要等待旧流结束后再处理（创建新流或使用新 stream_id）
        if (msg.is_first && audioStreams.has(activeStreamId)) {
          const existingStream = audioStreams.get(activeStreamId)
          // 如果旧流不在播放（没有 audio 对象或已暂停），清理后创建新流
          if (!existingStream.audio || existingStream.audio.paused) {
            console.log(`[App] 流 (${activeStreamId}) 旧音频不在播放，清理后创建新流`)
            if (existingStream.blobUrl) {
              try { URL.revokeObjectURL(existingStream.blobUrl) } catch (e) {}
            }
            if (existingStream.ms) {
              try { existingStream.ms.close() } catch (e) {}
            }
            if (existingStream.audio) {
              try { existingStream.audio.pause() } catch (e) {}
            }
            audioStreams.delete(activeStreamId)
          } else {
            const originalStreamId = activeStreamId
            activeStreamId = `${activeStreamId}_${Date.now()}`
            console.log(`[App] 流 (${originalStreamId}) 正在播放，创建新流 (${activeStreamId})`)
            audioStreams.set(activeStreamId, { chunks: [], startTime: null, audio: null, receivedEnd: false, isPlaying: false, blobUrl: null, ms: null, sourceBuffer: null, pendingChunks: [], msReady: false, originalStreamId: originalStreamId })
          }
        }

        if (!audioStreams.has(activeStreamId)) {
          audioStreams.set(activeStreamId, { chunks: [], startTime: null, audio: null, receivedEnd: false, isPlaying: false, blobUrl: null, ms: null, sourceBuffer: null, pendingChunks: [], msReady: false })
        }
        const stream = audioStreams.get(activeStreamId)

        // 提取纯 base64 内容
        if (typeof msg.data === 'string' && msg.data) {
          let base64Content = msg.data
          if (msg.data.includes(',')) {
            base64Content = msg.data.split(',')[1] || msg.data
          }

          // 【修复6】atob() 异常捕获，防止 base64 解析失败导致整个消息处理链断裂
          let bytes
          try {
            const binaryString = atob(base64Content)
            bytes = new Uint8Array(binaryString.length)
            for (let i = 0; i < binaryString.length; i++) {
              bytes[i] = binaryString.charCodeAt(i)
            }
          } catch (e) {
            console.error(`[App] base64 解码失败 (${activeStreamId}): ${e.message}`)
            return
          }

          // 【修复7】voice_stream_end 兜底定时器
          if (streamEndTimers.has(activeStreamId)) {
            clearTimeout(streamEndTimers.get(activeStreamId))
          }
          const timerId = setTimeout(() => {
            console.warn(`[App] voice_stream_end 等待超时 (${activeStreamId})，强制触发播放`)
            streamEndTimers.delete(activeStreamId)
            const s = audioStreams.get(activeStreamId)
            if (s && s.chunks.length > 0 && !s.audio) {
              stream.receivedEnd = true
              playNextInQueue()
            }
          }, 10000)
          streamEndTimers.set(activeStreamId, timerId)

          // 【修复8】流数据内存保护
          if (stream.chunks.length >= MAX_CHUNKS_PER_STREAM) {
            console.warn(`[App] 流 (${activeStreamId}) chunks 数量已达上限 (${MAX_CHUNKS_PER_STREAM})，移除旧数据`)
            stream.chunks.shift()
          }
          const estimatedTotalBytes = (stream.totalBytes || 0) + bytes.length
          if (estimatedTotalBytes > MAX_BYTES_PER_STREAM) {
            console.warn(`[App] 流 (${activeStreamId}) 总大小超过限制，截断旧数据`)
            const keepCount = Math.floor(stream.chunks.length * 0.8)
            stream.chunks = stream.chunks.slice(0, keepCount)
            stream.totalBytes = stream.chunks.reduce((acc, c) => acc + c.length, 0)
          }
          stream.totalBytes = estimatedTotalBytes

          if (msg.is_first || !stream.startTime) {
            // 第一个块：初始化队列
            console.log(`[App] 开始接收流式音频 (${activeStreamId})...`)
            stream.chunks = [bytes]
            stream.startTime = Date.now()
            stream.audio = null
            stream.receivedEnd = false
            stream.isPlaying = false
            stream.ms = null
            stream.sourceBuffer = null
            stream.pendingChunks = []
            stream.msReady = false

            // 【修复9】预缓冲时间优化：200ms（更适合网络波动）
            setTimeout(() => {
              const s = audioStreams.get(activeStreamId)
              if (s && s.chunks.length > 0) {
                console.log(`[App] 流 (${activeStreamId}) 收到 ${s.chunks.length} chunks，加入播放队列`)
                playNextInQueue()
              }
            }, 200)  // 200ms 预缓冲
          } else {
            // 后续块：追加到 chunks 数组
            stream.chunks.push(bytes)

            // 如果该流正在播放且有 MediaSource，实时追加到 SourceBuffer
            if (stream.isPlaying && stream.sourceBuffer) {
              _appendChunkToStream(activeStreamId, bytes)
            }
          }
        }
      } else if (msg.type === 'voice_stream_end') {
        // 流式播放结束：标记并尝试播放
        let endStreamId = msg.stream_id || 'default'
        let stream = audioStreams.get(endStreamId)

        // 如果找不到精确匹配的流，尝试查找 originalStreamId 匹配的新流
        if (!stream) {
          for (const [key, s] of audioStreams) {
            if (s.originalStreamId === endStreamId) {
              stream = s
              endStreamId = key
              console.log(`[App] voice_stream_end: 找不到 ${endStreamId}，找到匹配流 ${key}`)
              break
            }
          }
        }

        if (stream) {
          // 【修复7】清除 end 兜底定时器
          if (streamEndTimers.has(endStreamId)) {
            clearTimeout(streamEndTimers.get(endStreamId))
            streamEndTimers.delete(endStreamId)
          }

          stream.receivedEnd = true
          console.log(`[App] 流式音频接收完毕 (${endStreamId}): ${stream.chunks.length} chunks`)

          if (!stream.audio) {
            console.log(`[App] 流 (${endStreamId}) 不在播放，尝试开始播放...`)
            playNextInQueue()
          } else {
            console.log(`[App] 流 (${endStreamId}) 正在播放或已播放完毕`)
          }
        } else {
          console.warn(`[App] voice_stream_end 找不到流 (${endStreamId})`)
        }
      } else if (msg.type === 'pong') {
        // 【修复11】心跳响应
        lastPongTime = Date.now()
        console.log('[App] 收到心跳响应')
      } else if (msg.type === 'voice_input_result') {
        // ASR 识别结果
        if (msg.success && msg.text) {
          console.log(`[App] ASR 识别结果: ${msg.text}`)
          handleVoiceInputResult(msg.text)
        } else {
          // 显示真实错误信息（便于调试）
          console.warn('[App] ASR 识别失败:', msg.error, 'error_type:', msg.error_type)
          appStore.addChatMessage('ai', `（婉晴没听清楚你说的，请稍后重试）`)
        }
      }
    } catch (e) {
      console.error('[App] WebSocket 消息解析失败:', e)
    }
  }

  socket.onerror = (e) => {
    console.error('[App] WebSocket 连接错误:', e)
    // 【修复10】WebSocket onerror 无重连：在 onerror 中也触发重连
    appStore.setConnection(false)
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
    wsReconnectTimer = setTimeout(connectPerceptionBus, 3000)
  }

  socket.onclose = () => {
    appStore.setConnection(false)
    // 【修复11】心跳清理
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
    wsReconnectTimer = setTimeout(connectPerceptionBus, 3000)
  }

  // 【修复11】启动心跳机制
  startHeartbeat()
}

const startHeartbeat = () => {
  if (heartbeatTimer) clearInterval(heartbeatTimer)

  lastPongTime = Date.now()
  heartbeatTimer = setInterval(() => {
    // 检查心跳响应超时
    if (Date.now() - lastPongTime > HEARTBEAT_TIMEOUT) {
      console.warn('[App] 心跳超时，连接可能已假死')
      if (socket) {
        socket.close()
        socket = null
      }
      return
    }

    // 发送 ping
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }))
      console.log('[App] 发送心跳 ping')
    }
  }, HEARTBEAT_INTERVAL)
}

// ─────────────────────────────────────────────────────────────────────────────
// SSE Agent 响应
// ─────────────────────────────────────────────────────────────────────────────
let agentAbortController = null

const sendAgentRequest = (userMessage) => {
  if (agentAbortController) agentAbortController.abort()
  agentAbortController = new AbortController()

  const sessionId = appStore.sessionId
  if (!sessionId) {
    // 会话未就绪时自动触发重连；占位 AI 气泡已由 handleUserMsg 添加，只更新文案
    appStore.updateLastAIMessage('婉晴正在重新连接服务，请稍等...')
    initSession().then(() => {
      if (appStore.sessionId) sendAgentRequest(userMessage)
    })
    return
  }

  _fetchAgentSSE(api.chatStream, sessionId, userMessage, agentAbortController.signal)
}

const _fetchAgentSSE = async (url, sessionId, userMessage, signal) => {
  let accumulatedReply = ''

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + sessionId
      },
      body: JSON.stringify({ message: userMessage }),
      signal,
    })

    if (!response.ok) {
      appStore.updateLastAIMessage(`婉晴服务暂时不可用（${response.status}），请稍后重试。`)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const rawLine of lines) {
        // Spring SseEmitter 通常发出 data:{...}（冒号后无空格）；Python FastAPI 多为 data: {...}
        // 只认 data: 前缀，避免漏掉整段流
        const line = rawLine.replace(/\r$/, '')
        if (!line.startsWith('data:')) continue
        let jsonStr = line.slice(5)
        if (jsonStr.startsWith(' ')) jsonStr = jsonStr.slice(1)
        if (!jsonStr.trim()) continue
        try {
          const payload = JSON.parse(jsonStr)

          // 逐字流式渲染
          if (payload.chunk) {
            accumulatedReply += payload.chunk
            appStore.updateLastAIMessage(accumulatedReply)
          }

          // 最终帧：通过唯一入口更新所有决策状态 【Plan1-B】
          if (payload.is_end) {
            // 统一调用 store 单入口
            appStore.applyFinalDecisionSnapshot(payload)

            // UI 动作指令驱动光晕（保持独立，因为需要实时响应）
            if (payload.ui_action) {
              const emotionType = COLOR_MAP[payload.ui_action.color]
              const intensity   = PULSE_MAP[payload.ui_action.pulse]
              if (emotionType) appStore.debugEmotionType = emotionType
              if (intensity !== undefined) appStore.debugIntensity = intensity
              updateHaloAnimation()
            }

            // 干预弹窗触发（SSE 最终帧携带 intervention_alert）
            if (payload.intervention_alert) {
              const alert = payload.intervention_alert
              if (alert.show_popup) {
                appStore.showIntervention({
                  urgency: alert.urgency || 'low',
                  message: alert.message || '婉晴感受到你可能心情有些不好，需要聊聊吗？'
                })
              }
            }
          }
        } catch (e) {
          console.warn('[App] SSE 行解析失败，原始内容:', line.substring(0, 120), e.message)
        }
      }
    }
    // 若 buffer 里残留最后一行未以 \n 结束，仍尝试解析（部分浏览器分块边界）
    if (buffer.trim()) {
      const line = buffer.replace(/\r$/, '')
      if (line.startsWith('data:')) {
        let jsonStr = line.slice(5)
        if (jsonStr.startsWith(' ')) jsonStr = jsonStr.slice(1)
        if (jsonStr.trim()) {
          try {
            const payload = JSON.parse(jsonStr)
            if (payload.chunk) {
              accumulatedReply += payload.chunk
              appStore.updateLastAIMessage(accumulatedReply)
            }
          } catch (_) { /* ignore */ }
        }
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') return
    console.error('[App] SSE 响应流异常:', e)
    appStore.updateLastAIMessage('婉晴：抱歉，响应过程中遇到了问题，请重试。')
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 干预弹窗反馈处理
// ─────────────────────────────────────────────────────────────────────────────
const sendInterventionFeedback = async (choice) => {
  try {
    await fetch(api.feedback, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: appStore.sessionId,
        choice,                                      // 'accepted' | 'rejected' | 'ignored'
        emotion_vector: Object.fromEntries(
          ['喜悦', '悲伤', '愤怒', '恐惧', '厌恶', '惊讶', '踏实感', '期待']
            .map((k, i) => [k, appStore.currentVector[i] || 0])
        ),
        current_emotion: appStore.currentEmotion
      })
    })
  } catch (e) {
    console.warn('[App] 反馈发送失败:', e)
  }
}

const handleInterventionAccepted = () => {
  sendInterventionFeedback('accepted')
  appStore.hideIntervention()
}

const handleInterventionRejected = () => {
  sendInterventionFeedback('rejected')
  appStore.hideIntervention()
}

const handleInterventionDismissed = (reason) => {
  sendInterventionFeedback(reason || 'ignored')
  appStore.hideIntervention()
}

const handleUserMsg = (text) => {
  appStore.addChatMessage('user', text)
  appStore.addChatMessage('ai', '')
  sendAgentRequest(text)
}

/**
 * 处理 ChatWindow 传来的语音输入事件
 * ChatWindow 的语音按钮按下/松开会触发这里
 */
const handleVoiceInput = ({ action }) => {
  if (action === 'start') {
    onVoiceButtonDown()
  } else if (action === 'stop') {
    onVoiceButtonUp()
  } else if (action === 'cancel') {
    onVoiceButtonCancel()
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 生命周期
// ─────────────────────────────────────────────────────────────────────────────
onMounted(async () => {
  // 1. 初始化用户会话
  await initSession()

  // 2. 连接感知总线
  connectPerceptionBus()

  // 3. 初始化光晕
  nextTick(() => {
    updateHaloAnimation()
  })
})

onUnmounted(() => {
  // 清理 1：中止 SSE 请求（Phase C1）
  if (agentAbortController) {
    agentAbortController.abort()
    agentAbortController = null
  }

  // 清理 2：关闭 WebSocket
  if (socket) {
    socket.close()
    socket = null
  }

  // 清理 3：取消 WS 重连定时器（Phase C1）
  if (wsReconnectTimer !== null) {
    clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }

  // 清理 4：停止光晕动画
  if (haloRef.value) {
    gsap.killTweensOf(haloRef.value)
  }

  // 清理 5：停止心跳定时器
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }

  // 清理 6：清理所有流式音频的兜底定时器
  for (const timerId of streamEndTimers.values()) {
    clearTimeout(timerId)
  }
  streamEndTimers.clear()

  // 清理 7：取消按压说话
  cancelVoiceInput()
})
</script>

<style>
/* GSAP 直接操作 boxShadow，无需 CSS 规则 */

/* 背景微纹理 */
.noise-texture {
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  opacity: 0.03;
}

/* 深色模式下的纹理增强 */
.dark .noise-texture {
  opacity: 0.04;
}
</style>
