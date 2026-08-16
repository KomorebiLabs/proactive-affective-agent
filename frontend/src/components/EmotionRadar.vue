<template>
  <div ref="radarChartRef" class="flex-1 w-full h-full"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  vector: {
    type: Array,
    required: true
  },
  labels: {
    type: Array,
    default: () => ["喜悦", "悲伤", "愤怒", "恐惧", "厌恶", "惊讶", "踏实感", "期待"]
  },
  theme: {
    type: String,
    default: 'dark'
  }
})

let myChart = null
const radarChartRef = ref(null)

const axisColor = computed(() => props.theme === 'dark' ? '#94a3b8' : '#64748b')
const lineColor = computed(() => props.theme === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.15)')
const areaColor0 = computed(() => props.theme === 'dark' ? 'rgba(6,182,212,0.6)' : 'rgba(6,182,212,0.4)')
const areaColor1 = computed(() => props.theme === 'dark' ? 'rgba(6,182,212,0.1)' : 'rgba(6,182,212,0.05)')
const lineStyleColor = computed(() => props.theme === 'dark' ? '#06b6d4' : '#0891b2')
const splitLineColors = computed(() =>
  props.theme === 'dark'
    ? ['rgba(255,255,255,0.05)', 'rgba(255,255,255,0.1)']
    : ['rgba(0,0,0,0.04)', 'rgba(0,0,0,0.08)']
)

const initChart = () => {
  if (!radarChartRef.value) return
  myChart = echarts.init(radarChartRef.value)
  updateChartOption()

  window.addEventListener('resize', handleResize)
}

const handleResize = () => {
  if (myChart) {
    myChart.resize()
  }
}

const updateChartOption = () => {
  if (!myChart) return

  const option = {
    backgroundColor: 'transparent',
    radar: {
      center: ['50%', '55%'],
      radius: '65%',
      indicator: props.labels.map(name => ({
        name,
        max: 1,           // 归一化到 [0, 1] 范围
        axisLabel: { show: false }  // 隐藏刻度标签，避免对齐问题
      })),
      shape: 'circle',
      splitNumber: 4,
      axisName: { color: axisColor.value, fontSize: 10 },
      splitLine: { lineStyle: { color: splitLineColors.value } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: lineColor.value } }
    },
    series: [{
      type: 'radar',
      data: [{ value: props.vector }],
      symbol: 'none',
      lineStyle: { width: 2, color: lineStyleColor.value },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: areaColor0.value },
          { offset: 1, color: areaColor1.value }
        ])
      }
    }]
  }
  myChart.setOption(option)
}

watch(() => [props.vector, props.theme], () => {
  updateChartOption()
}, { deep: true })

onMounted(() => {
  initChart()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (myChart) {
    myChart.dispose()
  }
})

defineExpose({
  resize: handleResize
})
</script>