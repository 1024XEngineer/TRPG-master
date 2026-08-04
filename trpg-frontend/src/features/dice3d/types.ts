/**
 * 骰型定义。刻意不 import three——React 侧要能只引类型而不把 three 拖进首屏包。
 */

/** 本项目用到的骰型。D100 由两颗 D10 组成，几何上没有 d100。 */
export type DiceKind = 'd100' | 'd20' | 'd6'

/** 实际存在的多面体。 */
export type PolyhedronKind = 'd10' | 'd20' | 'd6'
