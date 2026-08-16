// 情绪相关映射的单一事实源（App.vue / appStore.js 共用，禁止再各自复制一份）
//
// OCC_LABELS 顺序约束：
//   必须与 components/EmotionRadar.vue 的 labels、后端 occ_to_zh 映射顺序完全一致：
//   joy→喜悦, sadness→悲伤, anger→愤怒, fear→恐惧,
//   disgust→厌恶, surprise→惊讶, well_grounding→踏实感, anticipation→期待
export const OCC_LABELS = ['喜悦', '悲伤', '愤怒', '恐惧', '厌恶', '惊讶', '踏实感', '期待']

// OCC 向量最大值标签 → 立绘情绪
export const EMOTION_MAP = {
  '喜悦': '开心', '悲伤': '悲伤', '愤怒': '愤怒',
  '恐惧': '恐惧', '厌恶': '厌恶', '惊讶': '惊讶',
  '踏实感': '平静', '期待': '平静',
  '好奇': '好奇', '害羞': '害羞', '焦虑': '焦虑', '无奈': '无奈'
}

// Python ui_action.pulse → 前端光晕 intensity
export const PULSE_MAP = { slow: 0.2, medium: 0.5, fast: 0.8, very_fast: 0.95 }
