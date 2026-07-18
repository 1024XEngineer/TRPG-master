import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { Attributes, InvestigatorInfo } from '@/data/character-model'

export interface CompletedCharacter {
  info: InvestigatorInfo
  attr: Attributes
  skillAlloc: Record<string, number>
  // 全部技能的最终值（skillId -> 已经算好的 base+分配，来自建卡完成时后端
  // previewCharacter 返回的权威计算结果），人物卡准备页/游戏内技能面板直接
  // 渲染这份数据，不用再拿 skillAlloc 现场重算（issue #84 S3：规则计算全部
  // 交给后端，前端只存/渲染结果）。
  skillFinalValues: Record<string, number>
  equipment: string
  background: string
  notes: string
  derived: { hp: number; san: number; mp: number; db: string; move: number }
}

interface CharacterState {
  character: CompletedCharacter | null
  // 这份角色数据属于哪个房间——见下面的 getForRoom，读取时要核对这个字段，
  // 不能假设 localStorage 里存的就是当前房间的角色。
  roomId: string | null
  setCharacter: (c: CompletedCharacter, roomId: string) => void
  getForRoom: (roomId: string) => CompletedCharacter | null
  clear: () => void
}

// ★ 之前只存在内存里，换个浏览器 tab（比如从「我的游戏」继续一局早前建过卡
// 的房间）角色数据就丢了，聊天室的"角色卡/技能"面板会看起来是空的——不是没
// 建过卡，是本地状态没了。持久化到 localStorage 解决同浏览器下的这类场景
// （换浏览器/清缓存仍然会丢，因为这份数据从来没真的存过后端，见 mock-db 里
// MockCharacter 只存了 draft/complete 状态、没存真实建卡内容）。
//
// ★ 只存一份角色、不按房间区分曾经导致真实 bug：同一浏览器加入/恢复另一个
// 房间时，会展示上一个房间的角色卡；换账号登录也会继承上一个用户的数据
// （见 PR #67 review）。现在额外存一个 roomId，读取时用 getForRoom 核对，
// 房间对不上就当作没建过卡，而不是直接把 character 暴露出去。
export const useCharacterStore = create<CharacterState>()(
  persist(
    (set, get) => ({
      character: null,
      roomId: null,
      setCharacter: (character, roomId) => set({ character, roomId }),
      getForRoom: (roomId) => (get().roomId === roomId ? get().character : null),
      clear: () => set({ character: null, roomId: null }),
    }),
    { name: 'aidm-character', storage: createJSONStorage(() => localStorage) }
  )
)
