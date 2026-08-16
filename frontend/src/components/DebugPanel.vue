<template>
  <div class="absolute bottom-6 left-6 z-50 p-4 rounded-xl bg-black/70 backdrop-blur-md border border-white/10 flex flex-col gap-5 shadow-2xl w-64 transition-all hover:scale-[1.02] active:scale-100">
    <div class="text-[10px] text-slate-500 font-mono flex justify-between tracking-[0.2em] border-b border-white/5 pb-2">
      <span class="font-bold">SYSTEM DEBUG</span>
      <span class="text-cyan-400 font-semibold animate-pulse uppercase">Active</span>
    </div>
    
    <!-- 情绪选择 -->
    <div class="flex flex-col gap-2">
      <label class="text-[9px] text-slate-500 uppercase font-black tracking-widest pl-1">Emotion Preset</label>
      <select 
        :value="emotionType" 
        @change="$emit('update:emotionType', $event.target.value)"
        class="bg-white/5 border border-white/10 rounded-lg text-xs text-slate-300 p-2.5 focus:border-cyan-500 transition-all focus:ring-1 focus:ring-cyan-500/20 cursor-pointer outline-none w-full appearance-none hover:bg-white/10"
      >
        <option value="neutral" class="bg-slate-900 px-2 py-1">NEUTRAL / 平静</option>
        <option value="positive_joy" class="bg-slate-900">JOY / 喜悦</option>
        <option value="negative_anger" class="bg-slate-900">ANGER / 愤怒</option>
        <option value="negative_sad" class="bg-slate-900">SADNESS / 悲伤</option>
      </select>
    </div>

    <!-- 强度控制 -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center px-1">
        <label class="text-[9px] text-slate-500 uppercase font-black tracking-widest">Intensity</label>
        <span class="text-[10px] text-cyan-400 font-mono bg-cyan-400/10 px-2 py-0.5 rounded border border-cyan-400/20">{{ intensity.toFixed(2) }}</span>
      </div>
      <div class="relative group px-1">
        <input 
          type="range" 
          :value="intensity" 
          @input="$emit('update:intensity', parseFloat($event.target.value))"
          min="0" max="1" step="0.01" 
          class="accent-cyan-500 cursor-pointer h-1.5 bg-white/10 rounded-lg appearance-none w-full outline-none opacity-80 group-hover:opacity-100 transition-opacity" 
        />
      </div>
    </div>

    <!-- 连接状态 -->
    <div class="flex items-center justify-between text-[10px] mt-1 pt-2 border-t border-white/5 px-1">
      <span class="text-slate-500 tracking-wider">NETWORK</span>
      <span class="px-2 py-0.5 rounded-full font-bold shadow-sm" :class="isConnected ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-500'">{{ isConnected ? 'CONNECTED' : 'OFFLINE' }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  emotionType: String,
  intensity: Number,
  isConnected: Boolean
})

defineEmits(['update:emotionType', 'update:intensity'])
</script>

<style scoped>
/* 自定义 Range 滑块样式，确保极致美观 */
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  height: 12px;
  width: 12px;
  border-radius: 50%;
  background: #22d3ee;
  box-shadow: 0 0 10px rgba(34, 211, 238, 0.5);
  cursor: pointer;
  border: 2px solid white;
}
</style>
