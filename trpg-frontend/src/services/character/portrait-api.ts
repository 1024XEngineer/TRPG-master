/** 角色生图后台任务 API；重连凭证始终从房间状态读取。 */
import type { PortraitGenerationTaskRead } from 'trpg-sdk'
import { useRoomStore } from '@/stores/room-store'
import { sdk } from '../api-client'

function token(): string {
  const reconnectToken = useRoomStore.getState().reconnectToken
  if (!reconnectToken) throw new Error('缺少房间重连凭证，请重新加入房间')
  return reconnectToken
}

export function createCharacterPortrait(roomId: string, characterId: string): Promise<PortraitGenerationTaskRead> {
  return sdk.characters.createPortraitGeneration(roomId, characterId, { style: 'realistic', size: '1024x1024' }, token())
}

export function getCurrentCharacterPortraitTask(roomId: string, characterId: string): Promise<PortraitGenerationTaskRead | null> {
  return sdk.characters.getCurrentPortraitGeneration(roomId, characterId, token())
}

export function cancelCharacterPortrait(roomId: string, characterId: string, generationId: string): Promise<PortraitGenerationTaskRead> {
  return sdk.characters.cancelPortraitGeneration(roomId, characterId, generationId, token())
}

/** 兼容旧调用名；返回值现在是后台任务快照。 */
export const generateCharacterPortrait = createCharacterPortrait
