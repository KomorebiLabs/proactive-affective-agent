<template>
  <Teleport to="body">
    <Transition name="popup">
      <div
        v-if="visible"
        class="fixed bottom-8 right-8 z-[100] w-80 rounded-2xl border backdrop-blur-xl shadow-2xl overflow-hidden"
        :class="theme === 'dark'
          ? 'bg-slate-900/90 border-white/15'
          : 'bg-white/90 border-black/10'"
      >
        <!-- 顶部色条 -->
        <div
          class="h-1.5 w-full"
          :class="urgencyClass"
        ></div>

        <!-- 内容 -->
        <div class="p-5">
          <!-- 婉晴头像 + 文案 -->
          <div class="flex items-start gap-4 mb-5">
            <div class="w-11 h-11 rounded-full overflow-hidden border-2 flex-shrink-0" :class="theme === 'dark' ? 'border-cyan-500/50' : 'border-cyan-500/30'">
              <img src="/portraits/ai_avatar.png" class="w-full h-full object-cover" alt="婉晴" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-bold" :class="theme === 'dark' ? 'text-slate-200' : 'text-slate-800'">婉晴</span>
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium" :class="urgencyBadgeClass">
                  {{ urgencyLabel }}
                </span>
              </div>
              <p class="text-sm leading-relaxed" :class="theme === 'dark' ? 'text-slate-300' : 'text-slate-600'">
                {{ message }}
              </p>
            </div>
          </div>

          <!-- 按钮组 -->
          <div class="flex gap-3">
            <button
              @click="handleAccepted"
              class="flex-1 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all duration-200 active:scale-95 hover:scale-[1.02]"
              :class="theme === 'dark'
                ? 'bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-600/25'
                : 'bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-600/20'"
            >
              好的，谢谢你
            </button>
            <button
              @click="handleRejected"
              class="flex-1 py-2.5 px-4 rounded-xl text-sm font-medium transition-all duration-200 active:scale-95"
              :class="theme === 'dark'
                ? 'bg-white/8 hover:bg-white/15 text-slate-400 border border-white/10'
                : 'bg-black/5 hover:bg-black/10 text-slate-500 border border-black/10'"
            >
              算了，不需要
            </button>
          </div>
        </div>

        <!-- 底部进度条（倒计时） -->
        <div class="h-0.5 w-full" :class="theme === 'dark' ? 'bg-white/5' : 'bg-black/5'">
          <div
            class="h-full transition-all duration-[100ms] linear"
            :class="urgencyBarClass"
            :style="{ width: `${countdownPercent}%` }"
          ></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  message: { type: String, default: '婉晴感受到你可能心情有些不好，需要聊聊吗？' },
  urgency: { type: String, default: 'low' }, // 'low' | 'medium' | 'high'
  autoDismissSeconds: { type: Number, default: 10 },
  theme: { type: String, default: 'dark' }
})

const emit = defineEmits(['accepted', 'rejected', 'dismissed'])

// ── 倒计时 ──────────────────────────────────────────────────────────────────
const countdownSeconds = ref(props.autoDismissSeconds)
let timer = null

watch(() => props.visible, (val) => {
  if (val) {
    countdownSeconds.value = props.autoDismissSeconds
    timer = setInterval(() => {
      countdownSeconds.value -= 0.1
      if (countdownSeconds.value <= 0) {
        clearInterval(timer)
        emit('dismissed', 'ignored')
      }
    }, 100)
  } else {
    clearInterval(timer)
  }
})

const countdownPercent = computed(() =>
  Math.max(0, (countdownSeconds.value / props.autoDismissSeconds) * 100)
)

onUnmounted(() => clearInterval(timer))

// ── 样式映射 ────────────────────────────────────────────────────────────────
const urgencyConfig = {
  low: {
    bar: 'bg-cyan-500',
    badge: theme => theme === 'dark'
      ? 'bg-cyan-500/15 text-cyan-400'
      : 'bg-cyan-50 text-cyan-600',
    badgeText: '轻微关怀',
    label: '轻微关怀'
  },
  medium: {
    bar: 'bg-amber-500',
    badge: theme => theme === 'dark'
      ? 'bg-amber-500/15 text-amber-400'
      : 'bg-amber-50 text-amber-600',
    badgeText: '建议聊聊',
    label: '婉晴建议聊聊'
  },
  high: {
    bar: 'bg-rose-500',
    badge: theme => theme === 'dark'
      ? 'bg-rose-500/15 text-rose-400'
      : 'bg-rose-50 text-rose-600',
    badgeText: '关心您',
    label: '婉晴很担心你'
  }
}

const urgencyClass = computed(() => urgencyConfig[props.urgency]?.bar || urgencyConfig.low.bar)
const urgencyBarClass = computed(() => urgencyConfig[props.urgency]?.bar || urgencyConfig.low.bar)
const urgencyBadgeClass = computed(() => urgencyConfig[props.urgency]?.badge(props.theme))
const urgencyLabel = computed(() => urgencyConfig[props.urgency]?.label || '婉晴关怀')

// ── 按钮响应 ────────────────────────────────────────────────────────────────
const handleAccepted = () => { emit('accepted') }
const handleRejected = () => { emit('rejected') }
</script>

<style scoped>
/* 弹出动画 */
.popup-enter-active { transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1); }
.popup-leave-active { transition: all 0.25s ease-in; }
.popup-enter-from { opacity: 0; transform: translateY(16px) scale(0.97); }
.popup-leave-to { opacity: 0; transform: translateY(8px) scale(0.97); }
</style>
