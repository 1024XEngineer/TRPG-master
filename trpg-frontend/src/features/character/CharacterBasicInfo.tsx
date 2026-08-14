import {
  BicepsFlexed,
  Brain,
  Footprints,
  Heart,
  Sword,
  WandSparkles,
  type LucideIcon,
} from 'lucide-react'
import { DERIVED_STAT_DEFINITIONS, type DerivedStatKey } from '@/data/derived-stats'
import type { CompletedCharacter } from '@/stores/character-store'
import { PortraitImage } from '@/features/portrait/PortraitImage'

const DERIVED_STAT_ICONS: Record<DerivedStatKey, LucideIcon> = {
  hp: Heart,
  san: Brain,
  mp: WandSparkles,
  db: Sword,
  build: BicepsFlexed,
  move: Footprints,
}

interface RadarAttribute {
  key: string
  label: string
}

/**
 * PlayerView 投影出来的当前资源，按 id 索引（`hp` / `san` / `mp` / `luck`）。
 *
 * 角色卡按可变性分两类数据源：姓名、职业、出生地这些建卡时定死的仍来自
 * `character-store` 的快照；HP/SAN/MP/幸运在游戏中会被引擎改写，权威值只在
 * PlayerView 里。把运行时资源写回 store 会制造第二份权威状态，所以这里只接
 * 一份只读入参，组件自己不持有运行时状态。
 *
 * 建卡完成页在开局前渲染同一个组件，那时根本没有 PlayerView——它不传这个
 * 入参，全部落回快照值。
 */
export type LiveResources = Readonly<Record<string, number>>

