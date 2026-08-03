import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'aidm-host-speech-settings'
const DEFAULT_RATE = 1
const DEFAULT_PITCH = 1
const DEFAULT_VOLUME = 1

export type HostSpeechStatus = 'idle' | 'speaking' | 'paused'

interface HostSpeechSettings {
  enabled: boolean
  voiceURI: string | null
}

interface SpeechQueueItem {
  messageId?: string
  text: string
}

function readSettings(): HostSpeechSettings {
  if (typeof window === 'undefined') return { enabled: false, voiceURI: null }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return { enabled: false, voiceURI: null }
    const parsed = JSON.parse(raw) as Partial<HostSpeechSettings>
    return {
      enabled: parsed.enabled === true,
      voiceURI: typeof parsed.voiceURI === 'string' && parsed.voiceURI ? parsed.voiceURI : null,
    }
  } catch {
    return { enabled: false, voiceURI: null }
  }
}

function writeSettings(settings: HostSpeechSettings): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // localStorage may be unavailable in private browsing or restricted frames.
  }
}

function getSpeechSynthesis(): SpeechSynthesis | null {
  if (typeof window === 'undefined') return null
  const synthesis = window.speechSynthesis
  const utteranceCtor = (window as Window & {
    SpeechSynthesisUtterance?: typeof SpeechSynthesisUtterance
  }).SpeechSynthesisUtterance
  return synthesis && utteranceCtor ? synthesis : null
}

function getUtteranceCtor(): typeof SpeechSynthesisUtterance | null {
  if (typeof window === 'undefined') return null
  return (window as Window & {
    SpeechSynthesisUtterance?: typeof SpeechSynthesisUtterance
  }).SpeechSynthesisUtterance ?? null
}

function sortVoices(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice[] {
  return [...voices].sort((left, right) =>
    left.name.localeCompare(right.name, 'zh-CN') ||
    left.lang.localeCompare(right.lang, 'zh-CN') ||
    left.voiceURI.localeCompare(right.voiceURI, 'zh-CN'),
  )
}

function isChineseVoice(voice: SpeechSynthesisVoice): boolean {
  const lang = voice.lang.toLocaleLowerCase()
  return lang === 'zh-cn' || lang === 'zh-hans' || lang.startsWith('zh-cn-') || lang.startsWith('zh-hans-')
}

function chooseDefaultVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const sorted = sortVoices(voices)
  return sorted.find(isChineseVoice) ?? voices.find((voice) => voice.default) ?? sorted[0] ?? null
}

