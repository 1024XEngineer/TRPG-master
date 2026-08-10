/** 验证角色头像可打开大图，并支持关闭按钮、遮罩与 Esc 退出。 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PortraitImage } from './PortraitImage'

describe('PortraitImage', () => {
  afterEach(cleanup)

  it('打开后锁定滚动并将焦点移入，按 Esc 关闭后恢复焦点', () => {
    render(
      <PortraitImage
        src="blob:portrait"
        alt="成吉思鸡的头像"
        imageClassName="h-full w-full"
      />,
    )

    const trigger = screen.getByRole('button', { name: '查看成吉思鸡的头像大图' })
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog', { name: '成吉思鸡的头像大图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '成吉思鸡的头像大图' })).toHaveAttribute(
      'src',
      'blob:portrait',
    )
    expect(screen.getByRole('button', { name: '关闭头像大图' })).toHaveFocus()
    expect(document.body.style.overflow).toBe('hidden')

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(document.body.style.overflow).toBe('')
  })

  it('点击关闭按钮退出大图', () => {
    render(<PortraitImage src="blob:portrait" alt="调查员的头像" />)
    fireEvent.click(screen.getByRole('button', { name: '查看调查员的头像大图' }))
    fireEvent.click(screen.getByRole('button', { name: '关闭头像大图' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Tab 焦点不会离开头像大图', () => {
    render(
      <>
        <button type="button">背景按钮</button>
        <PortraitImage src="blob:portrait" alt="调查员的头像" />
      </>,
    )
    fireEvent.click(screen.getByRole('button', { name: '查看调查员的头像大图' }))
    const closeButton = screen.getByRole('button', { name: '关闭头像大图' })

    screen.getByRole('button', { name: '背景按钮' }).focus()
    fireEvent.keyDown(window, { key: 'Tab' })
    expect(closeButton).toHaveFocus()

    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true })
    expect(closeButton).toHaveFocus()
  })
})
