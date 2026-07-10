import type { ReactNode } from 'react'

interface PhoneLayoutProps {
  children: ReactNode
}

export default function PhoneLayout({ children }: PhoneLayoutProps) {
  return (
    <>
      <div className="status-bar">
        <span>9:41</span>
        <span className="mono">🔋 ████</span>
      </div>
      <main className="animate-screen-in">{children}</main>
    </>
  )
}
