/**
 * 可点击的角色头像与全屏大图预览；统一处理遮罩、Esc 和无障碍关闭入口。
 */
import { useEffect, useState } from 'react'
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

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open])

  return (
    <>
      <button
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
            role="dialog"
            aria-modal="true"
            aria-label={`${alt}大图`}
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