/** 资源 id 与属性/衍生值的键大小写并不一致（`LUCK` vs `luck`）。 */
function liveValueOf(live: LiveResources | undefined, key: string): number | null {
  const value = live?.[key.toLocaleLowerCase()]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function AttributeRadarChart({
  attributes,
  values,
}: {
  attributes: readonly RadarAttribute[]
  values: Readonly<Partial<Record<string, number>>>
}) {
  if (attributes.length < 3) return null

  const centerX = 180
  const centerY = 155
  const radius = 98
  const labelRadius = 112
  const angleAt = (index: number) => -Math.PI / 2 + (index * Math.PI * 2) / attributes.length
  const pointAt = (index: number, pointRadius: number) => {
    const angle = angleAt(index)
    return `${centerX + Math.cos(angle) * pointRadius},${centerY + Math.sin(angle) * pointRadius}`
  }
  const polygonAt = (pointRadius: number) => attributes.map((_, index) => pointAt(index, pointRadius)).join(' ')
  const resolvedValues = attributes.map((attribute) => {
    const value = values[attribute.key]
    return typeof value === 'number' && Number.isFinite(value) ? value : null
  })
  const completeValues = resolvedValues.every((value): value is number => value !== null)
    ? resolvedValues
    : null
  const valuePolygon = completeValues
    ? completeValues.map((rawValue, index) => {
        const value = Math.max(0, Math.min(100, rawValue))
        return pointAt(index, radius * value / 100)
      }).join(' ')
    : null

  return (
    <div className="character-ready-sheet__radar" data-testid="attribute-radar-chart">
      <svg viewBox="0 28 360 260" role="img" aria-label="基础属性雷达图">
        {[0.25, 0.5, 0.75, 1].map(level => (
          <polygon
            key={level}
            points={polygonAt(radius * level)}
            className="character-ready-sheet__radar-grid"
          />
        ))}
        {attributes.map((attribute, index) => (
          <line
            key={attribute.key}
            x1={centerX}
            y1={centerY}
            x2={centerX + Math.cos(angleAt(index)) * radius}
            y2={centerY + Math.sin(angleAt(index)) * radius}
            className="character-ready-sheet__radar-axis"
          />
        ))}
        {valuePolygon ? (
          <polygon points={valuePolygon} className="character-ready-sheet__radar-value" />
        ) : (
          <text
            x={centerX}
            y={centerY}
            textAnchor="middle"
            dominantBaseline="middle"
            className="character-ready-sheet__radar-empty"
          >
            属性数据不完整
          </text>
        )}
        {attributes.map((attribute, index) => {
          const angle = angleAt(index)
          const x = centerX + Math.cos(angle) * labelRadius
          const y = centerY + Math.sin(angle) * labelRadius
          const anchor = Math.cos(angle) > 0.2 ? 'start' : Math.cos(angle) < -0.2 ? 'end' : 'middle'
          return (
            <text
              key={attribute.key}
              x={x}
              y={y}
              textAnchor={anchor}
              dominantBaseline="middle"
              className="character-ready-sheet__radar-label"
            >
              <tspan>{attribute.label}</tspan>
              <tspan className="character-ready-sheet__radar-number"> {resolvedValues[index] ?? '—'}</tspan>
            </text>
          )
        })}
      </svg>
    </div>
  )
}

export function CharacterBasicInfo({
  character,
  portraitUrl,
  occupationName,
  attributes,
  liveResources,
  portraitAction,
}: {
  character: CompletedCharacter
  portraitUrl?: string
  occupationName?: string | null
  attributes: readonly RadarAttribute[]
  liveResources?: LiveResources
  portraitAction?: { kind: 'preview' } | { kind: 'generate'; onActivate: () => void } | { kind: 'static' }
}) {
  // 当前值优先，没有运行时投影时才落回建卡快照。
  const derivedValues = DERIVED_STAT_DEFINITIONS.map(definition => ({
    definition,
    initial: character.derived[definition.key],
    current: liveValueOf(liveResources, definition.key) ?? character.derived[definition.key],
  }))
  const attributeValues: Record<string, number | undefined> = { ...character.attr }
  for (const attribute of attributes) {
    const live = liveValueOf(liveResources, attribute.key)
    if (live !== null) attributeValues[attribute.key] = live
  }

  // 初始值不能就这么消失：SAN 的初始值决定不定性疯狂的阈值（1/5），幸运的初始
  // 值是成长上限的参考。只列出真正变过的项，没变时这一行不渲染。
  const changed = [
    // 只认数字：`db` 是字符串且从不作为资源投影；老角色卡还可能整个缺 `mp`
    // 这类键，那时没有「初始值」可言，列出来只会是 `MP undefined`。
    ...derivedValues
      .filter(item => typeof item.initial === 'number' && item.current !== item.initial)
      .map(item => `${item.definition.abbreviation} ${item.initial}`),
    ...attributes
      .filter(attribute => {
        const initial = character.attr[attribute.key]
        return typeof initial === 'number' && attributeValues[attribute.key] !== initial
      })
      .map(attribute => `${attribute.label} ${character.attr[attribute.key]}`),
  ]

  return (
    <>
      <div className="character-ready-sheet__profile">
        <div
          className="character-ready-sheet__portrait rounded-sm flex items-center justify-center text-2xl overflow-hidden"
          style={{ background: 'linear-gradient(135deg,#e8e0d0,#d8cfb8)', border: '2px solid #b8976a' }}
        >
          {portraitUrl ? (
            <PortraitImage
              src={portraitUrl}
              alt={`${character.info.name}的头像`}
              buttonClassName="h-full w-full"
              imageClassName="h-full w-full object-cover"
              action={portraitAction}
            />
          ) : portraitAction?.kind === 'generate' ? (
            <button type="button" aria-label="生成角色图片" onClick={portraitAction.onActivate} className="h-full w-full text-2xl">🕵️</button>
          ) : '🕵️'}
        </div>
        <div className="character-ready-sheet__identity">
          <div className="character-ready-sheet__identity-name font-bold text-text-primary">{character.info.name}</div>
          <div className="character-ready-sheet__identity-summary character-ready-sheet__numbered text-text-muted">
            {character.info.age}岁 · {character.info.gender}
          </div>
          <div className="character-ready-sheet__occupation text-text-muted">
            职业：{occupationName ?? '未选择职业'}
          </div>
          <div className="character-ready-sheet__locations">
            <span>居住地：{character.info.residence || '—'}</span>
            <span>出生地：{character.info.birthplace || '—'}</span>
          </div>
        </div>
      </div>

      <div className="character-ready-sheet__derived" data-testid="derived-stats-grid">
        {derivedValues.map(({ definition, current }) => {
          const StatIcon = DERIVED_STAT_ICONS[definition.key]
          return (
            <div key={definition.key} className="character-ready-sheet__derived-item">
              <StatIcon className="character-ready-sheet__derived-icon" aria-hidden="true" />
              <span className="character-ready-sheet__derived-label">{definition.label}</span>
              <span
                className="character-ready-sheet__derived-value character-ready-sheet__numbered"
                style={{ color: definition.color }}
                data-testid={`derived-stat-${definition.key}`}
              >
                {current ?? '—'}
              </span>
            </div>
          )
        })}
      </div>

      <div className="character-ready-sheet__attributes">
        <h4 className="character-ready-sheet__section-title">基础属性</h4>
        <AttributeRadarChart attributes={attributes} values={attributeValues} />
        {changed.length > 0 && (
          <p
            className="character-ready-sheet__initial-values text-xs text-text-muted mt-1"
            data-testid="initial-values-note"
          >
            初始：{changed.join(' · ')}
          </p>
        )}
      </div>
    </>
  )
}
