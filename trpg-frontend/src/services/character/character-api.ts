import { useRoomStore } from '@/stores/room-store';
import { sdk } from '../api-client';

// 真实建卡流程对接：POST 建草稿 → PATCH 填数据 → POST complete 完成。
// 属性键位后端用大写（STR/CON/...），前端本地用小写，这里做一次转换。

export interface BuiltCharacter {
  name: string;
  attr: Record<string, number>; // 小写 key，如 { str: 50, con: 60, ... }
  derived: { hp: number; san: number; mp: number };
  skillValues: Record<string, number>; // skillId -> 最终值（base+分配）
  equipment: string;
  occupationName: string | null;
  background: string;
  notes: string;
}

// 属性键位后端用大写（STR/CON/...），前端本地用小写——建卡向导调
// previewCharacter 时也要做同样的转换，这里导出复用，不要在别处重复实现。
export function toUpperAttrs(attr: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(attr)) {
    out[k.toUpperCase()] = v;
  }
  return out;
}

// 建卡接口跟房间模块一样，靠 X-Reconnect-Token 确认"你是这个房间里的哪个玩家"。
function requireReconnectToken(): string {
  const token = useRoomStore.getState().reconnectToken;
  if (!token) throw new Error('缺少房间重连凭证，请重新加入房间');
  return token;
}

export async function createCharacterDraft(roomId: string): Promise<string> {
  const res = await sdk.characters.createDraft(roomId, requireReconnectToken());
  return res.characterId;
}

export async function saveCharacter(
  roomId: string,
  characterId: string,
  built: BuiltCharacter
): Promise<void> {
  await sdk.characters.save(
    roomId,
    characterId,
    {
      name: built.name,
      attributes: toUpperAttrs(built.attr),
      derivedStats: { HP: built.derived.hp, SAN: built.derived.san, MP: built.derived.mp },
      skills: built.skillValues,
      equipment: built.equipment
        ? built.equipment
            .split(/[,，\n]/)
            .map((s) => s.trim())
            .filter(Boolean)
            .map((name) => ({ name }))
        : [],
      occupation: built.occupationName,
      background: built.background,
      notes: built.notes
    },
    requireReconnectToken()
  );
}

export async function completeCharacter(roomId: string, characterId: string): Promise<void> {
  await sdk.characters.complete(roomId, characterId, requireReconnectToken());
}
