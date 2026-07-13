import type { ReactNode } from 'react'

interface PhoneLayoutProps {
  children: ReactNode
}

export default function PhoneLayout({ children }: PhoneLayoutProps) {
  return (
      <main className="animate-screen-in">{children}</main>
  )
}
