import type { ApiClient } from '../client';
import type {
  ConfirmEndingDraftRequest,
  ConfirmEndingDraftResult,
  CreateEndingDraftRequest,
  EndingDraft,
} from '../types';

/** Revision-bound ending review and confirmation (#212 §10). */
export class EndingsResource {
  constructor(private readonly client: ApiClient) {}

  private authenticated(reconnectToken: string): RequestInit {
    return { headers: { 'X-Reconnect-Token': reconnectToken } };
  }

  createDraft(
    roomId: string,
    payload: CreateEndingDraftRequest,
    reconnectToken: string
  ): Promise<EndingDraft> {
    return this.client.post(
      `/rooms/${roomId}/ending-drafts`,
      payload,
      this.authenticated(reconnectToken)
    );
  }

  confirmDraft(
    roomId: string,
    draftId: string,
    payload: ConfirmEndingDraftRequest,
    reconnectToken: string
  ): Promise<ConfirmEndingDraftResult> {
    return this.client.post(
      `/rooms/${roomId}/ending-drafts/${draftId}/confirm`,
      payload,
      this.authenticated(reconnectToken)
    );
  }
}
