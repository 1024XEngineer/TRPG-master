import { useEffect, useState } from 'react'
import { getRoomInfo, type RoomPreview } from '@/services/room'

// 轮询房间真实状态（玩家列表/是否就绪/是否建完卡/房间阶段）——后端目前没有
// room.join/player.ready/game.start 的 WS 广播（见 2026-07-13 多人测试报告
// P0：大厅对其他玩家的存在完全无感知），只能退而求其次，用 GET /rooms/{code}
// 按固定间隔轮询真实数据，驱动等待界面里的多玩家列表和"全员到齐才能继续"。
export function useRoomPlayers(roomCode: string | null, intervalMs = 3000) {
  const [info, setInfo] = useState<RoomPreview | null>(null)

  useEffect(() => {
    if (!roomCode) return
    let cancelled = false
    const poll = () => {
      getRoomInfo(roomCode)
        .then((data) => {
          if (!cancelled) setInfo(data)
        })
        .catch(() => {})
    }
    poll()
    const timer = setInterval(poll, intervalMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [roomCode, intervalMs])

  return info
}
