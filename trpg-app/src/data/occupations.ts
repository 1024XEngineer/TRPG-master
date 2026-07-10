import occupationData from './generated/coc7-occupations.json'

export type AttributeKey = 'str' | 'con' | 'pow' | 'dex' | 'app' | 'siz' | 'int' | 'edu' | 'luck'

export interface OccupationPointTerm {
  attr: AttributeKey
  multiplier: number
}

export type OccupationPointFormula =
  | { kind: 'fixed'; attr: AttributeKey; multiplier: number; raw: string }
  | { kind: 'sum'; terms: OccupationPointTerm[]; raw: string }
  | { kind: 'choice'; base: OccupationPointTerm; options: AttributeKey[]; optionMultiplier: number; raw: string }
  | { kind: 'unknown'; raw: string }

export interface OccupationSkillRule {
  kind: 'matrix'
  skillId: string
  label: string
  marker: string
  source: {
    sheet: string
    row: number
    column: number
  }
}

export interface OccupationDefinition {
  id: number
  excelNo: number
  name: string
  aliases: string[]
  creditRange: string | null
  credit: { min: number; max: number } | null
  /** Skill points formula for occupation skills, kept as source-display text. */
  skillPoints: string
  pointFormula: OccupationPointFormula
  category: string
  icon: string
  /** IDs of mapped skills this occupation provides. Full original text remains in skillsText. */
  skillIds: string[]
  skillRules: OccupationSkillRule[]
  skillsText: string
  contacts: string | null
  description: string | null
  sourceNote: string | null
  shortDesc: string
  source: {
    workbook: string
    sheet: string
    row: number
  }
}

export interface OccupationGroup {
  label: string
  icon: string
  ids: number[]
}

interface OccupationDataFile {
  metadata: {
    sourceWorkbook: string
    sourceSheet: string
    skillMatrixSheet: string
    recordCount: number
  }
  occupations: OccupationDefinition[]
}

const typedOccupationData = occupationData as OccupationDataFile

export const OCCUPATION_DATA_METADATA = typedOccupationData.metadata
export const ALL_OCCUPATIONS: OccupationDefinition[] = typedOccupationData.occupations

const GROUP_DEFINITIONS: Array<{ label: string; icon: string }> = [
  { label: '学术研究', icon: '📚' },
  { label: '执法安全', icon: '🔒' },
  { label: '文化艺术', icon: '🎨' },
  { label: '医疗保健', icon: '🏥' },
  { label: '法律金融', icon: '⚖️' },
  { label: '社交服务', icon: '🤝' },
  { label: '野外生存', icon: '🏔️' },
  { label: '社会边缘', icon: '🎭' },
  { label: '专业人员', icon: '🔧' },
  { label: '其他职业', icon: '🗂️' },
]

export const OCCUPATION_GROUPS: OccupationGroup[] = GROUP_DEFINITIONS.map(group => ({
  label: group.label,
  icon: group.icon,
  ids: ALL_OCCUPATIONS
    .filter(occupation => occupation.category === group.label)
    .map(occupation => occupation.id),
})).filter(group => group.ids.length > 0)

export function getOccupationById(id: number): OccupationDefinition | undefined {
  return ALL_OCCUPATIONS.find(occupation => occupation.id === id)
}
