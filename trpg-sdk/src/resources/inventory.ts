import type { ApiClient } from '../client';
import type {
  ChangeItemCustodyRequest,
  ChangeItemCustodyResult,
  ConfirmInventoryImportDraftRequest,
  ConfirmInventoryImportResult,
  CreateInventoryImportDraftRequest,
  InventoryImportDraft,
  InventoryView,
} from '../types';

/** Review-first, versioned room inventory operations (#212 §9). */
export class InventoryResource {
  constructor(private readonly client: ApiClient) {}

  private authenticated(reconnectToken: string): RequestInit {
    return { headers: { 'X-Reconnect-Token': reconnectToken } };
  }

  createImportDraft(
    roomId: string,
    payload: CreateInventoryImportDraftRequest,
    reconnectToken: string
  ): Promise<InventoryImportDraft> {
    return this.client.post(
      `/rooms/${roomId}/inventory-import-drafts`,
      payload,
      this.authenticated(reconnectToken)
    );
  }

  confirmImportDraft(
    roomId: string,
    draftId: string,
    payload: ConfirmInventoryImportDraftRequest,
    reconnectToken: string
  ): Promise<ConfirmInventoryImportResult> {
    return this.client.post(
      `/rooms/${roomId}/inventory-import-drafts/${draftId}/confirm`,
      payload,
      this.authenticated(reconnectToken)
    );
  }

  get(roomId: string, reconnectToken: string): Promise<InventoryView> {
    return this.client.get(
      `/rooms/${roomId}/inventory`,
      this.authenticated(reconnectToken)
    );
  }

  changeCustody(
    roomId: string,
    itemId: string,
    payload: ChangeItemCustodyRequest,
    reconnectToken: string
  ): Promise<ChangeItemCustodyResult> {
    return this.client.post(
      `/rooms/${roomId}/items/${itemId}/custody`,
      payload,
      this.authenticated(reconnectToken)
    );
  }
}
