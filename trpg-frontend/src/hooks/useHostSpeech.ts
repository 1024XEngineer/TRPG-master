import { useCallback, useEffect, useRef, useState } from 'react'
import type { HostSpeechSentenceRead, HostSpeechSettings, HostSpeechVoiceRead } from 'trpg-sdk'
import { friendlyErrorMessage, sdk } from '@/services/api-client'

const STORAGE_KEY = 'aidm-host-speech-settings'

export type HostSpeechStatus =
  | 'idle'
  | 'synthesizing'
  | 'buffering'
  | 'playing'
  | 'paused'
  | 'failed'

interface LocalSettings {
  version: 2
  enabled: boolean
  playbackRate: number
  volume: number
}

interface UseHostSpeechOptions {
  roomId: string | null
  reconnectToken: string | null
  accountToken: string | null
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

function readSettings(): LocalSettings {
  const fallback: LocalSettings = { version: 2, enabled: false, playbackRate: 1, volume: 1 }
  if (typeof window === 'undefined') return fallback
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Record<string, unknown>
    return {
      version: 2,
      enabled: parsed.enabled === true,
      playbackRate: clamp(typeof parsed.playbackRate === 'number' ? parsed.playbackRate : 1, 0.75, 1.25),
      volume: clamp(typeof parsed.volume === 'number' ? parsed.volume : 1, 0, 1),
    }
  } catch {
    return fallback
  }
}

function writeSettings(settings: LocalSettings): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // 受限 iframe/隐私模式可能禁用 localStorage；播放本身仍可继续。
  }
}

