/** 全局非阻塞展示角色生图任务的终态通知。 */
import { useEffect } from 'react'
import { X } from 'lucide-react'
import { usePortraitGenerationStore } from '@/stores/portrait-generation-store'

export function PortraitGenerationNotices() {
  const notices = usePortraitGenerationStore((s) => s.notices)
  const dismiss = usePortraitGenerationStore((s) => s.dismissNotice)
  useEffect(() => {
    const timers = notices.map((notice) => window.setTimeout(() => dismiss(notice.id), 5000))
    return () => timers.forEach(window.clearTimeout)
  }, [notices, dismiss])
  return <div aria-live="polite" className="fixed right-4 top-4 z-[120] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
    {notices.map((notice) => <div key={notice.id} role="status" className="flex items-center justify-between rounded-md border border-border-mid bg-white px-4 py-3 shadow-lg">
      <span className={notice.tone === 'error' ? 'text-[#b43b3b]' : 'text-text-primary'}>{notice.message}</span>
      <button type="button" aria-label="关闭通知" onClick={() => dismiss(notice.id)}><X className="h-4 w-4" /></button>
    </div>)}
  </div>
}
