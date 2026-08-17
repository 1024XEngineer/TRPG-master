import type { ApiClient } from '../client';
import type {
  CharacterTemplate,
  SaveCharacterTemplateInput,
  UpdateCharacterTemplateInput,
} from '../types';

/**
 * `/api/v1/me/character-templates` 的类型化封装——玩家的「我的常用角色卡」库。
 * 跨房间复用，属于账号级资源，走 `Authorization: Bearer <token>` 鉴权
 * （不是房间的重连凭证）。
 *
 * #337 起卡库同时是建卡的宿主：卡库卡由玩家显式保存产生，房间角色卡是它的一份
 * 拷贝，两者之后互不影响。
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
}
