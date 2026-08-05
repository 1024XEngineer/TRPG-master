import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useHostSpeech } from './useHostSpeech'

const { getSettings, getManifest, getSentence, updateSettings } = vi.hoisted(() => ({
  getSettings: vi.fn(),
  getManifest: vi.fn(),
  getSentence: vi.fn(),
  updateSettings: vi.fn(),
}))

vi.mock('@/services/api-client', () => ({
  friendlyErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
  sdk: { rooms: {
    getHostSpeechSettings: getSettings,
    getHostSpeechManifest: getManifest,
    getHostSpeechSentence: getSentence,
    updateHostSpeechSettings: updateSettings,
  } },
}))

class FakeAudio extends EventTarget {
  src = ''
  playbackRate = 1
  volume = 1
  preservesPitch = false
  play = vi.fn(async () => {})
  pause = vi.fn()
  load = vi.fn()
  removeAttribute = vi.fn(() => { this.src = '' })
  finish() { this.dispatchEvent(new Event('ended')) }
}

const options = { roomId: 'room-1', reconnectToken: 'reconnect-1', accountToken: 'account-1' }
const settings = {
  available: true,
  provider: 'fake',
  voiceType: 'voice-a',
  voices: [{ voiceType: 'voice-a', label: '音色 A' }],
  autoEmotion: true,
}

describe('useHostSpeech', () => {
  let audios: FakeAudio[]

  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    audios = []
    vi.stubGlobal('Audio', class {
      constructor() {
        const audio = new FakeAudio()
        audios.push(audio)
        return audio
      }
    })
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn((blob: Blob) => `blob:${blob.size}:${Math.random()}`),
      revokeObjectURL: vi.fn(),
    })
    getSettings.mockResolvedValue(settings)
    updateSettings.mockResolvedValue({ ...settings, voiceType: 'voice-b' })
    getManifest.mockResolvedValue({
      messageId: 'message-1',
      sentences: [{ index: 0, text: '第一句。' }, { index: 1, text: '第二句。' }],
    })
    getSentence.mockResolvedValue(new Blob(['mp3'], { type: 'audio/mpeg' }))
  })

  it('迁移旧设置时保留 enabled，并丢弃 voiceURI', async () => {
    localStorage.setItem('aidm-host-speech-settings', JSON.stringify({ enabled: true, voiceURI: 'browser' }))
    const { result } = renderHook(() => useHostSpeech(options))
    await waitFor(() => expect(result.current.available).toBe(true))
    expect(result.current.enabled).toBe(true)
    expect(result.current.playbackRate).toBe(1)
    expect(JSON.parse(localStorage.getItem('aidm-host-speech-settings')!)).toEqual({
      version: 2, enabled: true, playbackRate: 1, volume: 1,
    })
  })

  it('历史消息标记后不自动朗读，仍允许手动重播', async () => {
    const { result } = renderHook(() => useHostSpeech(options))
    await waitFor(() => expect(result.current.available).toBe(true))
    act(() => {
      result.current.setEnabled(true)
      result.current.markSeen(['message-1'])
      result.current.enqueue('message-1')
    })
    expect(getManifest).not.toHaveBeenCalled()
    act(() => result.current.replay('message-1'))
    await waitFor(() => expect(getManifest).toHaveBeenCalledTimes(1))
  })

  it('逐句播放，并在当前句播放时只预取下一句', async () => {
    const { result } = renderHook(() => useHostSpeech(options))
    await waitFor(() => expect(result.current.available).toBe(true))
    act(() => {
      result.current.setEnabled(true)
      result.current.enqueue('message-1')
    })
    await waitFor(() => expect(getSentence).toHaveBeenCalledTimes(2))
    expect(result.current.currentSentenceIndex).toBe(0)
    expect(result.current.currentSentences.map((sentence) => sentence.text).join('')).toBe('第一句。第二句。')
    act(() => audios[0].finish())
    await waitFor(() => expect(result.current.currentSentenceIndex).toBe(1))
    act(() => audios[0].finish())
    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('本地速度和音量即时应用，音色广播会停止并清空队列', async () => {
    const { result } = renderHook(() => useHostSpeech(options))
    await waitFor(() => expect(result.current.available).toBe(true))
    act(() => {
      result.current.setPlaybackRate(1.25)
      result.current.setVolume(0.4)
      result.current.replay('message-1')
    })
    await waitFor(() => expect(audios[0]?.play).toHaveBeenCalled())
    expect(audios[0].playbackRate).toBe(1.25)
    expect(audios[0].volume).toBe(0.4)
    act(() => result.current.handleSettingsUpdated('voice-b'))
    expect(result.current.status).toBe('idle')
    expect(result.current.queueLength).toBe(0)
    expect(result.current.voiceType).toBe('voice-b')
    expect(audios[0].pause).toHaveBeenCalled()
  })

  it('合成失败只保留失败状态，不调用浏览器 speechSynthesis', async () => {
    getManifest.mockRejectedValue(new Error('上游失败'))
    const browserSpeak = vi.fn()
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak: browserSpeak } })
    const { result } = renderHook(() => useHostSpeech(options))
    await waitFor(() => expect(result.current.available).toBe(true))
    act(() => result.current.replay('message-1'))
    await waitFor(() => expect(result.current.status).toBe('failed'))
    expect(result.current.error).toBe('上游失败')
    expect(browserSpeak).not.toHaveBeenCalled()
  })
})
