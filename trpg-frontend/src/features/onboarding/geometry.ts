export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

interface RootFrame extends Rect {
  borderLeft: number
  borderTop: number
  clientWidth: number
  clientHeight: number
}

export function calculateSpotlightRect(
  target: Rect,
  root: RootFrame,
): Rect | null {
  const layoutWidth = root.clientWidth + root.borderLeft * 2
  const layoutHeight = root.clientHeight + root.borderTop * 2
  const scaleX = layoutWidth > 0 ? root.width / layoutWidth : 1
  const scaleY = layoutHeight > 0 ? root.height / layoutHeight : 1
  const rootLeft = root.left + root.borderLeft * scaleX
  const rootTop = root.top + root.borderTop * scaleY
  const rawLeft = (target.left - rootLeft) / scaleX
  const rawTop = (target.top - rootTop) / scaleY
  const targetWidth = target.width / scaleX
  const targetHeight = target.height / scaleY
  const visibleLeft = Math.max(0, Math.min(rawLeft, root.clientWidth))
  const visibleTop = Math.max(0, Math.min(rawTop, root.clientHeight))
  const visibleRight = Math.max(0, Math.min(rawLeft + targetWidth, root.clientWidth))
  const visibleBottom = Math.max(0, Math.min(rawTop + targetHeight, root.clientHeight))

  if (visibleRight <= visibleLeft || visibleBottom <= visibleTop) return null

  return {
    left: visibleLeft,
    top: visibleTop,
    width: visibleRight - visibleLeft,
    height: visibleBottom - visibleTop,
  }
}
