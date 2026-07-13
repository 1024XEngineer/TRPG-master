import { apiRequest } from '../api-client'

// 真实建卡流程对接：POST 建草稿 → PATCH 填数据 → POST complete 完成。
// 属性键位后端用大写（STR/CON/...），前端本地用小写，这里做一次转换。

export interface BuiltCharacter {
  name: string
  attr: Record<string, number> // 小写 key，如 { str: 50, con: 60, ... }
  derived: { hp: number; san: number; mp: number }
  skillValues: Record<string, number> // skillId -> 最终值（base+分配）
  equipment: string
  occupationName: string | null
  background: string
  notes: string
}

function toUpperAttrs(attr: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(attr)) {
    out[k.toUpperCase()] = v
  }
  return out
}

export async function createCharacterDraft(roomId: string): Promise<string> {
  const res = await apiRequest<{ characterId: string; status: string }>(`/rooms/${roomId}/characters`, {
    method: 'POST',
    body: {},
  })
  return res.characterId
}

export async function saveCharacter(roomId: string, characterId: string, built: BuiltCharacter): Promise<void> {
  await apiRequest(`/rooms/${roomId}/characters/${characterId}`, {
    method: 'PATCH',
    body: {
      name: built.name,
      attributes: toUpperAttrs(built.attr),
      derivedStats: { HP: built.derived.hp, SAN: built.derived.san, MP: built.derived.mp },
      skills: built.skillValues,
      equipment: built.equipment
        ? built.equipment.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean).map((name) => ({ name }))
        : [],
      occupation: built.occupationName,
      background: built.background,
      notes: built.notes,
    },
  })
}

export async function completeCharacter(roomId: string, characterId: string): Promise<void> {
  await apiRequest(`/rooms/${roomId}/characters/${characterId}/complete`, { method: 'POST' })
}
