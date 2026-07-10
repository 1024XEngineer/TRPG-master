import type { SkillDefinition } from './skills'
import { calculateBaseValue } from './skills'

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
}

/** 基础属性默认值 (CoC7标准: 3d6×5 = 平均50) */
export const ATTRIBUTE_DEFAULTS: Attributes = {
  str: 50, con: 50, pow: 50, dex: 50,
  app: 50, siz: 50, int: 50, edu: 50,
}

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

/** 根据属性值计算衍生值 */
export function deriveStats(attr: Attributes) {
  return {
    hp: Math.floor((attr.siz + attr.con) / 10),
    san: attr.pow,
    mp: Math.floor(attr.pow / 5),
    luck: attr.pow, // 幸运 = POW × 5, but displayed as POW
    damageBonus: calcDamageBonus(attr.str, attr.siz),
    build: calcBuild(attr.str, attr.siz),
    db: calcDamageBonus(attr.str, attr.siz),
    move: calcMove(attr.dex, attr.str, attr.siz),
  }
}

function calcDamageBonus(str: number, siz: number): string {
  const sum = str + siz
  if (sum <= 64) return '-2'
  if (sum <= 84) return '-1'
  if (sum <= 124) return '0'
  if (sum <= 164) return '+1D4'
  if (sum <= 204) return '+1D6'
  return '+1D8'
}

function calcBuild(str: number, siz: number): string {
  const sum = str + siz
  if (sum <= 64) return '-2'
  if (sum <= 84) return '-1'
  if (sum <= 124) return '0'
  if (sum <= 164) return '+1D4'
  if (sum <= 204) return '+1D6'
  return '+1D8'
}

function calcMove(dex: number, str: number, siz: number): number {
  const isSmall = str < siz && dex < siz
  const isLarge = str > siz && dex > siz
  if (isSmall) return 9
  if (isLarge) return 7
  return 8
}

/** 计算职业技能点数 (基于公式字符串) */
export function calculateOccupationSkillPoints(formula: string, attr: Attributes): number {
  const attrNames: Record<string, keyof Attributes> = {
    EDU: 'edu',
    STR: 'str',
    CON: 'con',
    POW: 'pow',
    DEX: 'dex',
    APP: 'app',
    SIZ: 'siz',
    INT: 'int',
    教育: 'edu',
    力量: 'str',
    体质: 'con',
    意志: 'pow',
    敏捷: 'dex',
    外貌: 'app',
    体型: 'siz',
    智力: 'int',
    幸运: 'pow',
  }

  const normalized = formula
    .replace(/＋/g, '+')
    .replace(/×/g, '*')
    .replace(/\s+/g, '')

  const fixed = normalized.match(/^([A-Z]+|[\u4e00-\u9fa5]+)\*(\d+)$/)
  if (fixed) {
    const key = attrNames[fixed[1]]
    if (key) return attr[key] * Number(fixed[2])
  }

  const eduPlus = normalized.match(/^(EDU|教育)\*2\+(.+)\*2$/)
  if (eduPlus) {
    const choices = eduPlus[2]
      .split('或')
      .map(name => attrNames[name])
      .filter((key): key is keyof Attributes => Boolean(key))

    if (choices.length > 0) {
      return attr.edu * 2 + Math.max(...choices.map(key => attr[key])) * 2
    }
  }

  return attr.edu * 4
}

/** 计算兴趣技能点数 = INT × 2 */
export function calculateInterestSkillPoints(attr: Attributes): number {
  return attr.int * 2
}

/** 技能的即时值（基数 + 已分配点数）*/
export function getSkillCurrentValue(skill: SkillDefinition, baseAllocation: number, attr: Attributes): number {
  const base = calculateBaseValue(skill, attr)
  return Math.min(99, base + baseAllocation)
}
