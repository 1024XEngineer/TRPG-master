import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useHostSpeech } from './useHostSpeech'

class FakeUtterance {
  text: string
  voice: SpeechSynthesisVoice | null = null
  lang = ''
  rate = 0
  pitch = 0
  volume = 0
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

function fakeVoice(overrides: Partial<SpeechSynthesisVoice>): SpeechSynthesisVoice {
  return {
    default: false,
    lang: 'en-US',
    localService: true,
    name: 'English',
    voiceURI: 'english',
    ...overrides,
  }
}

function installSpeechApi(voices: SpeechSynthesisVoice[] = []) {
  let voicesChanged: (() => void) | null = null
  const spoken: FakeUtterance[] = []
  const synthesis = {
    getVoices: vi.fn(() => voices),
    speak: vi.fn((utterance: FakeUtterance) => spoken.push(utterance)),
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    addEventListener: vi.fn((_event: string, listener: () => void) => { voicesChanged = listener }),
    removeEventListener: vi.fn(),
    emitVoicesChanged: () => voicesChanged?.(),
  }
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: synthesis })
  Object.defineProperty(window, 'SpeechSynthesisUtterance', { configurable: true, value: FakeUtterance })
  return { synthesis, spoken }
}

describe('useHostSpeech', () => {
  beforeEach(() => {
    localStorage.clear()
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined })
    Object.defineProperty(window, 'SpeechSynthesisUtterance', { configurable: true, value: undefined })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reports unsupported browsers without throwing', () => {
    const { result } = renderHook(() => useHostSpeech())

    expect(result.current.supported).toBe(false)
    expect(result.current.enabled).toBe(false)
    act(() => {
      result.current.enqueue('message-1', '文本')
      result.current.replay('历史文本')
    })
    expect(result.current.status).toBe('idle')
  })

  it('selects a stable Chinese default and starts disabled', () => {
    installSpeechApi([
      fakeVoice({ name: '中文乙', lang: 'zh-CN', voiceURI: 'zh-b' }),
      fakeVoice({ name: '中文甲', lang: 'zh-Hans', voiceURI: 'zh-a' }),
      fakeVoice({ name: 'English default', default: true, voiceURI: 'en-default' }),
    ])
    const { result: mounted } = renderHook(() => useHostSpeech())

    expect(mounted.current.enabled).toBe(false)
    expect(mounted.current.selectedVoiceURI).toBe('zh-a')
    expect(mounted.current.voices.map((voice) => voice.voiceURI)).toEqual([
      'zh-a',
      'zh-b',
      'en-default',
    ])
  })

  it('falls back to the browser default voice when no Chinese voice exists', () => {
    installSpeechApi([
      fakeVoice({ name: 'Voice B', voiceURI: 'voice-b' }),
      fakeVoice({ name: 'Voice A', default: true, voiceURI: 'voice-a' }),
    ])
    const { result } = renderHook(() => useHostSpeech())
    expect(result.current.selectedVoiceURI).toBe('voice-a')
  })

  it('restores local settings and supports voice changes', () => {
    localStorage.setItem('aidm-host-speech-settings', JSON.stringify({ enabled: true, voiceURI: 'voice-2' }))
    installSpeechApi([
      fakeVoice({ name: 'Voice 1', voiceURI: 'voice-1' }),
      fakeVoice({ name: 'Voice 2', voiceURI: 'voice-2' }),
    ])
    const { result } = renderHook(() => useHostSpeech())

    expect(result.current.enabled).toBe(true)
    expect(result.current.selectedVoiceURI).toBe('voice-2')
    act(() => result.current.setSelectedVoiceURI('voice-1'))
    expect(JSON.parse(localStorage.getItem('aidm-host-speech-settings')!).voiceURI).toBe('voice-1')
  })

  it('plays an ordered, deduplicated automatic queue', () => {
    const { spoken, synthesis } = installSpeechApi()
    const { result } = renderHook(() => useHostSpeech())

    act(() => {
      result.current.setEnabled(true)
      result.current.enqueue('message-1', '第一段')
      result.current.enqueue('message-1', '重复第一段')
      result.current.enqueue('message-2', '第二段')
    })

    expect(synthesis.speak).toHaveBeenCalledTimes(1)
    expect(spoken[0]?.text).toBe('第一段')
    expect(result.current.queueLength).toBe(1)

    act(() => spoken[0]?.onend?.())
    expect(spoken[1]?.text).toBe('第二段')
    expect(result.current.queueLength).toBe(0)
  })

  it('allows manual replay while automatic speech is disabled', () => {
    const { spoken } = installSpeechApi()
    const { result } = renderHook(() => useHostSpeech())

    act(() => result.current.replay('历史主持人消息'))
    expect(spoken).toHaveLength(1)
    expect(spoken[0]?.text).toBe('历史主持人消息')
  })

  it('applies the selected voice and fixed speech parameters', () => {
    const voice = fakeVoice({ name: 'Voice 1', voiceURI: 'voice-1' })
    const { spoken } = installSpeechApi([voice])
    const { result } = renderHook(() => useHostSpeech())

    act(() => {
      result.current.setSelectedVoiceURI('voice-1')
      result.current.replay('带音色的消息')
    })

    expect(spoken[0]?.voice).toBe(voice)
    expect(spoken[0]?.lang).toBe('en-US')
    expect(spoken[0]?.rate).toBe(1)
    expect(spoken[0]?.pitch).toBe(1)
    expect(spoken[0]?.volume).toBe(1)
  })

  it('supports pause, resume, stop and skips utterance errors', () => {
    const { spoken, synthesis } = installSpeechApi()
    const { result } = renderHook(() => useHostSpeech())

    act(() => {
      result.current.setEnabled(true)
      result.current.enqueue('message-1', '第一段')
      result.current.enqueue('message-2', '第二段')
    })
    act(() => result.current.pause())
    expect(result.current.status).toBe('paused')
    expect(synthesis.pause).toHaveBeenCalledTimes(1)
    act(() => result.current.resume())
    expect(result.current.status).toBe('speaking')
    expect(synthesis.resume).toHaveBeenCalledTimes(1)

    act(() => spoken[0]?.onerror?.())
    expect(spoken[1]?.text).toBe('第二段')
    act(() => result.current.stop())
    expect(synthesis.cancel).toHaveBeenCalled()
    expect(result.current.status).toBe('idle')
    expect(result.current.queueLength).toBe(0)
  })

  it('refreshes voices and clears speech on unmount', async () => {
    const { synthesis } = installSpeechApi([])
    const { result, unmount } = renderHook(() => useHostSpeech())
    expect(result.current.voices).toHaveLength(0)

    const voice = fakeVoice({ name: '中文', lang: 'zh-CN', voiceURI: 'zh' })
    synthesis.getVoices.mockReturnValue([voice])
    act(() => synthesis.emitVoicesChanged())
    await waitFor(() => expect(result.current.selectedVoiceURI).toBe('zh'))

    act(() => result.current.replay('待清理'))
    unmount()
    expect(synthesis.cancel).toHaveBeenCalled()
    expect(synthesis.removeEventListener).toHaveBeenCalled()
  })
})
