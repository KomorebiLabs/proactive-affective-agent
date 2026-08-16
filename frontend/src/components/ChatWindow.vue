<template>
  <div class="w-3/5 rounded-3xl border backdrop-blur-xl flex flex-col overflow-hidden shadow-2xl transition-all duration-500 relative"
    :class="theme === 'dark'
      ? 'border-white/10 bg-gradient-to-b from-white/[0.07] to-black/50 shadow-cyan-900/10'
      : 'border-black/5 bg-gradient-to-b from-white/90 to-slate-200/70'"
  >
    <!-- 顶部栏 -->
    <div class="h-16 border-b flex items-center px-6 justify-between transition-all duration-500 backdrop-blur-sm"
      :class="theme === 'dark' ? 'border-white/[0.06] bg-black/30' : 'border-black/[0.05] bg-white/70'"
    >
      <div class="flex items-center gap-3">
        <div class="relative">
          <div class="w-2 h-2 rounded-full animate-pulse" :class="isConnected ? 'bg-emerald-500' : 'bg-red-500'"></div>
          <div class="absolute inset-0 w-2 h-2 rounded-full animate-ping opacity-60" :class="isConnected ? 'bg-emerald-500' : 'bg-red-500'"></div>
        </div>
        <span class="text-lg font-medium tracking-wider transition-colors duration-500"
          :class="theme === 'dark' ? 'text-slate-200' : 'text-slate-800'"
        >婉晴 <span class="text-xs text-slate-500 ml-1 font-normal">Live</span></span>
      </div>
      <div class="text-xs font-mono transition-colors duration-500" :class="theme === 'dark' ? 'text-slate-500' : 'text-slate-400'">{{ isConnected ? 'REALTIME CONNECTED' : 'OFFLINE' }}</div>
    </div>

    <!-- 聊天记录 -->
    <div ref="chatContainer" class="flex-1 overflow-y-auto p-6 space-y-5 custom-scrollbar">
      <div v-for="(msg, index) in messages" :key="index" class="flex gap-4 group animate-message-in" :class="msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'">
        <div class="w-10 h-10 rounded-full overflow-hidden border flex-shrink-0 transition-transform duration-300 group-hover:scale-105 ring-2 ring-offset-2"
          :class="[
            msg.role === 'user' ? 'ring-cyan-500/50' : 'ring-white/20',
            theme === 'dark' ? 'bg-slate-700/50 border-white/20' : 'bg-slate-300/60 border-black/10'
          ]"
        >
          <img :src="msg.role === 'user' ? '/portraits/user_avatar.png' : '/portraits/ai_avatar.png'" class="w-full h-full object-cover" @error="handleImgError" />
        </div>
        <div class="max-w-[75%] px-5 py-3.5 rounded-2xl text-sm leading-relaxed transition-all duration-300 shadow-lg backdrop-blur-sm"
          :class="msg.role === 'user'
            ? (theme === 'dark'
                ? 'bg-gradient-to-br from-cyan-600/90 to-cyan-700/90 text-white rounded-tr-lg shadow-cyan-500/20'
                : 'bg-gradient-to-br from-cyan-500/90 to-cyan-600/90 text-white rounded-tr-lg')
            : (theme === 'dark'
                ? 'bg-white/[0.08] text-slate-200 border border-white/[0.08] rounded-tl-lg backdrop-blur-md'
                : 'bg-white/70 text-slate-800 border border-black/5 rounded-tl-lg')"
        >
          {{ msg.text }}
        </div>
      </div>
    </div>

    <!-- 输入栏 -->
    <div class="p-5 border-t transition-all duration-500 backdrop-blur-sm"
      :class="theme === 'dark' ? 'bg-black/30 border-white/[0.06]' : 'bg-white/70 border-black/[0.05]'"
    >
      <div class="relative flex items-end gap-3 border rounded-2xl p-2.5 transition-all duration-300 group"
        :class="theme === 'dark'
          ? 'bg-white/[0.03] border-white/10 hover:border-white/20 focus-within:border-cyan-500/40'
          : 'bg-white/40 border-black/10 hover:border-black/20 focus-within:border-cyan-400/50'"
      >
        <!-- 语音输入按钮（按压说话） -->
        <button
          ref="voiceBtn"
          @mousedown="onVoiceBtnDown"
          @mouseup="onVoiceBtnUp"
          @mouseleave="onVoiceBtnCancel"
          @touchstart.prevent="onVoiceBtnDown"
          @touchend.prevent="onVoiceBtnUp"
          @touchcancel="onVoiceBtnCancel"
          class="mb-1 p-2.5 rounded-xl flex-shrink-0 flex items-center justify-center transition-all duration-200 active:scale-90"
          :class="isVoiceRecording
            ? 'bg-red-500/20 border border-red-500/50 text-red-400'
            : (theme === 'dark'
                ? 'bg-white/5 border border-white/10 text-slate-400 hover:text-slate-200 hover:bg-white/10'
                : 'bg-black/5 border border-black/10 text-slate-400 hover:text-slate-600 hover:bg-black/5')"
          :title="isVoiceRecording ? '松开发送语音' : '按住说话，松开后发送'"
        >
          <!-- 麦克风图标（录音时显示音波动画） -->
          <div class="relative">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
            <!-- 录音中音波指示器 -->
            <div v-if="isVoiceRecording" class="absolute -bottom-1 left-1/2 -translate-x-1/2 flex gap-0.5">
              <span class="w-0.5 h-1.5 bg-red-400 rounded-full animate-pulse" style="animation-duration: 0.4s"></span>
              <span class="w-0.5 h-2 bg-red-400 rounded-full animate-pulse" style="animation-duration: 0.5s; animation-delay: 0.1s"></span>
              <span class="w-0.5 h-1.5 bg-red-400 rounded-full animate-pulse" style="animation-duration: 0.4s; animation-delay: 0.2s"></span>
            </div>
          </div>
        </button>

        <textarea
          v-model="inputMsg"
          @keydown.enter.prevent="handleSend"
          placeholder="与婉晴对话，或按住麦克风说话..."
          class="w-full bg-transparent border-none text-sm p-2 max-h-32 focus:ring-0 resize-none transition-colors duration-500"
          :class="theme === 'dark' ? 'text-slate-200 placeholder-slate-500/70' : 'text-slate-800 placeholder-slate-400/70'"
          rows="1"
        ></textarea>
        <button
          @click="handleSend"
          class="mb-1 p-2.5 rounded-xl bg-gradient-to-br from-cyan-500 to-cyan-600 hover:from-cyan-400 hover:to-cyan-500 text-white shadow-lg hover:shadow-cyan-500/30 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 disabled:shadow-none"
          :disabled="!inputMsg.trim()"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  messages: {
    type: Array,
    required: true
  },
  isConnected: {
    type: Boolean,
    default: true
  },
  theme: {
    type: String,
    default: 'dark'
  }
})

