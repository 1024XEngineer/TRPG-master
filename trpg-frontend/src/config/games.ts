/**
 * 当前产品固定运行“跑团 + COC7”，用户只需要选择模组。
 *
 * systemId 对应后端 app/core/seed.py 的 BUILTIN_SYSTEM_ID。后端使用固定 UUID
 * 幂等写入内置规则系统，因此前端可以把它作为产品配置集中维护；不要把这个值
 * 再散落到页面、store 或测试里。
 */
export const FIXED_TRPG = {
  gameId: 'trpg',
  gameName: '跑团',
  systemId: '00000000-0000-0000-0000-000000000002',
  systemName: '克苏鲁的呼唤 7th（COC7）',
  systemCatalogName: 'COC7',
} as const

export const COC7_SYSTEM_COLORS = {
  iconBg: 'bg-[#f3eef8]',
  iconColor: 'text-[#7050a0]',
} as const
