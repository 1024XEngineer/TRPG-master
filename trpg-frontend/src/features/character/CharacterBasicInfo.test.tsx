import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { CharacterBasicInfo } from './CharacterBasicInfo'
import type { CompletedCharacter } from '@/stores/character-store'

const ATTRIBUTES = [
  { key: 'STR', label: '力量' },
  { key: 'CON', label: '体质' },
  { key: 'POW', label: '意志' },
  { key: 'LUCK', label: '幸运' },
] as const

function character(): CompletedCharacter {
  return {
    info: {
      name: '杜调查员',
      playerName: '陈探员',
      age: '32',
      gender: '男',
      residence: '阿卡姆',
      birthplace: '波士顿',
      occupationId: 1,
    },
    attr: { STR: 60, CON: 55, POW: 65, LUCK: 50 },
    skillAlloc: {},
    skillFinalValues: {},
    equipment: '',
    background: '',
    notes: '',
    derived: { hp: 10, san: 65, mp: 13, db: '0', build: 0, move: 8 },
  } as CompletedCharacter
}

describe('CharacterBasicInfo', () => {
  afterEach(() => cleanup())

  // 幸运在 COC7 里是属性而不是衍生值，但它有状态、能被 `luck.spend` 消耗，
  // 所以雷达图上那个点必须跟着引擎走。
  it('renders the live LUCK from the engine and keeps the initial value visible', () => {
    render(
      <CharacterBasicInfo
        character={character()}
        attributes={ATTRIBUTES}
        liveResources={{ luck: 37, san: 45 }}
      />,
    )

    expect(screen.getByTestId('derived-stat-san')).toHaveTextContent('45')
    expect(screen.getByTestId('initial-values-note')).toHaveTextContent(
      '初始：SAN 65 · 幸运 50',
    )
  })

  // 建卡完成页在开局前渲染同一个组件，那时没有 PlayerView 可读。
  it('falls back to the creation snapshot when no live resources are supplied', () => {
    render(<CharacterBasicInfo character={character()} attributes={ATTRIBUTES} />)

    expect(screen.getByTestId('derived-stat-hp')).toHaveTextContent('10')
    expect(screen.getByTestId('derived-stat-san')).toHaveTextContent('65')
    expect(screen.queryByTestId('initial-values-note')).not.toBeInTheDocument()
  })

  it('omits unchanged values from the initial note', () => {
    render(
      <CharacterBasicInfo
        character={character()}
        attributes={ATTRIBUTES}
        liveResources={{ hp: 10, san: 45, mp: 13, luck: 50 }}
      />,
    )

    const note = screen.getByTestId('initial-values-note')
    expect(note).toHaveTextContent('初始：SAN 65')
    expect(note).not.toHaveTextContent('HP')
    expect(note).not.toHaveTextContent('幸运')
  })

  // 老角色卡整个缺 `mp` 这类键（`character-store` 里确实存在这种快照）。
  // 没有初始值可言时不能凑一条 `MP undefined` 出来。
  it('skips derived keys the creation snapshot never recorded', () => {
    const legacy = character()
    delete (legacy.derived as unknown as Record<string, unknown>).mp

    render(
      <CharacterBasicInfo
        character={legacy}
        attributes={ATTRIBUTES}
        liveResources={{ mp: 8, san: 45 }}
      />,
    )

    expect(screen.getByTestId('derived-stat-mp')).toHaveTextContent('8')
    const note = screen.getByTestId('initial-values-note')
    expect(note).toHaveTextContent('初始：SAN 65')
    expect(note).not.toHaveTextContent('MP')
  })
})
