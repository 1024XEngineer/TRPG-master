import type { ReactNode } from 'react'
import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

interface PhoneLayoutProps {
  children: ReactNode
}

export default function PhoneLayout({ children }: PhoneLayoutProps) {
  const mainRef = useRef<HTMLElement>(null)
  const { pathname } = useLocation()

  // <main> 是横跨所有路由、从不重新挂载的滚动容器——SPA 导航不像整页跳转
  // 那样会自动把滚动位置归零。上一页往下滑过之后再切页，新页面会直接
  // 顶着那个滚动偏移渲染，看起来像是内容"消失"了、面板位置不对。
  useEffect(() => {
    mainRef.current?.scrollTo(0, 0)
  }, [pathname])

  return (
      <main ref={mainRef} className="animate-screen-in h-full overflow-y-auto overflow-x-hidden">{children}</main>
  )
}
