/**
 * 可点击的角色头像与全屏大图预览；统一处理遮罩、Esc 和无障碍关闭入口。
 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface PortraitImageProps {
  src: string
  alt: string
  buttonClassName?: string
  imageClassName?: string
}

/**
 * 渲染可点击头像，并通过 Portal 打开不受父容器裁剪影响的全屏大图。
 */
export function PortraitImage({
  src,
  alt,
  buttonClassName = '',
  imageClassName = '',
}: PortraitImageProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const trigger = triggerRef.current
    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()

    // 模态打开期间把 Tab 循环限制在对话框内，避免键盘焦点进入遮罩后的游戏页面。
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        return
      }
      if (event.key !== 'Tab') return

      const dialog = dialogRef.current
      if (!dialog) return
      const focusableElements = [...dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )]
      if (focusableElements.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const first = focusableElements[0]
      const last = focusableElements[focusableElements.length - 1]
      const activeElement = document.activeElement
      if (event.shiftKey && (activeElement === first || !dialog.contains(activeElement))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (activeElement === last || !dialog.contains(activeElement))) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousBodyOverflow
      trigger?.focus()
    }
  }, [open])

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={`查看${alt}大图`}
        title="点击查看大图"
        onClick={() => setOpen(true)}
        className={`block cursor-zoom-in overflow-hidden border-0 bg-transparent p-0 ${buttonClassName}`}
      >
        <img src={src} alt={alt} className={imageClassName} />
      </button>

      {open &&
        createPortal(
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label={`${alt}大图`}
            tabIndex={-1}
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4 animate-fade-in"
            onClick={() => setOpen(false)}
          >
            <div
              className="relative flex max-h-full max-w-full items-center justify-center"
              onClick={(event) => event.stopPropagation()}
            >
              <img
                src={src}
                alt={`${alt}大图`}
                className="max-h-[88vh] max-w-[92vw] rounded-lg object-contain shadow-2xl"
              />
              <button
                ref={closeButtonRef}
                type="button"
                aria-label="关闭头像大图"
                title="关闭"
                onClick={() => setOpen(false)}
                className="absolute right-2 top-2 flex h-10 w-10 items-center justify-center rounded-full bg-black/65 text-white backdrop-blur-sm transition-colors hover:bg-black/80"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
