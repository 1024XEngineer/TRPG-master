import type { ReactNode } from 'react'

type BadgeVariant = 'success' | 'info' | 'default' | 'warning'

interface BadgeProps {
  variant?: BadgeVariant
  children: ReactNode
}

const variantStyles: Record<BadgeVariant, string> = {
  success: 'bg-[rgba(74,138,74,0.12)] text-mold',
  info: 'bg-[rgba(74,112,152,0.12)] text-ink-blue',
  default: 'bg-[rgba(138,130,118,0.12)] text-text-muted',
  warning: 'bg-[rgba(184,151,106,0.12)] text-brass-dark',
}

export default function Badge({ variant = 'default', children }: BadgeProps) {
  return (
    <span className={`inline-block px-[10px] py-[2px] rounded-[99px] text-[10px] font-semibold ${variantStyles[variant]}`}>
      {children}
    </span>
  )
}
