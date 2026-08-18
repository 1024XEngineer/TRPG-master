import { useEffect, useState } from 'react'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'
import { fetchCharacter } from '@/services/character/character-api'
import { normalizeDerivedStats } from '@/data/derived-stats'
import { useRuleset } from '@/hooks/useRuleset'

type RoomCharacter = ReturnType<typeof useCharacterStore.getState>['character']

/**
 * 当前房间的角色卡，**以后端为准**，本地缓存只作首屏占位（issue #96）。
 *
 * 这段逻辑原本只长在准备页里，游戏内的 RoomPage 却只读 `useCharacterStore`——
 * 而那个 store 全仓库只有建卡向导的两处提交会写。于是任何绕开建卡向导的路径
 * （#337 的「从卡库选卡」直接完成建卡进准备页就是一条）在准备页看着正常、进了
 * 游戏角色卡面板就是空的。换浏览器或清掉 localStorage 也一样。
 *
 * 抽成 hook 而不是在那条新路径上补一次 `setCharacter`：补那一处只堵得住那一条
 * 路，而"缓存是权威源"这个错误本身还留在 RoomPage 里，下一条新路径照样会踩。
 */
export interface RoomCharacterView {
  character: RoomCharacter
  /** 这张房间卡是从哪张卡库卡播种来的；没有出处就是 null。 */
  basedOnTemplateId: string | null
}

export function useRoomCharacter(): RoomCharacterView {
  const roomId = useRoomStore((s) => s.roomId)
  const characterId = useRoomStore((s) => s.characterId)
  // 按房间取缓存，而不是直接读 s.character——本地缓存不按房间区分的话，换房间
  // 会把上一个房间的角色数据错误地展示出来（见 PR #67 review）。
  const cached = useCharacterStore((s) => (roomId ? s.getForRoom(roomId) : null))
  const { ruleset } = useRuleset()

  const identity = roomId && characterId ? `${roomId}:${characterId}` : null
  const [remote, setRemote] = useState<{
    identity: string
    character: NonNullable<RoomCharacter>
    basedOnTemplateId: string | null
  } | null>(null)

  useEffect(() => {
    // 组件可能在不卸载的情况下切换房间。上一身份的远程角色不能继续压过新房间的
    // 缓存，更不能让没有 characterId 的房间误判为已经建卡。
    setRemote(null)
    if (!roomId || !characterId || !ruleset || !identity) return
    let cancelled = false
    fetchCharacter(roomId, characterId)
      .then((saved) => {
        if (cancelled || !saved.name) return
        const occupationId = ruleset.occupations.find((o) => o.name === saved.occupation)?.id ?? null
        setRemote({
          identity,
          basedOnTemplateId: saved.basedOnTemplateId ?? null,
          character: {
            info: {
              name: saved.name,
              playerName: '',
              age: saved.age != null ? String(saved.age) : '',
              gender: saved.gender ?? '',
              residence: saved.residence ?? '',
              birthplace: saved.birthplace ?? '',
              occupationId,
            },
            attr: { ...saved.attributes },
            skillAlloc: {},
            skillFinalValues: { ...saved.skills },
            occupationChoiceSkillIds: saved.occupationChoiceSkillIds ?? [],
            equipment: (saved.equipment ?? []).join('、'),
            background: saved.background ?? '',
            notes: saved.notes ?? '',
            derived: normalizeDerivedStats(saved.derivedStats ?? {}),
          },
        })
      })
      .catch(() => {
        // 拉不到就沿用本地缓存（比如还没建过卡），不打断页面。
      })
    return () => {
      cancelled = true
    }
  }, [roomId, characterId, identity, ruleset])

  return remote?.identity === identity
    ? { character: remote.character, basedOnTemplateId: remote.basedOnTemplateId }
    : { character: cached, basedOnTemplateId: null }
}
