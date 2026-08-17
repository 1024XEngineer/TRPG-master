/**
 * 「我的角色卡库」（#337）。
 *
 * 卡库卡是玩家自己的第一等资产，房间角色卡是它的一份拷贝。所以这一层走的是
 * **账号凭证**（`Authorization: Bearer`），不是房间的 `X-Reconnect-Token`——
 * 卡库脱离任何房间存在。
 */

import { getAuthToken, sdk } from '../api-client';
import type { BuiltCharacter } from './character-api';
import { resolveSystemId } from './ruleset-api';

export type CharacterTemplate = Awaited<
  ReturnType<typeof sdk.characterTemplates.list>
>[number];

function requireAuthToken(): string {
  const token = getAuthToken();
  if (!token) throw new Error('请先登录');
  return token;
}

/**
 * 卡库卡 `data` 里的建卡态字段。
 *
 * 键名是后端 `_character_template_data()` 的输出（snake_case 的 JSON 袋子，
 * 不是 DTO，所以不会经过 camelCase 转换）。`generation_method` 只读——它由服务端
 * 背书，客户端写什么都会被压成 `pointbuy`（见后端 `create/update` 的说明）。
 */
export interface CharacterTemplateData {
  // 后端 `data` 是自由 JSON 列，DTO 侧就是 `dict`。索引签名让这个精确形状能直接
  // 作为 `CharacterTemplateCreateBody['data']` 传下去，而不必在每个调用点 cast。
  [key: string]: unknown;
  generation_method?: string;
  name?: string | null;
  age?: number | null;
  gender?: string | null;
  residence?: string;
  birthplace?: string;
  attributes?: Record<string, number>;
  skills?: Record<string, number>;
  occupation_choice_skill_ids?: string[] | null;
  equipment?: string[];
  occupation?: string | null;
  background?: string;
  notes?: string;
}

/**
 * 我的卡库列表。默认只列当前产品固定运行的 COC7——卡库按规则系统隔离，
 * 别的系统的卡拿到这里也用不了（后端播种时会 409）。
 */
export async function listCharacterTemplates(systemId?: string): Promise<CharacterTemplate[]> {
  return sdk.characterTemplates.list(requireAuthToken(), systemId ?? (await resolveSystemId()));
}

export function getCharacterTemplate(templateId: string): Promise<CharacterTemplate> {
  return sdk.characterTemplates.get(templateId, requireAuthToken());
}

export async function createCharacterTemplate(
  name: string,
  data: CharacterTemplateData = {}
): Promise<CharacterTemplate> {
  const systemId = await resolveSystemId();
  return sdk.characterTemplates.save({ name, systemId, data }, requireAuthToken());
}

export function updateCharacterTemplate(
  templateId: string,
  payload: { name?: string; data?: CharacterTemplateData }
): Promise<CharacterTemplate> {
  return sdk.characterTemplates.update(templateId, payload, requireAuthToken());
}

export function deleteCharacterTemplate(templateId: string): Promise<null> {
  return sdk.characterTemplates.remove(templateId, requireAuthToken());
}

export function rollTemplateAttributes(templateId: string) {
  return sdk.characterTemplates.rollAttributes(templateId, requireAuthToken());
}

export function quickGenerateTemplate(
  templateId: string,
  identity?: { name?: string; age?: number | null; gender?: string; residence?: string; birthplace?: string }
) {
  return sdk.characterTemplates.quickGenerate(
    templateId,
    identity
      ? {
          name: identity.name?.trim() || null,
          age: identity.age ?? null,
          gender: identity.gender || null,
          residence: identity.residence ?? '',
          birthplace: identity.birthplace ?? '',
        }
      : undefined,
    requireAuthToken()
  );
}

/**
 * 把建卡向导算好的一张卡转成卡库卡的 `data`。
 *
 * 刻意不带 `derived_stats`：HP/理智/魔法值是**按属性算出来的**，后端 complete 时
 * 会权威重算并覆盖。存进卡库只会在下次播种时变成一份可能已经过期的副本。
 * `generation_method` 同样不带——服务端说了算，这里写什么都不作数。
 */
export function templateDataFromBuilt(built: BuiltCharacter): CharacterTemplateData {
  return {
    name: built.name,
    age: built.age,
    gender: built.gender,
    residence: built.residence,
    birthplace: built.birthplace,
    attributes: built.attr,
    skills: built.skillValues,
    occupation_choice_skill_ids: built.occupationChoiceSkillIds,
    equipment: Array.isArray(built.equipment)
      ? built.equipment.map((item) => item.trim()).filter(Boolean)
      : built.equipment
        ? built.equipment
            .split(/[,，\n]/)
            .map((item) => item.trim())
            .filter(Boolean)
        : [],
    occupation: built.occupationName,
    background: built.background,
    notes: built.notes,
  };
}
