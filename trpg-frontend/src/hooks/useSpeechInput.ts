import { useCallback, useEffect, useRef, useState } from 'react'

// TypeScript 的 DOM lib 尚未统一收录各浏览器的 SpeechRecognition 类型，且
// Chromium 仍可能只暴露 webkit 前缀实现。这里声明实际使用的最小契约，避免
// 引入与浏览器运行时不一致的第三方类型包。
export type SpeechInputStatus =
  | 'unsupported'
  | 'idle'
  | 'requesting_permission'
  | 'listening'
  | 'processing'
  | 'failed'

interface SpeechRecognitionAlternativeLike {
  transcript: string
}

interface SpeechRecognitionResultLike extends ArrayLike<SpeechRecognitionAlternativeLike> {
  isFinal?: boolean
}

interface SpeechRecognitionEventLike {
  resultIndex?: number
  results: ArrayLike<SpeechRecognitionResultLike>
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onstart: (() => void) | null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

interface SpeechCapability {
  ctor: SpeechRecognitionCtor | null
  unavailableReason: string | null
}

function getSpeechCapability(): SpeechCapability {
  if (typeof window === 'undefined') {
    return { ctor: null, unavailableReason: '当前环境不支持语音输入' }
  }
  // 纯 HTTP IP 页面即使暴露了构造器，也无法可靠取得麦克风权限。localhost
  // 被浏览器视为安全来源，因此本地开发仍可直接使用。
  if (window.isSecureContext === false) {
    return {
      ctor: null,
      unavailableReason: '当前页面不是安全连接，请使用 HTTPS 或 localhost 访问',
    }
  }
  const speechWindow = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  const ctor = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null
  return {
    ctor,
    unavailableReason: ctor ? null : '当前浏览器不支持语音输入，请继续使用键盘输入',
  }
}

function speechErrorMessage(code: string): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return '麦克风权限被拒绝，请在浏览器设置中允许后重试'
    case 'audio-capture':
      return '没有找到可用的麦克风'
    case 'no-speech':
      return '没有识别到语音，请重试'
    case 'network':
      return '浏览器语音识别服务网络异常，请稍后重试'
    case 'language-not-supported':
      return '当前浏览器不支持中文语音识别'
    default:
      return '语音识别失败，请重试或使用键盘输入'
  }
}

function detachRecognition(recognition: SpeechRecognitionLike) {
  recognition.onstart = null
  recognition.onresult = null
  recognition.onend = null
  recognition.onerror = null
}

/**
 * 浏览器语音输入适配层。房间 UI 只依赖这里的状态和最终文本，未来增加
 * Paraformer 时可以替换 Provider，而不需要把浏览器事件散落到输入组件中。
 */
export function useSpeechInput(onTranscript: (text: string) => void) {
  // 能力在页面生命周期内不会变化，只在首次渲染探测一次，避免渲染过程中因为
  // 全局对象差异在 supported/unsupported 之间跳动。
  const [capability] = useState(getSpeechCapability)
  const [status, setStatus] = useState<SpeechInputStatus>(
    capability.ctor ? 'idle' : 'unsupported',
  )
  const [error, setError] = useState<string | null>(null)
  // ref 同时充当 single-flight 锁：一个实例结束或取消前，重复点击 start 不会
  // 再申请一次麦克风权限，也不会创建相互竞争的识别会话。
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  // acceptingResults 是取消闸门；finalResults 按浏览器 resultIndex 暂存最终片段。
  // 两者都不用 state，避免每个语音事件触发 React 重渲染。
  const acceptingResultsRef = useRef(false)
  const finalResultsRef = useRef(new Map<number, string>())
  // 调用方回调可能随输入框/频道状态更新；ref 保证浏览器异步事件总能调用最新版。
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript

  const release = useCallback((recognition: SpeechRecognitionLike) => {
    if (recognitionRef.current === recognition) recognitionRef.current = null
    detachRecognition(recognition)
    acceptingResultsRef.current = false
    finalResultsRef.current.clear()
  }, [])

  useEffect(() => () => {
    const recognition = recognitionRef.current
    if (!recognition) return
    // 卸载时先拒收迟到结果，再解绑事件。某些实现会在 abort 后继续派发 end/error。
    acceptingResultsRef.current = false
    recognitionRef.current = null
    detachRecognition(recognition)
    try {
      recognition.abort()
    } catch {
      // 页面已经离开，浏览器实例的清理异常无需再反馈给已卸载的 UI。
    }
  }, [])

  const start = useCallback(() => {
    const Ctor = capability.ctor
    if (!Ctor || recognitionRef.current) return

    setError(null)
    setStatus('requesting_permission')
    acceptingResultsRef.current = true
    finalResultsRef.current.clear()

    const recognition = new Ctor()
    recognition.lang = 'zh-CN'
    recognition.continuous = false
    recognition.interimResults = false
    recognitionRef.current = recognition

    recognition.onstart = () => {
      if (recognitionRef.current === recognition) setStatus('listening')
    }
    recognition.onresult = (event) => {
      if (!acceptingResultsRef.current || recognitionRef.current !== recognition) return
      const firstIndex = event.resultIndex ?? 0
      for (let index = firstIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        // 即便 interimResults=false，仍有实现可能派发临时结果；只接受 final，
        // 并用 resultIndex 去重浏览器重复派发的累计结果。
        if (result.isFinal === false || finalResultsRef.current.has(index)) continue
        const transcript = result[0]?.transcript?.trim()
        if (transcript) finalResultsRef.current.set(index, transcript)
      }
    }
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return
      // 浏览器通常先派发 result 再派发 end。等到正常结束才一次性提交，保证用户
      // 即使在两事件之间点击取消，也能真正丢弃本轮的全部识别结果。
      const transcript = acceptingResultsRef.current
        ? [...finalResultsRef.current.entries()]
            .sort(([left], [right]) => left - right)
            .map(([, text]) => text)
            .join('')
        : ''
      release(recognition)
      if (transcript) onTranscriptRef.current(transcript)
      setStatus('idle')
    }
    recognition.onerror = (event) => {
      if (recognitionRef.current !== recognition) return
      release(recognition)
      setError(speechErrorMessage(event.error))
      setStatus('failed')
    }

    try {
      recognition.start()
    } catch {
      release(recognition)
      setError('无法启动语音识别，请重试或使用键盘输入')
      setStatus('failed')
    }
  }, [capability.ctor, release])

  const stop = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) return
    // stop 会要求浏览器完成当前识别，并由后续 onend 提交已暂存的最终文本；
    // cancel 则会关闭结果闸门并 abort，两条路径不能合并。
    setStatus('processing')
    try {
      recognition.stop()
    } catch {
      release(recognition)
      setError('无法停止语音识别，请重试或使用键盘输入')
      setStatus('failed')
    }
  }, [release])

  const cancel = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) {
      if (capability.ctor) {
        setError(null)
        setStatus('idle')
      }
      return
    }
    // cancel 与 stop 的关键区别：先关闭结果闸门，确保 abort 之后到达的转写不会
    // 写进已切换频道、已发送或已卸载页面的输入框。
    acceptingResultsRef.current = false
    release(recognition)
    setError(null)
    setStatus('idle')
    try {
      recognition.abort()
    } catch {
      // 已经完成的浏览器实例无需继续处理。
    }
  }, [capability.ctor, release])

  return {
    supported: capability.ctor !== null,
    unavailableReason: capability.unavailableReason,
    status,
    error,
    start,
    stop,
    cancel,
  }
}
