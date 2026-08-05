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
  const rootLeft = root.left + root.borderLeft
  const rootTop = root.top + root.borderTop
  const rawLeft = target.left - rootLeft
  const rawTop = target.top - rootTop
  const visibleLeft = Math.max(0, Math.min(rawLeft, root.clientWidth))
  const visibleTop = Math.max(0, Math.min(rawTop, root.clientHeight))
  const visibleRight = Math.max(0, Math.min(rawLeft + target.width, root.clientWidth))
  const visibleBottom = Math.max(0, Math.min(rawTop + target.height, root.clientHeight))

  if (visibleRight <= visibleLeft || visibleBottom <= visibleTop) return null

  return {
    left: visibleLeft,
    top: visibleTop,
    width: visibleRight - visibleLeft,
    height: visibleBottom - visibleTop,
  }
}
