import type { ApiClient } from '../client';
import type {
  CharacterTemplate,
  QuickGenerateInput,
  RollAttributesResult,
  SaveCharacterTemplateInput,
  SystemQuickGenerateOutput,
  UpdateCharacterTemplateInput,
} from '../types';

/**
 * `/api/v1/me/character-templates` 的类型化封装——玩家的「我的常用角色卡」库。
 * 跨房间复用，属于账号级资源，走 `Authorization: Bearer <token>` 鉴权
 * （不是房间的重连凭证）。
 *
 * #337 起卡库同时是建卡的宿主：卡库卡由玩家显式保存产生，房间角色卡是它的一份
 * 拷贝。普通角色字段之后互不影响；头像是明确例外，模板派生角色生图后会更新模板
 * 当前头像，供下一次跨房间复用。
 */
export class CharacterTemplatesResource {
  constructor(private readonly client: ApiClient) {}

  private authenticated(token: string): RequestInit {
    return { headers: { Authorization: `Bearer ${token}` } };
  }

  /**
   * GET /api/v1/me/character-templates — 我的卡库列表，最近更新的在前。
   *
   * `systemId` 给车卡界面用：只列出能用在这个规则系统的卡。
   */
  list(token: string, systemId?: string): Promise<CharacterTemplate[]> {
    const query = systemId ? `?systemId=${encodeURIComponent(systemId)}` : '';
    return this.client.get<CharacterTemplate[]>(
      `/me/character-templates${query}`,
      this.authenticated(token)
    );
  }

  /** POST /api/v1/me/character-templates — 把一张角色卡保存为常用卡 */
  save(payload: SaveCharacterTemplateInput, token: string): Promise<CharacterTemplate> {
    return this.client.post<CharacterTemplate>(
      '/me/character-templates',
      payload,
      this.authenticated(token)
    );
  }

  /** GET /api/v1/me/character-templates/{templateId} — 卡库详情 */
  get(templateId: string, token: string): Promise<CharacterTemplate> {
    return this.client.get<CharacterTemplate>(
      `/me/character-templates/${templateId}`,
      this.authenticated(token)
    );
  }

  /** GET /api/v1/me/character-templates/{templateId}/portrait — 读取账号级模板头像。 */
  getPortrait(
    templateId: string,
    version: string,
    token: string,
    signal?: AbortSignal
  ): Promise<Blob> {
    const path = `/me/character-templates/${encodeURIComponent(templateId)}/portrait?v=${encodeURIComponent(version)}`;
    return this.client.requestBlob(path, {
      ...this.authenticated(token),
      method: 'GET',
      signal
    });
  }

  /**
   * PATCH /api/v1/me/character-templates/{templateId} — 改名或覆盖建卡态数据。
   *
   * `data` 是整体覆盖而不是合并——合并语义下删掉一项技能永远删不掉。
   */
  update(
    templateId: string,
    payload: UpdateCharacterTemplateInput,
    token: string
  ): Promise<CharacterTemplate> {
    return this.client.patch<CharacterTemplate>(
      `/me/character-templates/${templateId}`,
      payload,
      this.authenticated(token)
    );
  }

  /**
   * DELETE /api/v1/me/character-templates/{templateId} — 删除常用卡。
   *
   * 引用过它的房间角色卡不受影响，只是出处被置空。
   */
  remove(templateId: string, token: string): Promise<null> {
    return this.client.delete<null>(
      `/me/character-templates/${templateId}`,
      this.authenticated(token)
    );
  }

  /**
   * POST /api/v1/me/character-templates/{templateId}/roll-attributes —— 服务端
   * 权威掷属性，结果**直接写进这张卡**并背书为 roll（#337）。
   *
   * 写进服务端而不是交回客户端自己存，是因为「属性是掷出来的」这条声明的唯一
   * 作用是让房间里的 complete 跳过点数预算校验。客户端能自己声明的话，8 项全
   * 90 也能过关。之后任何改动属性的 update() 都会把这条背书退回点数购买法。
   */
  rollAttributes(templateId: string, token: string): Promise<RollAttributesResult> {
    return this.client.post<RollAttributesResult>(
      `/me/character-templates/${templateId}/roll-attributes`,
      undefined,
      this.authenticated(token)
    );
  }

  /**
   * POST /api/v1/me/character-templates/{templateId}/quick-generate —— 一键生成
   * 一整份建卡态数据并写进这张卡（#337）。
   *
   * 不生成 AI 背景故事：卡库建卡是随手捏卡，不该每点一次就产生一次计费请求。
   */
  quickGenerate(
    templateId: string,
    payload: QuickGenerateInput | undefined,
    token: string
  ): Promise<SystemQuickGenerateOutput> {
    return this.client.post<SystemQuickGenerateOutput>(
      `/me/character-templates/${templateId}/quick-generate`,
      payload,
      this.authenticated(token)
    );
  }
}
