import { ChevronDown } from 'lucide-react'
import { useId, type ReactNode } from 'react'

export function UnreadDot() {
  return <span className="room-play__unread-dot" role="img" aria-label="有新增内容" />
}

export function InformationDisclosure({
  title, expanded, onToggle, unread = false, children, actions,
}: {
  title: string
  expanded: boolean
  onToggle: () => void
  unread?: boolean
  children: ReactNode
  actions?: ReactNode
}) {
  const contentId = useId()
  return (
    <section className="room-play__information-section">
      <div className="room-play__information-section-header">
        <button
          type="button"
          className="room-play__information-summary"
          aria-label={title}
          aria-description={unread ? '有新增内容' : undefined}
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={onToggle}
        >
          <span className="room-play__information-name"><span className="room-play__information-text">{title}</span>{unread && <UnreadDot />}</span>
          <ChevronDown aria-hidden="true" className={expanded ? 'is-expanded' : ''} />
        </button>
        {actions && <div className="room-play__information-actions">{actions}</div>}
      </div>
      <div id={contentId} hidden={!expanded} className="room-play__information-content">
        {children}
      </div>
    </section>
  )
}

export function InformationSection({
  title, unread = false, children, actions,
}: {
  title: string
  unread?: boolean
  children: ReactNode
  actions?: ReactNode
}) {
  return (
    <section className="room-play__information-section">
      <div className="room-play__information-section-header">
        <h4 className="room-play__information-heading" aria-label={title}
          aria-description={unread ? '有新增内容' : undefined}>
          <span className="room-play__information-name"><span className="room-play__information-text">{title}</span>{unread && <UnreadDot />}</span>
        </h4>
        {actions && <div className="room-play__information-actions">{actions}</div>}
      </div>
      <div className="room-play__information-content">{children}</div>
    </section>
  )
}
