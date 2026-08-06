import { describe, expect, it } from 'vitest'
import { ApiError } from '@/services/api-client'
import { resolveSystemId, translateCharacterValidationError } from './ruleset-api'
import { FIXED_TRPG } from '@/config/games'

describe('resolveSystemId', () => {
  it('always resolves the fixed COC7 ruleset', async () => {
    await expect(resolveSystemId()).resolves.toBe(FIXED_TRPG.systemId)
  })
})

describe('translateCharacterValidationError', () => {
  it('translates request validation paths into player-facing Chinese messages', () => {
    const err = new ApiError(
      'VALIDATION_ERROR',
      'body.name: String should have at least 1 character; body.age: Input should be a valid integer',
      422
    )

    expect(translateCharacterValidationError(err)).toBe('姓名不能为空；年龄必须是整数')
  })

  it('removes backend issue codes from character validation messages', () => {
    const err = new ApiError(
      'CHARACTER_INVALID',
      '角色卡未通过校验：[SKILL_ABOVE_CAP] 聆听 的值 105 超过上限 99; [CREDIT_OUT_OF_RANGE] 信用评级不在职业范围内',
      422
    )

    expect(translateCharacterValidationError(err)).toBe('聆听 的值 105 超过上限 99；信用评级不在职业范围内')
  })
})
