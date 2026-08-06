export const CHARACTER_BACKGROUND_MAX_LENGTH = 4000

export const BACKGROUND_SECTION_DEFINITIONS = [
  { key: 'personalDescription', label: '形象描述' },
  { key: 'ideologyBeliefs', label: '思想与信念' },
  { key: 'significantPeople', label: '重要之人' },
  { key: 'meaningfulLocations', label: '意义非凡之地' },
  { key: 'treasuredPossessions', label: '宝贵之物' },
  { key: 'traits', label: '特质' },
  { key: 'injuriesScars', label: '伤口和疤痕' },
  { key: 'phobiasManias', label: '恐惧症和躁狂症' },
] as const

export type BackgroundSectionKey = typeof BACKGROUND_SECTION_DEFINITIONS[number]['key']
export type BackgroundSections = Record<BackgroundSectionKey, string>

export interface CharacterBackgroundForm {
  sections: BackgroundSections
  other: string
}

const SECTION_KEY_BY_LABEL = new Map<string, BackgroundSectionKey>(
  BACKGROUND_SECTION_DEFINITIONS.map(section => [section.label, section.key])
)

export function emptyCharacterBackground(): CharacterBackgroundForm {
  return {
    sections: Object.fromEntries(
      BACKGROUND_SECTION_DEFINITIONS.map(section => [section.key, ''])
    ) as BackgroundSections,
    other: '',
  }
}

function normalizedLines(value: string): string[] {
  return value.replace(/\r\n?/g, '\n').split('\n')
}

function cleanedBlock(lines: string[]): string {
  let start = 0
  let end = lines.length
  while (start < end && lines[start].trim() === '') start += 1
  while (end > start && lines[end - 1].trim() === '') end -= 1
  return lines.slice(start, end).join('\n')
}

export function parseCharacterBackground(raw: string): CharacterBackgroundForm {
  const result = emptyCharacterBackground()
  if (!raw.trim()) return result

  const sectionLines = Object.fromEntries(
    BACKGROUND_SECTION_DEFINITIONS.map(section => [section.key, [] as string[]])
  ) as Record<BackgroundSectionKey, string[]>
  const otherLines: string[] = []
  let currentTarget: BackgroundSectionKey | 'other' | null = null

  const appendToCurrent = (line: string) => {
    if (currentTarget === 'other') {
      otherLines.push(line)
    } else if (currentTarget) {
      sectionLines[currentTarget].push(line)
    } else {
      otherLines.push(line)
    }
  }

  for (const line of normalizedLines(raw)) {
    const prefixed = line.match(/^([^：:\n]+)[：:](.*)$/)
    if (!prefixed) {
      appendToCurrent(line)
      continue
    }

    const label = prefixed[1].trim()
    const content = prefixed[2]
    const sectionKey = SECTION_KEY_BY_LABEL.get(label)
    if (sectionKey) {
      currentTarget = sectionKey
      sectionLines[sectionKey].push(content)
      continue
    }
    if (label === '其他') {
      currentTarget = 'other'
      otherLines.push(content)
      continue
    }
    appendToCurrent(line)
  }

  for (const section of BACKGROUND_SECTION_DEFINITIONS) {
    result.sections[section.key] = cleanedBlock(sectionLines[section.key])
  }
  result.other = cleanedBlock(otherLines)
  return result
}

export function serializeCharacterBackground(form: CharacterBackgroundForm): string {
  const output: string[] = []
  for (const section of BACKGROUND_SECTION_DEFINITIONS) {
    const content = form.sections[section.key].replace(/\r\n?/g, '\n').trim()
    if (content) output.push(`${section.label}：${content}`)
  }

  const other = form.other.replace(/\r\n?/g, '\n').trim()
  if (other) output.push(`其他：${other}`)
  return output.join('\n')
}
