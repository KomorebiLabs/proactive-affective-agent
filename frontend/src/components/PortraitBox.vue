<template>
  <div
    ref="portraitCardRef"
    class="flex-1 relative rounded-3xl border backdrop-blur-sm overflow-hidden flex items-center justify-center group transition-all duration-500 relative"
    :class="theme === 'dark'
      ? 'border-white/10 bg-white/[0.03] shadow-lg shadow-black/20'
      : 'border-black/5 bg-white/70 shadow-lg shadow-black/10'"
    style="will-change: transform;"
  >
    <!-- 边框光晕效果 -->
    <div class="absolute inset-0 rounded-3xl border border-white/5 pointer-events-none"></div>

    <!-- 顶部渐变装饰 -->
    <div class="absolute top-0 left-0 right-0 h-20 bg-gradient-to-b from-white/5 to-transparent pointer-events-none"></div>

    <img
      ref="imgRef"
      :src="portraitPath"
      class="h-[92%] object-contain transition-all duration-500 relative z-10"
      :class="theme === 'dark' ? 'drop-shadow-[0_0_30px_rgba(255,255,255,0.15)]' : 'drop-shadow-[0_0_20px_rgba(0,0,0,0.15)]'"
      style="-webkit-mask-image: linear-gradient(to bottom, black 75%, transparent 100%); mask-image: linear-gradient(to bottom, black 75%, transparent 100%);"
      alt="Role Portrait"
    />

    <!-- 状态标签 -->
    <div class="absolute top-4 left-4 px-4 py-2.5 rounded-2xl backdrop-blur-xl flex flex-col gap-2 shadow-xl border transition-all duration-500 text-xs z-20"
      :class="theme === 'dark'
        ? 'bg-black/50 border-white/10 text-white/80'
        : 'bg-white/80 border-black/5 text-slate-700'"
    >
      <div class="flex items-center gap-2.5">
        <div class="w-2 h-2 rounded-full bg-gradient-to-br from-cyan-400 to-emerald-400 shadow-lg shadow-cyan-400/50"></div>
        <span class="font-medium">状态: {{ emotion }}</span>
      </div>
      <div class="flex items-center gap-2.5">
        <div class="w-2 h-2 rounded-full" :class="theme === 'dark' ? 'bg-slate-500' : 'bg-slate-400'"></div>
        <span class="text-[11px]" :class="theme === 'dark' ? 'text-slate-400' : 'text-slate-500'">行为: {{ behavior }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import gsap from 'gsap'

const props = defineProps({
  portraitPath: {
    type: String,
    required: true
  },
  emotion: String,
  behavior: String,
  intensity: {
    type: Number,
    default: 0.2
  },
  theme: {
    type: String,
    default: 'dark'
  }
})

const portraitCardRef = ref(null)
const imgRef = ref(null)

// 立绘平滑切换效果
watch(() => props.portraitPath, (newVal) => {
  if (!imgRef.value) return
  
  // 先淡出并稍微缩小
  gsap.to(imgRef.value, {
    duration: 0.3,
    opacity: 0,
    scale: 0.95,
    ease: 'power2.in',
    onComplete: () => {
      // 这里的 props.portraitPath 已经因为 Vue 的响应式变了
      // 直接淡入并恢复大小
      gsap.to(imgRef.value, {
        duration: 0.6,
        opacity: 1,
        scale: 1,
        ease: 'back.out(1.4)'
      })
    }
  })
})

// 柔性悬浮动画 BreathMotion
const applyBreathMotion = () => {
  if (!portraitCardRef.value) return
  
  gsap.killTweensOf(portraitCardRef.value)
  
  const t = props.intensity
  const floatDuration = 4.0 - (t * 2.0)
  const floatY = 4 + (t * 8)
  
  gsap.to(portraitCardRef.value, {
    duration: Math.max(0.5, floatDuration),
    y: -floatY,
    yoyo: true,
    repeat: -1,
    ease: 'sine.inOut'
  })
}

watch(() => props.intensity, () => {
  applyBreathMotion()
})

onMounted(() => {
  applyBreathMotion()
})

onUnmounted(() => {
  if (portraitCardRef.value) {
    gsap.killTweensOf(portraitCardRef.value)
  }
})
</script>
