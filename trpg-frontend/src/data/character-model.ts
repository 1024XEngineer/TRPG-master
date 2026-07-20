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

/**
 * 属性值表：键用后端 ruleset 里的属性键（`STR`/`CON`/…/`LUCK`），值是属性值。
 *
 * 这里刻意**不**枚举有哪些属性、也不带默认值和中文标签——那些全都是规则数据，
 * 由后端 `GET /systems/{systemId}/ruleset` 提供（issue #96）：
 * - 有哪些属性、哪些能用点数购买 → `ruleset.attributes` 的 `key` / `pointBuy`
 * - 中文名 → `AttributeSpec.label`（缩写直接用 `key`）
 * - 默认值 / 点数预算 / 单项上下限 → `ruleset.attributePointBuy`
 *
 * 此前这些在前端硬编码了好几份（三处属性键名单 + 标签表 + 默认值 + 480 和
 * [10,90]），加一项属性要改好几个地方，漏一处就静默出错——PR #88 加幸运时
 * 就漏了角色卡视图那处，导致建好的卡看不到幸运值。
 *
 * 键名也直接用后端的大写形式，不再前端小写、提交时转换一次：那层转换本身
 * 就是两套命名并存的产物，去掉之后少一类对不上的可能。
 */
export type Attributes = Record<string, number>
