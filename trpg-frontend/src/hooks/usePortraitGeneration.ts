/** 在应用顶层恢复并轮询当前玩家的角色生图后台任务。 */
import { useEffect } from 'react'
import { getCurrentCharacterPortraitTask } from '@/services/character/portrait-api'
import { useRoomStore } from '@/stores/room-store'
import { isPortraitTaskActive, portraitTaskKey, usePortraitGenerationStore } from '@/stores/portrait-generation-store'

export function usePortraitGenerationCoordinator() {
  const roomId = useRoomStore((s) => s.roomId)
  const characterId = useRoomStore((s) => s.characterId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const task = usePortraitGenerationStore((s) => roomId && characterId ? s.tasks[portraitTaskKey(roomId, characterId)] : null)
  const setTask = usePortraitGenerationStore((s) => s.setTask)
  const taskActive = isPortraitTaskActive(task)
  const taskLoaded = task !== undefined
  useEffect(() => {
    if (!roomId || !characterId || !reconnectToken) return
    let disposed = false
    const refresh = async (notify: boolean) => {
      try {
        const current = await getCurrentCharacterPortraitTask(roomId, characterId)
        if (!disposed) setTask(roomId, characterId, current, notify)
      } catch { /* 短暂断线时保留最后一次权威快照，下一轮继续恢复。 */ }
    }
    void refresh(false)
    if (!taskActive && taskLoaded) return () => { disposed = true }
    const timer = window.setInterval(() => void refresh(true), 2000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [roomId, characterId, reconnectToken, taskActive, taskLoaded, setTask])
}
