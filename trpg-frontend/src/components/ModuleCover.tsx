import type { ImgHTMLAttributes } from 'react'

export const MODULE_ASSET_ROOT = '/assets/rooms/scenarios'
export const DEFAULT_MODULE_COVER = `${MODULE_ASSET_ROOT}/cover-default.webp`

const MODULE_COVERS: Record<string, string> = {
  'paper-chase-zh-coc7': `${MODULE_ASSET_ROOT}/cover-paper-chase.webp`,
}

export function moduleCover(moduleId: string): string {
  return MODULE_COVERS[moduleId] ?? DEFAULT_MODULE_COVER
}

export function hasDedicatedModuleCover(moduleId: string): boolean {
  return Boolean(MODULE_COVERS[moduleId])
}

interface ModuleCoverProps {
  moduleId: string
  title: string
  className?: string
  imageClassName?: string
  frameClassName?: string
  framed?: boolean
  imageProps?: Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt' | 'className' | 'onError'>
}

export function ModuleCover({
  moduleId,
  title,
  className = '',
  imageClassName = '',
  frameClassName = '',
  framed = true,
  imageProps,
}: ModuleCoverProps) {
  const usesDefaultCover = !hasDedicatedModuleCover(moduleId)

  return (
    <span className={`${className}${usesDefaultCover ? ' is-default-cover' : ''}`.trim()}>
      <img
        {...imageProps}
        className={imageClassName}
        src={moduleCover(moduleId)}
        alt={`${title}模组封面`}
        onError={(event) => {
          if (!event.currentTarget.src.endsWith(DEFAULT_MODULE_COVER)) {
            event.currentTarget.src = DEFAULT_MODULE_COVER
          }
        }}
      />
      {framed && (
        <img
          className={frameClassName}
          src={`${MODULE_ASSET_ROOT}/cover-frame.webp`}
          alt=""
          aria-hidden="true"
        />
      )}
    </span>
  )
}
