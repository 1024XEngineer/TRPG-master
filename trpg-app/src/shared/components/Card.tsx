import type { HTMLAttributes, ReactNode } from 'react'

type CardVariant = 'game' | 'player' | 'system' | 'section'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant
  children: ReactNode
}

const variantStyles: Record<CardVariant, string> = {
  game: 'bg-card border border-border-light rounded-md p-5 text-center cursor-pointer active:scale-[0.96] transition-all duration-200',
  player: 'flex items-center gap-3 px-3.5 py-3 bg-card border border-border-light rounded-md',
  system: 'bg-card border border-border-light rounded-md p-5 cursor-pointer flex items-center gap-4 active:scale-[0.98] transition-all duration-200',
  section: 'bg-card border border-border-light rounded-md p-[18px]',
}

export default function Card({
  variant = 'section',
  children,
  className = '',
  ...props
}: CardProps) {
  return (
    <div className={`${variantStyles[variant]} ${className}`} {...props}>
      {children}
    </div>
  )
}
