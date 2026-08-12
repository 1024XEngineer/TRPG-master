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
}: {
  character: CompletedCharacter
  portraitUrl?: string
  occupationName?: string | null
  attributes: readonly RadarAttribute[]
}) {
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
            />
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
        {DERIVED_STAT_DEFINITIONS.map(definition => {
          const StatIcon = DERIVED_STAT_ICONS[definition.key]
          return (
            <div key={definition.key} className="character-ready-sheet__derived-item">
              <StatIcon className="character-ready-sheet__derived-icon" aria-hidden="true" />
              <span className="character-ready-sheet__derived-label">{definition.label}</span>
              <span
                className="character-ready-sheet__derived-value character-ready-sheet__numbered"
                style={{ color: definition.color }}
              >
                {character.derived[definition.key] ?? '—'}
              </span>
            </div>
          )
        })}
      </div>

      <div className="character-ready-sheet__attributes">
        <h4 className="character-ready-sheet__section-title">基础属性</h4>
        <AttributeRadarChart attributes={attributes} values={character.attr} />
      </div>
    </>
  )
}
