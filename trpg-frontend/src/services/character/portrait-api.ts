import type { PortraitGenerationResult } from 'trpg-sdk'
import { useRoomStore } from '@/stores/room-store'
import { sdk } from '../api-client'

export async function generateCharacterPortrait(
  roomId: string,
  characterId: string,
): Promise<PortraitGenerationResult> {
  // 重连 token 只从房间 store 读取并发往本项目后端，前端不持有任何生图服务 Key。
  const reconnectToken = useRoomStore.getState().reconnectToken
  if (!reconnectToken) throw new Error('缺少房间重连凭证，请重新加入房间')
  return sdk.characters.generatePortrait(
    roomId,
    characterId,
    { style: 'realistic', size: '1024x1024' },
    reconnectToken,
  )
}
