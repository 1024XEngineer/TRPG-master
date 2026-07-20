/** 调查员基本信息 */
export interface InvestigatorInfo {
  name: string
  playerName: string
  age: string
  gender: string
  residence: string
  birthplace: string
  occupationId: number | null
}

/** 8 项基础属性 + 幸运（幸运独立掷骰，不参与点数购买，见 ATTRIBUTE_DEFAULTS） */
export interface Attributes {
  str: number // 力量
  con: number // 体质
  pow: number // 意志
  dex: number // 敏捷
  app: number // 外貌
  siz: number // 体型
  int: number // 智力
  edu: number // 教育
  luck: number // 幸运
  // 索引签名：允许 Attributes 直接传给 Record<string, number> 形参
  // （建卡 PATCH 请求体/previewCharacter 都是这么用的），不用每处再转换。
  [key: string]: number
}

// 基础属性默认值 (CoC7标准: 3d6×5 = 平均50)。
// 幸运（luck）跟其余 8 项不同：COC7 里它只能掷（3d6*5），不能用属性点数购买，
// 所以它不在建卡页的点数购买网格（ATTR_KEYS）与总点数预算里，这里给同样的
// 平均值 50 作默认，真实掷骰由服务端权威的 roll-attributes 端点产出。
export const ATTRIBUTE_DEFAULTS: Attributes = {
  str: 50, con: 50, pow: 50, dex: 50,
  app: 50, siz: 50, int: 50, edu: 50,
  luck: 50,
}

// 纯展示用的中文标签映射，不是规则数据——后端 AttributeSpec 也带了 label，
// 但这里额外要一个更短的 short 缩写（STR/CON/...）用于紧凑排版，保留在
// 前端本地（issue #84 S3：属性生成公式等规则数据交给后端，展示文案不用）。
export const ATTRIBUTE_LABELS: Record<keyof Attributes, { short: string; full: string }> = {
  str: { short: 'STR', full: '力量' },
  con: { short: 'CON', full: '体质' },
  pow: { short: 'POW', full: '意志' },
  dex: { short: 'DEX', full: '敏捷' },
  app: { short: 'APP', full: '外貌' },
  siz: { short: 'SIZ', full: '体型' },
  int: { short: 'INT', full: '智力' },
  edu: { short: 'EDU', full: '教育' },
  luck: { short: 'LUCK', full: '幸运' },
}
