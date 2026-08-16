<template>
  <div
    ref="featuresCardRef"
    class="rounded-3xl border backdrop-blur-xl flex flex-col overflow-hidden relative shadow-xl transition-all duration-500 relative"
    :class="[
      theme === 'dark'
        ? 'border-white/10 bg-white/[0.03] shadow-black/30'
        : 'border-black/5 bg-white/80 shadow-black/10',
      isExpanded ? 'h-64' : 'h-16'
    ]"
    style="will-change: transform;"
  >
    <!-- 收起时：提示文字 + 展开图标 -->
    <div
      v-if="!isExpanded"
      @click="isExpanded = true"
      class="flex-1 flex flex-col items-center justify-center gap-3 cursor-pointer select-none group px-6"
    >
      <div class="flex items-center gap-4 w-full">
        <!-- 展开图标 -->
        <div class="w-10 h-10 rounded-full border-2 flex items-center justify-center flex-shrink-0 transition-all duration-300 group-hover:border-cyan-400/50 group-hover:bg-cyan-500/10 group-hover:shadow-lg group-hover:shadow-cyan-500/20"
          :class="theme === 'dark' ? 'border-white/20 bg-white/5' : 'border-black/10 bg-white/50'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 transition-colors duration-300" :class="theme === 'dark' ? 'text-slate-400 group-hover:text-cyan-400' : 'text-slate-500 group-hover:text-cyan-600'" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        </div>
        <span class="text-xs tracking-wide transition-colors duration-300" :class="theme === 'dark' ? 'text-slate-500 group-hover:text-slate-300' : 'text-slate-400 group-hover:text-slate-600'">
          AI感知到的情绪倾向
        </span>
        <div class="ml-auto flex gap-1.5 backdrop-blur-xl rounded-xl px-3 py-1.5 border"
          :class="theme === 'dark' ? 'bg-black/40 border-white/10' : 'bg-white/60 border-black/5'">
          <button @click.stop="internalMode = 'radar'; isExpanded = true" class="px-3 py-1 text-[10px] uppercase font-bold tracking-wider rounded-lg transition-all duration-300" :class="internalMode === 'radar' ? 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-white shadow-lg shadow-cyan-500/30' : 'text-slate-500 hover:text-slate-300'">情感雷达</button>
          <button @click.stop="internalMode = 'camera'; isExpanded = true" class="px-3 py-1 text-[10px] uppercase font-bold tracking-wider rounded-lg transition-all duration-300" :class="internalMode === 'camera' ? 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-white shadow-lg shadow-cyan-500/30' : 'text-slate-500 hover:text-slate-300'">视觉信号</button>
        </div>
      </div>
    </div>

    <!-- 展开时 -->
    <template v-else>
      <!-- 切换按钮 -->
      <div class="absolute top-3 right-3 flex gap-1.5 backdrop-blur-xl rounded-xl px-2 py-1.5 z-20 border"
        :class="theme === 'dark' ? 'bg-black/50 border-white/10' : 'bg-white/80 border-black/5'">
        <button @click="internalMode = 'radar'" class="px-3 py-1 text-[10px] uppercase font-bold tracking-wider rounded-lg transition-all duration-300" :class="internalMode === 'radar' ? 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-white shadow-lg shadow-cyan-500/30' : 'text-slate-500 hover:text-slate-300'">情感雷达</button>
        <button @click="internalMode = 'camera'" class="px-3 py-1 text-[10px] uppercase font-bold tracking-wider rounded-lg transition-all duration-300" :class="internalMode === 'camera' ? 'bg-gradient-to-r from-cyan-500 to-emerald-500 text-white shadow-lg shadow-cyan-500/30' : 'text-slate-500 hover:text-slate-300'">视觉信号</button>
        <!-- 收起按钮 -->
        <button @click="isExpanded = false" class="ml-1 px-2 py-1 text-[10px] uppercase font-bold tracking-wider rounded-lg transition-all duration-300" :class="theme === 'dark' ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600'">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" />
          </svg>
        </button>
      </div>

      <!-- 雷达图 -->
      <EmotionRadar
        v-show="internalMode === 'radar'"
        ref="radarComponent"
        :vector="radarVector"
        :theme="theme"
      />

      <!-- 摄像头 -->
      <div v-show="internalMode === 'camera'" class="flex-1 bg-black flex items-center justify-center relative w-full h-full overflow-hidden">
        <img v-if="videoFrame" :src="videoFrame" class="w-full h-full object-cover opacity-90" />
        <div v-else class="text-slate-600 text-[10px] tracking-[0.3em] uppercase animate-pulse font-medium">WAITING FOR SIGNAL...</div>
        <div class="absolute inset-0 bg-gradient-to-b from-transparent via-cyan-500/5 to-transparent h-full w-full animate-vignette pointer-events-none"></div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import EmotionRadar from './EmotionRadar.vue'
import gsap from 'gsap'

const props = defineProps({
  radarVector: Array,
  videoFrame: String,
  intensity: {
    type: Number,
    default: 0.2
  },
  theme: {
    type: String,
    default: 'dark'
  }
})

const isExpanded = ref(false)
const internalMode = ref('radar')
const featuresCardRef = ref(null)
const radarComponent = ref(null)

// 呼吸浮动动画（仅在展开时生效）
const applyBreathMotion = () => {
  if (!featuresCardRef.value || !isExpanded.value) return
  gsap.killTweensOf(featuresCardRef.value)

  const t = props.intensity
  const floatDuration = 4.0 - (t * 2.0)
  const floatY = 4 + (t * 8)

  gsap.to(featuresCardRef.value, {
    duration: Math.max(0.5, floatDuration),
    y: -floatY,
    yoyo: true,
    repeat: -1,
    ease: 'sine.inOut',
    delay: 0.5
  })
}

watch(() => props.intensity, () => {
  applyBreathMotion()
})

watch(isExpanded, (val) => {
  if (val) {
    nextTick(() => {
      applyBreathMotion()
      if (internalMode.value === 'radar') {
        setTimeout(() => radarComponent.value?.resize(), 50)
      }
    })
  } else {
    gsap.killTweensOf(featuresCardRef.value)
  }
})

// 当切换回雷达图时重绘
watch(internalMode, (newVal) => {
  if (newVal === 'radar' && isExpanded.value) {
    setTimeout(() => {
      radarComponent.value?.resize()
    }, 50)
  }
})

onMounted(() => {
  // 默认收起，不启动动画
})

onUnmounted(() => {
  if (featuresCardRef.value) {
    gsap.killTweensOf(featuresCardRef.value)
  }
})
</script>

<style scoped>
@keyframes sweep {
  0% { transform: translateY(-100%); }
  100% { transform: translateY(100%); }
}
.animate-vignette {
  animation: sweep 3s linear infinite;
}
</style>
