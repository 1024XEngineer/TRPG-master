import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  onBack?: () => void
  right?: React.ReactNode
}

export default function PageHeader({ title, subtitle, onBack, right }: PageHeaderProps) {
  const navigate = useNavigate()

  const handleBack = () => {
    if (onBack) {
      onBack()
    } else {
      navigate(-1)
    }
  }

  return (
    <div className="flex items-center gap-2.5 px-5 pb-3 pt-1">
      <button
        onClick={handleBack}
        className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150"
      >
        <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
      </button>
      <div className="flex-1 min-w-0">
        <h2 className="text-lg font-bold text-text-primary truncate">{title}</h2>
        {subtitle && <p className="text-xs text-text-muted">{subtitle}</p>}
      </div>
      {right && <div className="flex-shrink-0">{right}</div>}
    </div>
  )
}
