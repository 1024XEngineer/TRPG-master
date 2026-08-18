import type { ApiClient } from '../client';
import type {
  Character,
  CharacterDraftResult,
  GeneratePortraitInput,
  PortraitGenerationTaskRead,
  QuickGenerateInput,
  QuickGenerateResult,
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
  /**
   * POST /api/v1/rooms/{roomId}/characters — 建一份房间角色草稿。
   *
   * `basedOnTemplateId`（#337）：从玩家自己的卡库卡播种这份草稿，建卡态字段整体
   * 拷进来，拷完房间卡就自足了。房间里**已经有草稿时会 409**——要不要冲掉玩家
   * 已经改了一半的草稿，得让玩家自己决定，不能静默忽略。
   */
  createDraft(
    roomId: string,
    reconnectToken: string,
    basedOnTemplateId?: string
  ): Promise<CharacterDraftResult> {
    return this.client.post<CharacterDraftResult>(
      `/rooms/${roomId}/characters`,
      basedOnTemplateId ? { basedOnTemplateId } : null,
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

  /** POST /api/v1/rooms/{roomId}/characters/{characterId}/quick-generate —
   * 服务端生成一张规则合法的角色草稿，不完成角色卡，也不触发生图。 */
  quickGenerate(
    roomId: string,
    characterId: string,
    reconnectToken: string,
    payload?: QuickGenerateInput
  ): Promise<QuickGenerateResult> {
    return this.client.post<QuickGenerateResult>(
      `/rooms/${roomId}/characters/${characterId}/quick-generate`,
      payload ?? null,
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

  /** POST /api/v1/rooms/{roomId}/characters/{characterId}/portrait-generations —
   * 玩家主动为已完成的本人角色生成图片。 */
  createPortraitGeneration(
    roomId: string,
    characterId: string,
    payload: GeneratePortraitInput,
    reconnectToken: string
  ): Promise<PortraitGenerationTaskRead> {
    return this.client.post<PortraitGenerationTaskRead>(
      `/rooms/${roomId}/characters/${characterId}/portrait-generations`,
      payload,
      this.authenticated(reconnectToken)
    );
  }

  /** 兼容旧资源命名；现在创建的是后台任务而非同步图片结果。 */
  generatePortrait(
    roomId: string,
    characterId: string,
    payload: GeneratePortraitInput,
    reconnectToken: string
  ): Promise<PortraitGenerationTaskRead> {
    return this.createPortraitGeneration(roomId, characterId, payload, reconnectToken);
  }

  /** GET current — 读取活动任务；没有活动任务时返回最近终态。 */
  getCurrentPortraitGeneration(
    roomId: string,
    characterId: string,
    reconnectToken: string
  ): Promise<PortraitGenerationTaskRead | null> {
    return this.client.get<PortraitGenerationTaskRead | null>(
      `/rooms/${roomId}/characters/${characterId}/portrait-generations/current`,
      this.authenticated(reconnectToken)
    );
  }

  /** GET generation — 读取指定任务的权威快照。 */
  getPortraitGeneration(
    roomId: string,
    characterId: string,
    generationId: string,
    reconnectToken: string
  ): Promise<PortraitGenerationTaskRead> {
    return this.client.get<PortraitGenerationTaskRead>(
      `/rooms/${roomId}/characters/${characterId}/portrait-generations/${generationId}`,
      this.authenticated(reconnectToken)
    );
  }

  /** POST cancel — 幂等终止任务并返回服务端权威状态。 */
  cancelPortraitGeneration(
    roomId: string,
    characterId: string,
    generationId: string,
    reconnectToken: string
  ): Promise<PortraitGenerationTaskRead> {
    return this.client.post<PortraitGenerationTaskRead>(
      `/rooms/${roomId}/characters/${characterId}/portrait-generations/${generationId}/cancel`,
      null,
      this.authenticated(reconnectToken)
    );
  }

  /** GET /api/v1/rooms/{roomId}/players/{playerId}/portrait —
   * 使用房间凭证读取持久化头像；version 只用于安全地刷新浏览器缓存。 */
  getPlayerPortrait(
    roomId: string,
    playerId: string,
    version: string,
    reconnectToken: string,
    signal?: AbortSignal
  ): Promise<Blob> {
    const path = `/rooms/${encodeURIComponent(roomId)}/players/${encodeURIComponent(playerId)}/portrait?v=${encodeURIComponent(version)}`;
    return this.client.requestBlob(path, {
      ...this.authenticated(reconnectToken),
      method: 'GET',
      signal
    });
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
