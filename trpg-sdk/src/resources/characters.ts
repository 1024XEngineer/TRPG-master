import type { ApiClient } from '../client';
import type {
  Character,
  CharacterDraftResult,
  RollAttributesResult,
  UpdateCharacterInput,
} from '../types';

/**
 * `/api/v1/rooms/{roomId}/characters` 的类型化封装——房间内的建卡流程：
 * 创建草稿 → 保存建卡向导算好的数据 → 标记完成。
 */
export class CharactersResource {
  constructor(private readonly client: ApiClient) {}

  private authenticated(reconnectToken: string): RequestInit {
    return { headers: { 'X-Reconnect-Token': reconnectToken } };
  }

  /** POST /api/v1/rooms/{roomId}/characters — 创建一份角色草稿 */
  createDraft(roomId: string, reconnectToken: string): Promise<CharacterDraftResult> {
    return this.client.post<CharacterDraftResult>(
      `/rooms/${roomId}/characters`,
      null,
      this.authenticated(reconnectToken)
    );
  }

  /** GET /api/v1/rooms/{roomId}/characters/{characterId} — 读回自己的角色卡。
   *
   * 后端是角色卡的唯一事实来源，客户端不该把它存进本地当权威源——本地副本的
   * 结构会随后端 schema 演进而过期（issue #96）。
   */
  get(roomId: string, characterId: string, reconnectToken: string): Promise<Character> {
    return this.client.get<Character>(
      `/rooms/${roomId}/characters/${characterId}`,
      this.authenticated(reconnectToken)
    );
  }

  /** PATCH /api/v1/rooms/{roomId}/characters/{characterId} — 保存建卡向导算好的完整角色数据 */
  save(
    roomId: string,
    characterId: string,
    payload: UpdateCharacterInput,
    reconnectToken: string
  ): Promise<null> {
    return this.client.patch<null>(
      `/rooms/${roomId}/characters/${characterId}`,
      payload,
      this.authenticated(reconnectToken)
    );
  }

  /** POST /api/v1/rooms/{roomId}/characters/{characterId}/complete — 标记建卡完成 */
  complete(roomId: string, characterId: string, reconnectToken: string): Promise<null> {
    return this.client.post<null>(
      `/rooms/${roomId}/characters/${characterId}/complete`,
      null,
      this.authenticated(reconnectToken)
    );
  }

  /** POST /api/v1/rooms/{roomId}/characters/{characterId}/roll-attributes —
   * 服务端权威掷骰生成属性（issue #77 新增，本期未实现）。 */
  rollAttributes(
    roomId: string,
    characterId: string,
    reconnectToken: string
  ): Promise<RollAttributesResult> {
    return this.client.post<RollAttributesResult>(
      `/rooms/${roomId}/characters/${characterId}/roll-attributes`,
      null,
      this.authenticated(reconnectToken)
    );
  }
}
