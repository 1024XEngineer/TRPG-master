import { useRoomStore } from '@/stores/room-store';
import { sdk } from '../api-client';

// 真实建卡流程对接：POST 建草稿 → PATCH 填数据 → POST complete 完成。

export interface BuiltCharacter {
  name: string;
  attr: Record<string, number>; // 后端属性键，如 { STR: 50, CON: 60, ... }
  derived: { hp: number; san: number; mp: number };
  skillValues: Record<string, number>; // skillId -> 最终值（base+分配）
  equipment: string;
  occupationName: string | null;
  background: string;
  notes: string;
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
      attributes: built.attr,
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

/**
 * 从后端读回一张已保存的角色卡（issue #96）。
 *
 * 后端是角色卡的唯一事实来源。此前前端把整张卡存在 localStorage 里当权威源，
 * 那份副本的结构会随后端 schema 演进而过期——PR #88 给属性加了幸运之后，本地
 * 存的 8 键旧卡再打开就被后端的 9 键校验拒了，玩家的卡直接编辑不了。
 */
export async function fetchCharacter(roomId: string, characterId: string) {
  return sdk.characters.get(roomId, characterId, requireReconnectToken());
}

export async function completeCharacter(roomId: string, characterId: string): Promise<void> {
  await sdk.characters.complete(roomId, characterId, requireReconnectToken());
}
