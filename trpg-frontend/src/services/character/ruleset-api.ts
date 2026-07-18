import type { CharacterComputeResult, PreviewCharacterInput, Ruleset } from 'trpg-sdk';
import { ApiError, friendlyErrorMessage, getAuthToken, sdk } from '../api-client';

// 建卡规则数据/计算全部改由后端权威提供（issue #84 S3，路线乙）：职业/技能/
// 属性目录来自 `GET /systems/{systemId}/ruleset`，衍生值/技能点预算/校验
// 报告来自 `POST /systems/{systemId}/character/preview`，前端不再本地存一份
// 规则数据、也不再本地重算 COC7 数值。

// ── systemId 解析 ──────────────────────────────────────────────────────
// 目前 `RoomPreview`/`ModuleRead` 等既有接口都没有把房间实际绑定的
// GameSystem id 带回前端（见 trpg-backend app/service/room.py
// `room.system_id = scenario.game_system_id`，只落库不对外返回），而前端本地
// config/games.ts 里的 'coc'/'dnd' 只是展示用字符串、并非后端真实的
// GameSystem UUID。当前后端只有一个内置游戏大类 + 一个内置 COC7 规则系统
// （见 trpg-backend app/core/seed.py 的种子数据），所以取 `GET /games` +
// `GET /games/{gameId}/systems` 目录的第一项即可稳定拿到正确的 systemId；
// 以后如果要支持多规则系统，需要后端把 systemId 补进房间/模组相关接口，
// 这里再改成读那个字段（本期不改后端/SDK，见 issue #84 S3 范围）。
let systemIdPromise: Promise<string> | null = null;

export function resolveSystemId(): Promise<string> {
  if (!systemIdPromise) {
    systemIdPromise = (async () => {
      const games = await sdk.games.list();
      if (games.length === 0) throw new Error('没有可用的游戏大类');
      const systems = await sdk.games.listSystems(games[0].id);
      if (systems.length === 0) throw new Error('没有可用的规则系统');
      return systems[0].id;
    })().catch((err) => {
      systemIdPromise = null; // 失败不缓存，允许下次重试
      throw err;
    });
  }
  return systemIdPromise;
}

// ── 规则目录（职业/技能/属性），静态数据，会话内只需要拿一次 ──────────
let rulesetPromise: Promise<Ruleset> | null = null;

export function getRuleset(): Promise<Ruleset> {
  if (!rulesetPromise) {
    rulesetPromise = resolveSystemId()
      .then((systemId) => sdk.games.getRuleset(systemId))
      .catch((err) => {
        rulesetPromise = null;
        throw err;
      });
  }
  return rulesetPromise;
}

// ── 建卡计算预览：衍生值/技能点预算/base·cap/校验报告，全部后端权威算出 ──
export async function previewCharacter(payload: PreviewCharacterInput): Promise<CharacterComputeResult> {
  const token = getAuthToken();
  if (!token) throw new Error('未登录，无法预览建卡计算');
  const systemId = await resolveSystemId();
  return sdk.games.previewCharacter(systemId, payload, token);
}

// ── 把 complete() 422 返回的结构化建卡校验错误翻译成人话 ──────────────
// `CharacterInvalidError` 的 message 形如
// "角色卡未通过校验：[SKILL_ABOVE_CAP] 聆听 的值 105 超过上限 99；[...] ..."
// （见 trpg-backend app/service/character.py），这里去掉方括号里的机器码，
// 只把给人看的说明拼起来展示。
export function translateCharacterValidationError(err: unknown): string {
  if (err instanceof ApiError && err.code === 'CHARACTER_INVALID') {
    const body = err.message.replace(/^角色卡未通过校验：/, '');
    const items = body
      .split('；')
      .map((s) => s.replace(/^\[[^\]]+\]\s*/, '').trim())
      .filter(Boolean);
    if (items.length > 0) return items.join('；');
  }
  return friendlyErrorMessage(err, '建卡失败');
}
