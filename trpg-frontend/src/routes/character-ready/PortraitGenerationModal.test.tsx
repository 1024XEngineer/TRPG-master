import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { PortraitGenerationResult } from 'trpg-sdk'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { generateCharacterPortrait } from '@/services/character/portrait-api'
import { PortraitGenerationModal } from './PortraitGenerationModal'

vi.mock('@/services/character/portrait-api', () => ({
  generateCharacterPortrait: vi.fn(),
}))

const generated: PortraitGenerationResult = {
  generationId: 'generation-1',
  status: 'completed',
  imageUrl: 'https://images.example/portrait.png',
  portraitVersion: 'portrait-version-1',
  prompt: 'portrait prompt',
  negativePrompt: 'watermark',
  promptSummary: '私家侦探的风衣、伤疤和侦查装备',
  promptSource: 'deepseek',
}

function Harness({ initialResult = null }: { initialResult?: PortraitGenerationResult | null }) {
  const [result, setResult] = useState(initialResult)
  return (
    <PortraitGenerationModal
      roomId="room-1"
      characterId="character-1"
      characterName="陈探员"
      result={result}
      portraitUrl={result ? 'blob:persistent-portrait' : undefined}
      onResult={setResult}
      onClose={vi.fn()}
    />
  )
}

describe('PortraitGenerationModal', () => {
  beforeEach(() => {
    vi.mocked(generateCharacterPortrait).mockReset()
  })

  afterEach(() => {
    cleanup()
  })

  it('打开弹窗时不会自动生图，由玩家主动确认', () => {
    render(<Harness />)

    expect(generateCharacterPortrait).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '开始生成' })).toBeEnabled()
  })

  it('展示生成中状态、成功图片和生成依据', async () => {
    let resolveRequest: (value: PortraitGenerationResult) => void = () => undefined
    vi.mocked(generateCharacterPortrait).mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve
      }),
    )
    render(<Harness />)

    fireEvent.click(screen.getByRole('button', { name: '开始生成' }))

    expect(screen.getByText('正在生成人物图片…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成中…' })).toBeDisabled()
    expect(generateCharacterPortrait).toHaveBeenCalledTimes(1)

    resolveRequest(generated)
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '陈探员的人物图片' })).toHaveAttribute(
        'src',
        'blob:persistent-portrait',
      )
    })
    expect(screen.getByText(generated.promptSummary)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新生成' })).toBeEnabled()
  })

  it('生成失败后显示错误并允许重试', async () => {
    vi.mocked(generateCharacterPortrait).mockRejectedValueOnce(new Error('阿里云生图服务暂时不可用'))
    render(<Harness initialResult={generated} />)

    fireEvent.click(screen.getByRole('button', { name: '重新生成' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('阿里云生图服务暂时不可用')
    expect(screen.getByRole('button', { name: '重新生成' })).toBeEnabled()
  })
})
