// 语音输入 hook（issue #107）：用浏览器自带的 Web Speech API 把语音转成文字。
//
// 设计要点：
// - 转写完全发生在客户端，转写出的文本交给调用方填进输入框，之后跟手动打字
//   走完全相同的发送路径——后端只收文本，不知道也不需要知道这段话是打的还是
//   说的，协议零改动（issue #107 关键决策：语音输入客户端转写）。
// - SpeechRecognition 是浏览器原生能力，Chrome/Edge 用 webkit 前缀，部分
//   浏览器（Firefox、老 Safari）不支持——不支持时 `supported` 为 false，
//   调用方隐藏/禁用麦克风按钮即可，不报错、不影响打字。
// - 单次识别模式（continuous=false）：点一下说一句，说完自动停止。比连续
//   听写简单可控，也避免麦克风一直开着的隐私顾虑。

import { useCallback, useEffect, useRef, useState } from 'react'

// TS 的 DOM lib 还没有收录 SpeechRecognition 的标准类型（各浏览器实现差异
// 仍在），这里只声明用到的最小面。
interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export function useSpeechInput(onTranscript: (text: string) => void) {
  const [supported] = useState(() => getSpeechRecognitionCtor() !== null)
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  // onTranscript 存 ref：识别是异步回调，直接闭包引用会拿到旧的回调实例
  // （比如切换了频道后仍把文本发到旧频道的 setter 上）。
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort()
    }
  }, [])

  const start = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor || recognitionRef.current) return
    const recognition = new Ctor()
    recognition.lang = 'zh-CN'
    recognition.continuous = false
    recognition.interimResults = false
    recognition.onresult = (event) => {
      const transcript = Array.from({ length: event.results.length }, (_, i) => event.results[i])
        .map((result) => result[0]?.transcript ?? '')
        .join('')
      if (transcript) onTranscriptRef.current(transcript)
    }
    recognition.onend = () => {
      recognitionRef.current = null
      setListening(false)
    }
    recognition.onerror = () => {
      // 权限被拒/无语音输入等都走这里：安静地结束，回到可重试状态。
      // 不弹错误——语音只是打字的替代输入方式，失败的兜底就是打字。
      recognitionRef.current = null
      setListening(false)
    }
    recognitionRef.current = recognition
    setListening(true)
    recognition.start()
  }, [])

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  return { supported, listening, start, stop }
}
