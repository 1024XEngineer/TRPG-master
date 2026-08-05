import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSpeechInput } from './useSpeechInput'

type ResultHandler = ((event: {
  resultIndex?: number
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }>
}) => void) | null

class FakeSpeechRecognition {
  static instances: FakeSpeechRecognition[] = []

  lang = ''
  continuous = true
  interimResults = true
  onstart: (() => void) | null = null
  onresult: ResultHandler = null
  onend: (() => void) | null = null
  onerror: ((event: { error: string }) => void) | null = null
  start = vi.fn()
  stop = vi.fn()
  abort = vi.fn()

  constructor() {
    FakeSpeechRecognition.instances.push(this)
  }

  begin() {
    this.onstart?.()
  }

  result(transcript: string, index = 0) {
    const results = Array.from({ length: index + 1 }, () =>
      Object.assign([{ transcript: '' }], { isFinal: true }),
    )
    results[index] = Object.assign([{ transcript }], { isFinal: true })
    this.onresult?.({ resultIndex: index, results })
  }

  fail(error: string) {
    this.onerror?.({ error })
  }

  end() {
    this.onend?.()
  }
}

function installRecognition(name: 'SpeechRecognition' | 'webkitSpeechRecognition' = 'SpeechRecognition') {
  Object.defineProperty(window, name, {
    configurable: true,
    value: FakeSpeechRecognition,
  })
}

describe('useSpeechInput', () => {
  beforeEach(() => {
    FakeSpeechRecognition.instances = []
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
    Reflect.deleteProperty(window, 'SpeechRecognition')
    Reflect.deleteProperty(window, 'webkitSpeechRecognition')
  })

  afterEach(() => {
    Reflect.deleteProperty(window, 'SpeechRecognition')
    Reflect.deleteProperty(window, 'webkitSpeechRecognition')
    Reflect.deleteProperty(window, 'isSecureContext')
  })

  it('detects unsupported browsers and insecure HTTP pages', () => {
    const { result, unmount } = renderHook(() => useSpeechInput(vi.fn()))
    expect(result.current.status).toBe('unsupported')
    expect(result.current.unavailableReason).toContain('浏览器不支持')
    unmount()

    installRecognition()
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false })
    const insecure = renderHook(() => useSpeechInput(vi.fn()))
    expect(insecure.result.current.supported).toBe(false)
    expect(insecure.result.current.unavailableReason).toContain('HTTPS')
  })

  it('supports the webkit-prefixed constructor', () => {
    installRecognition('webkitSpeechRecognition')
    const { result } = renderHook(() => useSpeechInput(vi.fn()))
    expect(result.current.supported).toBe(true)
    expect(result.current.status).toBe('idle')
  })

  it('moves through start, listening, processing and idle while emitting each final result once', () => {
    installRecognition()
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useSpeechInput(onTranscript))

    act(() => result.current.start())
    expect(result.current.status).toBe('requesting_permission')
    const recognition = FakeSpeechRecognition.instances[0]
    expect(recognition.start).toHaveBeenCalledTimes(1)
    expect(recognition.lang).toBe('zh-CN')
    expect(recognition.continuous).toBe(false)
    expect(recognition.interimResults).toBe(false)

    act(() => recognition.begin())
    expect(result.current.status).toBe('listening')
    act(() => {
      recognition.result('调查书架')
      recognition.result('调查书架')
    })
    expect(onTranscript).not.toHaveBeenCalled()

    act(() => result.current.stop())
    expect(result.current.status).toBe('processing')
    expect(recognition.stop).toHaveBeenCalledOnce()
    act(() => recognition.end())
    expect(result.current.status).toBe('idle')
    expect(onTranscript).toHaveBeenCalledOnce()
    expect(onTranscript).toHaveBeenCalledWith('调查书架')
  })

  it('ignores late results after cancellation and prevents duplicate instances', () => {
    installRecognition()
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useSpeechInput(onTranscript))

    act(() => {
      result.current.start()
      result.current.start()
    })
    expect(FakeSpeechRecognition.instances).toHaveLength(1)
    const recognition = FakeSpeechRecognition.instances[0]
    const lateResult = recognition.onresult!

    act(() => recognition.result('取消前暂存但尚未提交'))
    act(() => result.current.cancel())
    expect(recognition.abort).toHaveBeenCalledOnce()
    expect(result.current.status).toBe('idle')
    act(() => lateResult({
      resultIndex: 0,
      results: [Object.assign([{ transcript: '不应写入' }], { isFinal: true })],
    }))
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('maps browser errors and clears them on the next attempt', () => {
    installRecognition()
    const { result } = renderHook(() => useSpeechInput(vi.fn()))
    act(() => result.current.start())
    act(() => FakeSpeechRecognition.instances[0].fail('not-allowed'))
    expect(result.current.status).toBe('failed')
    expect(result.current.error).toContain('权限被拒绝')

    act(() => result.current.start())
    expect(result.current.error).toBeNull()
    expect(result.current.status).toBe('requesting_permission')
  })

  it('reports synchronous start failures and aborts on unmount', () => {
    class ThrowingRecognition extends FakeSpeechRecognition {
      override start = vi.fn(() => { throw new Error('start failed') })
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: ThrowingRecognition })
    const throwing = renderHook(() => useSpeechInput(vi.fn()))
    act(() => throwing.result.current.start())
    expect(throwing.result.current.status).toBe('failed')
    expect(throwing.result.current.error).toContain('无法启动')
    throwing.unmount()

    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: FakeSpeechRecognition })
    const mounted = renderHook(() => useSpeechInput(vi.fn()))
    act(() => mounted.result.current.start())
    const active = FakeSpeechRecognition.instances.at(-1)!
    mounted.unmount()
    expect(active.abort).toHaveBeenCalledOnce()
  })
})
