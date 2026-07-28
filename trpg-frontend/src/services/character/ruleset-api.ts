import type { CharacterComputeResult, PreviewCharacterInput, Ruleset } from 'trpg-sdk';
import { ApiError, friendlyErrorMessage, getAuthToken, sdk } from '../api-client';
import { useGameStore } from '@/stores/game-store';
import { useRoomStore } from '@/stores/room-store';

// 建卡规则数据/计算全部改由后端权威提供（issue #84 S3，路线乙）：职业/技能/
// 属性目录来自 `GET /systems/{systemId}/ruleset`，衍生值/技能点预算/校验
// 报告来自 `POST /systems/{systemId}/character/preview`，前端不再本地存一份
// 规则数据、也不再本地重算 COC7 数值。

// ── systemId 解析 ──────────────────────────────────────────────────────
// 新建流程优先使用用户从后端目录实际选择的 systemId；继续已有房间时通过
// Room.moduleId 读取后端 ModuleDetail.gameSystemId。仅旧会话缺少这两项时才
// 回退到目录第一项，兼容 #123 之前保存的状态。
let fallbackSystemIdPromise: Promise<string> | null = null;

export function resolveSystemId(): Promise<string> {
  const selectedSystemId = useGameStore.getState().systemId;
  if (selectedSystemId) return Promise.resolve(selectedSystemId);

  const moduleId = useRoomStore.getState().moduleId;
  if (moduleId) {
    return sdk.modules.getDetail(moduleId).then((module) => module.gameSystemId);
  }

  if (!fallbackSystemIdPromise) {
    fallbackSystemIdPromise = (async () => {
      const games = await sdk.games.list();
      if (games.length === 0) throw new Error('没有可用的游戏大类');
      const systems = await sdk.games.listSystems(games[0].id);
      if (systems.length === 0) throw new Error('没有可用的规则系统');
      return systems[0].id;
    })().catch((err) => {
      fallbackSystemIdPromise = null; // 失败不缓存，允许下次重试
      throw err;
    });
  }
  return fallbackSystemIdPromise;
}

// ── 规则目录（职业/技能/属性），按权威 systemId 分别缓存 ──────────────
const rulesetPromises = new Map<string, Promise<Ruleset>>();

export async function getRuleset(): Promise<Ruleset> {
  const systemId = await resolveSystemId();
  const cached = rulesetPromises.get(systemId);
  if (cached) return cached;

  const pending = sdk.games.getRuleset(systemId).catch((err) => {
    rulesetPromises.delete(systemId);
    throw err;
  });
  rulesetPromises.set(systemId, pending);
  return pending;
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
const VALIDATION_FIELD_LABELS: Record<string, string> = {
  name: '姓名',
  age: '年龄',
  gender: '性别',
  residence: '居住地',
  birthplace: '出生地',
  attributes: '属性',
  skills: '技能',
  equipment: '装备',
  occupation: '职业',
  background: '背景故事',
  notes: '备注',
}

function stripValidationLocation(raw: string): { field: string; message: string } {
  const [location, ...messageParts] = raw.split(':')
  const field = location
    .trim()
    .replace(/^(body|query|path|header)\./, '')
    .replace(/^payload\./, '')
  return { field, message: messageParts.join(':').trim() }
}

function translateValidationLine(raw: string): string {
  const { field, message } = stripValidationLocation(raw)
  const label = VALIDATION_FIELD_LABELS[field.split('.').at(-1) ?? field] ?? field
  if (!message) return label
  if (/at least 1 character|field required/i.test(message)) return `${label}不能为空`
  if (/valid integer/i.test(message)) return `${label}必须是整数`
  if (/valid string/i.test(message)) return `${label}必须是字符串`
  return `${label}：${message}`
}

export function translateCharacterValidationError(err: unknown): string {
  if (err instanceof ApiError && err.code === 'CHARACTER_INVALID') {
    const body = err.message.replace(/^角色卡未通过校验：/, '');
    const items = body
      .split(/[；;]\s*/)
      .map((s) => s.replace(/^\[[^\]]+\]\s*/, '').trim())
      .filter(Boolean);
    if (items.length > 0) return items.join('；');
  }
  if (err instanceof ApiError && err.code === 'VALIDATION_ERROR') {
    const items = err.message
      .split(/[；;]\s*/)
      .map((s) => translateValidationLine(s.trim()))
      .filter(Boolean);
    if (items.length > 0) return items.join('；');
  }
  return friendlyErrorMessage(err, '建卡失败');
}
