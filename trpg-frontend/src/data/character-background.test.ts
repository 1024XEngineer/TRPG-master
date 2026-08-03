import { describe, expect, it } from 'vitest'
import {
  emptyCharacterBackground,
  parseCharacterBackground,
  serializeCharacterBackground,
} from './character-background'

describe('character background', () => {
  it('serializes non-empty sections in fixed order with other last', () => {
    const form = emptyCharacterBackground()
    form.sections.personalDescription = '穿着旧风衣'
    form.sections.significantPeople = '导师亨利'
    form.other = '习惯随身带笔记本'

    expect(serializeCharacterBackground(form)).toBe([
      '形象描述：穿着旧风衣',
      '重要之人：导师亨利',
      '其他：习惯随身带笔记本',
    ].join('\n'))
  })

  it('parses multiline Windows text and merges duplicate sections without overwriting', () => {
    const parsed = parseCharacterBackground([
      '重要之人：亨利是我的导师。',
      '他在三年前失踪。',
      '宝贵之物：一支钢笔。',
      '重要之人：记者艾琳。',
    ].join('\r\n'))

    expect(parsed.sections.significantPeople).toBe([
      '亨利是我的导师。',
      '他在三年前失踪。',
      '记者艾琳。',
    ].join('\n'))
    expect(parsed.sections.treasuredPossessions).toBe('一支钢笔。')
  })

  it('places legacy free text in other', () => {
    const legacy = parseCharacterBackground('这是旧版背景。\n包含两行内容。')
    expect(legacy.other).toBe('这是旧版背景。\n包含两行内容。')
  })

  it('round-trips categorized content', () => {
    const form = emptyCharacterBackground()
    form.sections.ideologyBeliefs = '真相总会留下痕迹。\n即使它并不体面。'
    form.sections.phobiasManias = '害怕密闭空间'
    form.other = '来自波士顿'

    expect(parseCharacterBackground(serializeCharacterBackground(form))).toEqual(form)
  })
})
