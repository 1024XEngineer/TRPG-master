// Re-export types from data modules for convenient imports
import type { Ruleset } from 'trpg-sdk'

export type { InvestigatorInfo, Attributes } from './character-model'
export type { Ruleset } from 'trpg-sdk'

// 职业/技能/属性目录的元素类型——后端 ruleset 已经导出了 `Ruleset`
// (`RulesetRead`) 这个整体类型，但 trpg-sdk 的公开类型里没有单独导出
// `OccupationSpec`/`SkillSpec`/`AttributeSpec`（见 trpg-sdk/src/types.ts），
// 用索引访问从 `Ruleset` 上取出元素类型，不需要改 SDK。
export type OccupationSpec = Ruleset['occupations'][number]
export type SkillSpec = Ruleset['skills'][number]
export type AttributeSpec = Ruleset['attributes'][number]
