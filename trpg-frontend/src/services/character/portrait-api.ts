import type { PortraitGenerationResult } from 'trpg-sdk'
import { useRoomStore } from '@/stores/room-store'
import { sdk } from '../api-client'

export function isCharacterPortraitEnabled(
  value: string | boolean | undefined = import.meta.env.VITE_ENABLE_CHARACTER_PORTRAIT,
): boolean {
  return value === true || value === 'true'
}

export async function generateCharacterPortrait(
  roomId: string,
  characterId: string,
): Promise<PortraitGenerationResult> {
  const reconnectToken = useRoomStore.getState().reconnectToken
  if (!reconnectToken) throw new Error('缺少房间重连凭证，请重新加入房间')
  return sdk.characters.generatePortrait(
    roomId,
    characterId,
    { style: 'realistic', size: '1024x1024' },
    reconnectToken,
  )
}
