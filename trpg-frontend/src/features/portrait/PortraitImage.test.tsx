/** 验证角色头像可打开大图，并支持关闭按钮、遮罩与 Esc 退出。 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PortraitImage } from './PortraitImage'

describe('PortraitImage', () => {
  afterEach(cleanup)

  it('点击头像打开大图并可按 Esc 关闭', () => {
    render(
      <PortraitImage
        src="blob:portrait"
        alt="成吉思鸡的头像"
        imageClassName="h-full w-full"
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '查看成吉思鸡的头像大图' }))
    expect(screen.getByRole('dialog', { name: '成吉思鸡的头像大图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '成吉思鸡的头像大图' })).toHaveAttribute(
      'src',
      'blob:portrait',
    )

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('点击关闭按钮退出大图', () => {
    render(<PortraitImage src="blob:portrait" alt="调查员的头像" />)
    fireEvent.click(screen.getByRole('button', { name: '查看调查员的头像大图' }))
    fireEvent.click(screen.getByRole('button', { name: '关闭头像大图' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