const emit = defineEmits(['send', 'voice-input'])
const inputMsg = ref('')
const chatContainer = ref(null)
const voiceBtn = ref(null)
const isVoiceRecording = ref(false)

const handleSend = () => {
  if (!inputMsg.value.trim()) return
  emit('send', inputMsg.value)
  inputMsg.value = ''
}

// 语音按钮按下 → 开始采集
const onVoiceBtnDown = () => {
  isVoiceRecording.value = true
  emit('voice-input', { action: 'start' })
}

// 语音按钮松开 → 结束采集并发送
const onVoiceBtnUp = () => {
  isVoiceRecording.value = false
  emit('voice-input', { action: 'stop' })
}

// 鼠标移出按钮区域 → 取消采集（不发送）
const onVoiceBtnCancel = () => {
  if (!isVoiceRecording.value) return
  isVoiceRecording.value = false
  emit('voice-input', { action: 'cancel' })
}

const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

const handleImgError = (e) => { e.target.src = 'https://via.placeholder.com/40' }

// 监听消息变化自动滚动
watch(() => props.messages, () => {
  scrollToBottom()
}, { deep: true })
</script>

<style scoped>
/* 自定义滚动条样式 */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.2);
  border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.3);
}

/* 消息进入动画 */
@keyframes messageIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-message-in {
  animation: messageIn 0.3s ease-out forwards;
}
</style>
