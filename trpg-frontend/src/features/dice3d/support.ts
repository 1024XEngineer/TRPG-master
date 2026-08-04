/**
 * 3D 骰子的可用性探测（issue #217）。
 *
 * 检定是主流程的一环，不能因为渲染能力缺失就卡住。这两个判断决定是否回退到
 * 原有的 2D 数字展示——回退路径必须始终可用。
 *
 * 这里不 import three：调用方要先用它决定「值不值得动态加载 three」，
 * 所以它自己必须是零依赖的。
 */

/** WebGL 是否可用。老旧移动端浏览器、部分隐私模式下会拿不到 context。 */
export function isWebGLAvailable(): boolean {
  if (typeof document === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    const gl =
      canvas.getContext('webgl2') ??
      canvas.getContext('webgl') ??
      canvas.getContext('experimental-webgl')
    return gl !== null
  } catch {
    // 某些环境下取 context 会直接抛异常，等同不可用。
    return false
  }
}

/** 用户是否要求减少动态效果（无障碍偏好）。 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 三者合一：当前环境是否应该走 3D。 */
export function supports3DDice(): boolean {
  return isWebGLAvailable() && !prefersReducedMotion()
}