export function useHostSpeech() {
  const initialSettingsRef = useRef<HostSpeechSettings | null>(null)
  if (initialSettingsRef.current === null) initialSettingsRef.current = readSettings()

  const synthesisRef = useRef<SpeechSynthesis | null>(getSpeechSynthesis())
  const utteranceCtorRef = useRef<typeof SpeechSynthesisUtterance | null>(getUtteranceCtor())
  const supportedRef = useRef(synthesisRef.current !== null && utteranceCtorRef.current !== null)
  const [supported] = useState(supportedRef.current)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => {
    try {
      return synthesisRef.current ? sortVoices(synthesisRef.current.getVoices()) : []
    } catch {
      return []
    }
  })
  const [enabled, setEnabledState] = useState(() => initialSettingsRef.current?.enabled ?? false)
  const [selectedVoiceURI, setSelectedVoiceURIState] = useState<string | null>(
    () => initialSettingsRef.current?.voiceURI ?? null,
  )
  const [status, setStatus] = useState<HostSpeechStatus>('idle')
  const [queueLength, setQueueLength] = useState(0)

  const voicesRef = useRef(voices)
  const selectedVoiceURIRef = useRef(selectedVoiceURI)
  const enabledRef = useRef(enabled)
  const queueRef = useRef<SpeechQueueItem[]>([])
  const seenMessageIdsRef = useRef(new Set<string>())
  const currentRef = useRef<SpeechQueueItem | null>(null)
  const processQueueRef = useRef<() => void>(() => {})

  voicesRef.current = voices
  selectedVoiceURIRef.current = selectedVoiceURI
  enabledRef.current = enabled

  const processQueue = useCallback(() => {
    const synthesis = synthesisRef.current
    const Utterance = utteranceCtorRef.current
    if (!synthesis || !Utterance || currentRef.current || queueRef.current.length === 0) {
      if (!currentRef.current && queueRef.current.length === 0) setStatus('idle')
      return
    }

    const item = queueRef.current.shift()!
    currentRef.current = item
    setQueueLength(queueRef.current.length)
    setStatus('speaking')

    const utterance = new Utterance(item.text)
    const voice = voicesRef.current.find((candidate) => candidate.voiceURI === selectedVoiceURIRef.current)
    if (voice) {
      utterance.voice = voice
      utterance.lang = voice.lang
    }
    utterance.rate = DEFAULT_RATE
    utterance.pitch = DEFAULT_PITCH
    utterance.volume = DEFAULT_VOLUME
    const finish = () => {
      currentRef.current = null
      processQueueRef.current()
    }
    utterance.onend = finish
    utterance.onerror = finish

    try {
      synthesis.speak(utterance)
    } catch {
      finish()
    }
  }, [])

  processQueueRef.current = processQueue

  const clearPlayback = useCallback(() => {
    synthesisRef.current?.cancel()
    queueRef.current = []
    currentRef.current = null
    setQueueLength(0)
    setStatus('idle')
  }, [])

  const setEnabled = useCallback((nextEnabled: boolean) => {
    setEnabledState(nextEnabled)
    enabledRef.current = nextEnabled
    if (!nextEnabled) clearPlayback()
  }, [clearPlayback])

  const setSelectedVoiceURI = useCallback((voiceURI: string) => {
    setSelectedVoiceURIState(voiceURI || null)
    selectedVoiceURIRef.current = voiceURI || null
  }, [])

  const enqueue = useCallback((messageId: string | undefined, text: string) => {
    const trimmed = text.trim()
    if (!supportedRef.current || !enabledRef.current || !messageId || !trimmed) return
    if (seenMessageIdsRef.current.has(messageId)) return
    seenMessageIdsRef.current.add(messageId)
    queueRef.current.push({ messageId, text: trimmed })
    setQueueLength(queueRef.current.length)
    processQueueRef.current()
  }, [])

  const replay = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!supportedRef.current || !trimmed) return
    queueRef.current.push({ text: trimmed })
    setQueueLength(queueRef.current.length)
    processQueueRef.current()
  }, [])

  const pause = useCallback(() => {
    if (status !== 'speaking') return
    synthesisRef.current?.pause()
    setStatus('paused')
  }, [status])

  const resume = useCallback(() => {
    if (status !== 'paused') return
    synthesisRef.current?.resume()
    setStatus('speaking')
  }, [status])

  useEffect(() => {
    writeSettings({ enabled, voiceURI: selectedVoiceURI })
  }, [enabled, selectedVoiceURI])

  useEffect(() => {
    const synthesis = synthesisRef.current
    if (!synthesis) return

    const refreshVoices = () => {
      try {
        setVoices(sortVoices(synthesis.getVoices()))
      } catch {
        setVoices([])
      }
    }
    refreshVoices()
    synthesis.addEventListener('voiceschanged', refreshVoices)
    return () => synthesis.removeEventListener('voiceschanged', refreshVoices)
  }, [])

  useEffect(() => {
    if (voices.length === 0) return
    if (selectedVoiceURI && voices.some((voice) => voice.voiceURI === selectedVoiceURI)) return
    setSelectedVoiceURIState(chooseDefaultVoice(voices)?.voiceURI ?? null)
  }, [selectedVoiceURI, voices])

  useEffect(() => () => clearPlayback(), [clearPlayback])

  return {
    supported,
    voices,
    enabled,
    setEnabled,
    selectedVoiceURI,
    setSelectedVoiceURI,
    status,
    queueLength,
    enqueue,
    replay,
    pause,
    resume,
    stop: clearPlayback,
  }
}

export { chooseDefaultVoice, sortVoices }
