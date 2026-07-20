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

/** 8项基础属性 */
export interface Attributes {
  str: number // 力量
  con: number // 体质
  pow: number // 意志
  dex: number // 敏捷
  app: number // 外貌
  siz: number // 体型
  int: number // 智力
  edu: number // 教育
  // 索引签名：允许 Attributes 直接传给 Record<string, number> 形参
  // （建卡 PATCH 请求体/previewCharacter 都是这么用的），不用每处再转换。
  [key: string]: number
}

/** 基础属性默认值 (CoC7标准: 3d6×5 = 平均50) */
export const ATTRIBUTE_DEFAULTS: Attributes = {
  str: 50, con: 50, pow: 50, dex: 50,
  app: 50, siz: 50, int: 50, edu: 50,
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
}
