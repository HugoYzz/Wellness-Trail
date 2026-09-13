/** 记录域标签与枚举（与后端 app/schemas.py §2.3 对齐）。 */
export const TYPE_LABELS: Record<string, string> = {
  weight: '体重',
  sleep: '睡眠',
  meal: '餐食',
  sweet_drink: '奶茶/甜饮',
  night_hunger: '夜饿处理',
  exercise: '运动',
  step: '步数',
  waist: '腰围',
  supplement: '补剂',
  body: '身体不适',
  note: '备注',
}

export const SLOT_LABELS: Record<string, string> = {
  am: '晨重',
  evening: '夜重',
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
}

export const SWEET_LEVELS = ['0杯', '无糖', '三分糖', '半糖', '全糖'] as const
export const NIGHT_HUNGER_LEVELS = ['没饿', '加餐预案', '破戒'] as const
export const SUPPLEMENT_ITEMS = ['vitd3', 'zinc', 'copper'] as const
export const SUPPLEMENT_TIMINGS = ['早餐后', '晚餐后'] as const
export const BODY_SITES = ['腰', '踝', '肠胃'] as const

/** 单条记录的一句话摘要（时间线/卡片展示用）。 */
export function recordSummary(r: RecordItem): string {
  const f = (r.fields ?? {}) as Record<string, any>
  const s = (v: unknown): string => (v === undefined || v === null ? '' : String(v))
  switch (r.type) {
    case 'weight':
      return `${s(f.kg)}kg`
    case 'sleep':
      return `${s(f.bedtime)} 入睡`
    case 'meal':
      return s(f.desc)
    case 'sweet_drink':
      return f.desc ? `${s(f.level)}（${s(f.desc)}）` : s(f.level)
    case 'night_hunger':
      return f.desc ? `${s(f.level)}（${s(f.desc)}）` : `${s(f.level)}${r.raw_text ? `（${r.raw_text}）` : ''}`
    case 'exercise':
      return f.kind === 'swim' ? `游泳 ${s(f.duration_min)} 分钟` : f.done ? '力量训练 完成' : '力量训练 未做'
    case 'step':
      return `${s(f.steps)} 步`
    case 'waist':
      return `${s(f.cm)}cm`
    case 'supplement':
      return `${s(f.item)} ${s(f.dose)} · ${s(f.timing)} · ${f.taken ? '已服' : '未服'}`
    case 'body':
      return [s(f.site), f.level ? `${s(f.level)}/10` : '', s(f.symptom)].filter(Boolean).join(' ')
    case 'note':
      return s(f.text)
    default:
      return JSON.stringify(f)
  }
}

export interface RecordItem {
  id: number
  type: string
  date: string
  slot: string | null
  fields: Record<string, unknown>
  raw_text: string
  source: string
  confirmed: boolean
  created_at?: string
  warnings?: string[]
}