export function useHostSpeech({ roomId, reconnectToken, accountToken }: UseHostSpeechOptions) {
  const initial = useRef(readSettings()).current
  const [enabled, setEnabledState] = useState(initial.enabled)
  const [playbackRate, setPlaybackRateState] = useState(initial.playbackRate)
  const [volume, setVolumeState] = useState(initial.volume)
  const [settings, setSettings] = useState<HostSpeechSettings | null>(null)
  const [status, setStatus] = useState<HostSpeechStatus>('idle')
  const [queueLength, setQueueLength] = useState(0)
  const [currentMessageId, setCurrentMessageId] = useState<string | null>(null)
  const [currentSentenceIndex, setCurrentSentenceIndex] = useState<number | null>(null)
  const [currentSentences, setCurrentSentences] = useState<HostSpeechSentenceRead[]>([])
  const [error, setError] = useState('')

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const queueRef = useRef<string[]>([])
  const seenRef = useRef(new Set<string>())
  const processingRef = useRef(false)
  const enabledRef = useRef(enabled)
  const rateRef = useRef(playbackRate)
  const volumeRef = useRef(volume)
  const abortRef = useRef<AbortController | null>(null)
  const generationRef = useRef(0)
  const objectUrlsRef = useRef(new Set<string>())
  const processQueueRef = useRef<() => void>(() => {})

  const credentialsReady = Boolean(roomId && reconnectToken && accountToken)
  const available = credentialsReady && settings?.available === true

  const audio = useCallback(() => {
    if (!audioRef.current) audioRef.current = new Audio()
    return audioRef.current
  }, [])

  const revokeUrl = useCallback((url: string | null) => {
    if (!url || !objectUrlsRef.current.delete(url)) return
    URL.revokeObjectURL(url)
  }, [])

  const clearCurrent = useCallback(() => {
    setCurrentMessageId(null)
    setCurrentSentenceIndex(null)
    setCurrentSentences([])
  }, [])

  const stop = useCallback(() => {
    // generation 让已经跨过 fetch await 的旧播放协程也立刻失效；AbortController
    // 只负责网络取消，二者配合才能覆盖切音色、关自动播放和页面卸载全部路径。
    generationRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    const element = audioRef.current
    if (element) {
      element.pause()
      element.removeAttribute('src')
      element.load()
    }
    for (const url of objectUrlsRef.current) URL.revokeObjectURL(url)
    objectUrlsRef.current.clear()
    queueRef.current = []
    processingRef.current = false
    setQueueLength(0)
    clearCurrent()
    setStatus('idle')
  }, [clearCurrent])

  const fetchSentence = useCallback(async (messageId: string, index: number, signal: AbortSignal) => {
    if (!roomId || !accountToken || !reconnectToken) throw new Error('缺少房间语音身份凭证')
    const blob = await sdk.rooms.getHostSpeechSentence(
      roomId, messageId, index, accountToken, reconnectToken, signal,
    )
    // stop() 可能发生在 fetch 已完成、continuation 尚未恢复的间隙；此处再检查
    // 一次，防止取消后才创建的 Object URL 躲过 stop() 的集中回收。
    if (signal.aborted) throw new DOMException('主持人语音请求已取消', 'AbortError')
    const url = URL.createObjectURL(blob)
    objectUrlsRef.current.add(url)
    return url
  }, [accountToken, reconnectToken, roomId])

  const playUrl = useCallback(async (url: string, generation: number) => {
    const element = audio()
    element.src = url
    element.playbackRate = rateRef.current
    element.volume = volumeRef.current
    element.preservesPitch = true
    setStatus('buffering')
    await new Promise<void>((resolve, reject) => {
      const ended = () => { cleanup(); resolve() }
      const failed = () => { cleanup(); reject(new Error('音频播放失败')) }
      const cleanup = () => {
        element.removeEventListener('ended', ended)
        element.removeEventListener('error', failed)
      }
      element.addEventListener('ended', ended, { once: true })
      element.addEventListener('error', failed, { once: true })
      void element.play().then(() => {
        if (generation === generationRef.current) setStatus('playing')
      }).catch(failed)
    })
  }, [audio])

  const processQueue = useCallback(async () => {
    if (processingRef.current || queueRef.current.length === 0 || !available) return
    processingRef.current = true
    const generation = generationRef.current
    try {
      while (queueRef.current.length > 0 && generation === generationRef.current) {
        const messageId = queueRef.current.shift()!
        setQueueLength(queueRef.current.length)
        setCurrentMessageId(messageId)
        setStatus('synthesizing')
        setError('')
        const controller = new AbortController()
        abortRef.current = controller
        if (!roomId || !accountToken || !reconnectToken) throw new Error('缺少房间语音身份凭证')
        const manifest = await sdk.rooms.getHostSpeechManifest(
          roomId, messageId, accountToken, reconnectToken, controller.signal,
        )
        setCurrentSentences(manifest.sentences)
        // 最多保留当前句和下一句：当前句开始播放前触发下一句请求，减少句间停顿，
        // 又不会把整段叙事提前合成、在用户停止或切换音色时浪费 Provider 费用。
        let nextUrl: Promise<string> | null = manifest.sentences.length
          ? fetchSentence(messageId, 0, controller.signal)
          : null
        try {
          for (let index = 0; index < manifest.sentences.length; index += 1) {
            setCurrentSentenceIndex(index)
            const currentUrl = await nextUrl!
            nextUrl = index + 1 < manifest.sentences.length
              ? fetchSentence(messageId, index + 1, controller.signal)
              : null
            await playUrl(currentUrl, generation)
            revokeUrl(currentUrl)
          }
        } finally {
          // 当前句播放失败时，下一句的预取可能已经完成；显式等待并释放它，
          // 避免悬空 Promise 的拒绝告警和 Blob URL 泄漏。
          if (nextUrl) {
            try { revokeUrl(await nextUrl) } catch { /* 取消/上游失败由外层统一展示。 */ }
          }
        }
        clearCurrent()
      }
      if (generation === generationRef.current) setStatus('idle')
    } catch (caught) {
      if (generation === generationRef.current && !(caught instanceof DOMException && caught.name === 'AbortError')) {
        queueRef.current = []
        setQueueLength(0)
        setError(friendlyErrorMessage(caught, '主持人语音播放失败，请手动重播'))
        setStatus('failed')
        clearCurrent()
      }
    } finally {
      if (generation === generationRef.current) {
        processingRef.current = false
        abortRef.current = null
        if (queueRef.current.length > 0) processQueueRef.current()
      }
    }
  }, [accountToken, available, clearCurrent, fetchSentence, playUrl, reconnectToken, revokeUrl, roomId])

  processQueueRef.current = () => { void processQueue() }

  const markSeen = useCallback((messageIds: readonly string[]) => {
    for (const id of messageIds) if (id.trim()) seenRef.current.add(id.trim())
  }, [])

  const enqueue = useCallback((messageId: string | undefined) => {
    if (!enabledRef.current || !messageId || seenRef.current.has(messageId)) return
    seenRef.current.add(messageId)
    // 设置 GET 尚未返回时先保留权威 ID，避免进入页面后第一句因竞态被吞掉；
    // 已明确 disabled 时则保持纯文本，不积压一个永远无法消费的队列。
    if (!credentialsReady || settings?.available === false) return
    queueRef.current.push(messageId)
    setQueueLength(queueRef.current.length)
    processQueueRef.current()
  }, [credentialsReady, settings?.available])

  const replay = useCallback((messageId: string | undefined) => {
    if (!available || !messageId) return
    queueRef.current.push(messageId)
    setQueueLength(queueRef.current.length)
    processQueueRef.current()
  }, [available])

  const setEnabled = useCallback((next: boolean) => {
    enabledRef.current = next
    setEnabledState(next)
    if (!next) stop()
  }, [stop])

  const setPlaybackRate = useCallback((next: number) => {
    const value = clamp(next, 0.75, 1.25)
    rateRef.current = value
    setPlaybackRateState(value)
    if (audioRef.current) audioRef.current.playbackRate = value
  }, [])

  const setVolume = useCallback((next: number) => {
    const value = clamp(next, 0, 1)
    volumeRef.current = value
    setVolumeState(value)
    if (audioRef.current) audioRef.current.volume = value
  }, [])

  const pause = useCallback(() => {
    if (status !== 'playing') return
    audioRef.current?.pause()
    setStatus('paused')
  }, [status])

  const resume = useCallback(() => {
    if (status !== 'paused' || !audioRef.current) return
    void audioRef.current.play().then(() => setStatus('playing')).catch((caught) => {
      setError(friendlyErrorMessage(caught, '浏览器阻止了音频播放，请再次点击继续'))
      setStatus('failed')
    })
  }, [status])

  const updateVoice = useCallback(async (voiceType: string) => {
    if (!roomId || !accountToken || !reconnectToken) return
    stop()
    const updated = await sdk.rooms.updateHostSpeechSettings(
      roomId, voiceType, accountToken, reconnectToken,
    )
    setSettings(updated)
  }, [accountToken, reconnectToken, roomId, stop])

  const handleSettingsUpdated = useCallback((voiceType: string | null) => {
    stop()
    setSettings((current) => current ? { ...current, voiceType } : current)
  }, [stop])

  useEffect(() => {
    writeSettings({ version: 2, enabled, playbackRate, volume })
  }, [enabled, playbackRate, volume])

  useEffect(() => {
    stop()
    if (!roomId || !accountToken || !reconnectToken) {
      setSettings(null)
      return
    }
    const controller = new AbortController()
    void sdk.rooms.getHostSpeechSettings(
      roomId, accountToken, reconnectToken, controller.signal,
    ).then(setSettings).catch((caught) => {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setSettings({ available: false, provider: 'disabled', voiceType: null, voices: [], autoEmotion: true })
        setError(friendlyErrorMessage(caught, '主持人语音设置加载失败'))
      }
    })
    return () => controller.abort()
  }, [accountToken, reconnectToken, roomId, stop])

  useEffect(() => {
    if (available && queueRef.current.length > 0) processQueueRef.current()
  }, [available])

  useEffect(() => () => stop(), [stop])

  return {
    available,
    provider: settings?.provider ?? 'disabled',
    voices: settings?.voices ?? [] as HostSpeechVoiceRead[],
    voiceType: settings?.voiceType ?? null,
    autoEmotion: settings?.autoEmotion ?? true,
    enabled,
    setEnabled,
    playbackRate,
    setPlaybackRate,
    volume,
    setVolume,
    status,
    queueLength,
    currentMessageId,
    currentSentenceIndex,
    currentSentences,
    error,
    markSeen,
    enqueue,
    replay,
    pause,
    resume,
    stop,
    updateVoice,
    handleSettingsUpdated,
  }
}
