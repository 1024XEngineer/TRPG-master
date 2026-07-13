import type { ButtonHTMLAttributes, ReactNode } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'outline'
type ButtonSize = 'default' | 'sm'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  block?: boolean
  icon?: ReactNode
  children: ReactNode
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-brass text-white active:bg-brass-dark',
  secondary: 'bg-card text-text-body border border-border-mid active:bg-panel',
  outline: 'bg-transparent text-brass-dark border border-brass',
}

const sizeStyles: Record<ButtonSize, string> = {
  default: 'px-6 py-3.5 text-sm font-semibold',
  sm: 'px-4 py-2.5 text-xs font-semibold',
}

export default function Button({
  variant = 'primary',
  size = 'default',
  block = false,
  icon,
  children,
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      className={`
        inline-flex items-center justify-center gap-2 rounded-sm
        transition-all duration-150 select-none
        active:scale-[0.97]
        font-sans
        ${variantStyles[variant]}
        ${sizeStyles[size]}
        ${block ? 'w-full' : ''}
        ${className}
      `}
      {...props}
    >
      {icon && <span className="w-[18px] h-[18px]">{icon}</span>}
      {children}
    </button>
  )
}
