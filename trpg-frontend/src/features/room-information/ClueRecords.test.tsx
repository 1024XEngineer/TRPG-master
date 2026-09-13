import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ClueRecords } from './ClueRecords'

const information = [{ id: 'letter', title: '已知来信', summary: '来信提到墓园。' }]
const props = { roomId: 'room-1', information, isUnread: () => false }

function writeRecord(title: string, content: string) {
  fireEvent.click(screen.getByRole('button', { name: '新增记录' }))
  fireEvent.change(screen.getByRole('textbox', { name: '记录标题' }), { target: { value: title } })
  fireEvent.change(screen.getByRole('textbox', { name: '记录内容' }), { target: { value: content } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
}

describe('clues and manual records', () => {
  beforeEach(() => { localStorage.clear(); vi.clearAllMocks() })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('saves multiple records alongside clues and restores the original note without overwriting it', () => {
    localStorage.setItem('aidm-notes-room-1', '旧笔记\n保留换行与原文')
    const first = render(<ClueRecords {...props} />)
    expect(screen.getByText('旧笔记 保留换行与原文')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '新增记录' }))
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(localStorage.getItem('aidm-records-room-1')).toBeNull()
    writeRecord('核对地址', '明早去墓园核对。')
    writeRecord('联系证人', '再问一下邻居。')
    expect(screen.getByText('来信提到墓园。')).toBeVisible()
    expect(JSON.parse(localStorage.getItem('aidm-records-room-1')!).records).toHaveLength(3)
    expect(localStorage.getItem('aidm-notes-room-1')).toBe('旧笔记\n保留换行与原文')
    first.unmount()
    render(<ClueRecords {...props} />)
    expect(screen.getByText('明早去墓园核对。')).toBeVisible()
    expect(screen.getByText('再问一下邻居。')).toBeVisible()
    expect(screen.getAllByText('旧笔记 保留换行与原文')).toHaveLength(1)
  })

  it('keeps cancel separate from saving a new record', () => {
    render(<ClueRecords {...props} />)
    fireEvent.click(screen.getByRole('button', { name: '新增记录' }))
    fireEvent.change(screen.getByRole('textbox', { name: '记录内容' }), { target: { value: '未保存的推测' } })
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(localStorage.getItem('aidm-records-room-1')).toBeNull()
    expect(screen.queryByText('未保存的推测')).not.toBeInTheDocument()
  })

  it('preserves the draft on save failure and lets the user retry', () => {
    render(<ClueRecords {...props} />)
    const denied = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    writeRecord('线索推测', '不能丢失的记录')
    expect(within(screen.getByRole('form', { name: '新增记录' })).getByRole('alert')).toHaveTextContent('保存失败')
    expect(screen.getByRole('textbox', { name: '记录内容' })).toHaveValue('不能丢失的记录')
    denied.mockRestore()
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('不能丢失的记录')).toBeVisible()
  })

  it('deletes only the confirmed record and does not restore deleted legacy notes after reloading', () => {
    localStorage.setItem('aidm-notes-room-1', '原有手写内容')
    let rendered = render(<ClueRecords {...props} />)
    writeRecord('待删除', '这条推测已过时')
    writeRecord('保留记录', '还需要核实的内容')
    const before = localStorage.getItem('aidm-records-room-1')
    fireEvent.click(screen.getByRole('button', { name: '删除记录：待删除' }))
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(localStorage.getItem('aidm-records-room-1')).toBe(before)
    for (const title of ['待删除', '手写笔记']) {
      fireEvent.click(screen.getByRole('button', { name: `删除记录：${title}` }))
      fireEvent.click(within(screen.getByRole('group', { name: `确认删除记录：${title}` })).getByRole('button', { name: '确认删除' }))
    }
    expect(screen.queryByText('这条推测已过时')).not.toBeInTheDocument()
    expect(screen.getByText('还需要核实的内容')).toBeVisible()
    expect(screen.getByText('来信提到墓园。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '删除记录：已知来信' })).not.toBeInTheDocument()
    rendered.unmount()
    rendered = render(<ClueRecords {...props} />)
    expect(screen.queryByText('原有手写内容')).not.toBeInTheDocument()
    expect(screen.queryByText('这条推测已过时')).not.toBeInTheDocument()
    expect(screen.getByText('还需要核实的内容')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '删除记录：保留记录' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(JSON.parse(localStorage.getItem('aidm-records-room-1')!).records).toEqual([])
    rendered.unmount()
    render(<ClueRecords {...props} />)
    expect(screen.queryByText('原有手写内容')).not.toBeInTheDocument()
    expect(screen.queryByText('还需要核实的内容')).not.toBeInTheDocument()
    expect(localStorage.getItem('aidm-notes-room-1')).toBe('原有手写内容')
  })

  it('retains the record when deletion cannot be saved and allows retrying', () => {
    localStorage.setItem('aidm-notes-room-1', '删除失败时仍保留')
    render(<ClueRecords {...props} />)
    const denied = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    fireEvent.click(screen.getByRole('button', { name: '删除记录：手写笔记' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(screen.getByRole('alert')).toHaveTextContent('删除失败')
    expect(screen.getByText('删除失败时仍保留')).toBeVisible()
    expect(localStorage.getItem('aidm-records-room-1')).toBeNull()
    denied.mockRestore()
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('删除失败时仍保留')).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('aidm-records-room-1')!).records).toEqual([])
  })

  it('keeps records and unfinished drafts isolated when switching rooms', () => {
    const rendered = render(<ClueRecords {...props} />)
    writeRecord('第一间房', '只属于第一间房的记录')
    fireEvent.click(screen.getByRole('button', { name: '新增记录' }))
    fireEvent.change(screen.getByRole('textbox', { name: '记录内容' }), { target: { value: '第一间房的草稿' } })
    rendered.rerender(<ClueRecords {...props} roomId="room-2" />)
    expect(screen.queryByText('只属于第一间房的记录')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    writeRecord('第二间房', '只属于第二间房的记录')
    rendered.rerender(<ClueRecords {...props} />)
    expect(screen.getByText('只属于第一间房的记录')).toBeVisible()
    expect(screen.queryByText('只属于第二间房的记录')).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('aidm-records-room-2')!).records).toHaveLength(1)
  })

  it('does not overwrite unreadable saved records', () => {
    localStorage.setItem('aidm-records-room-1', 'incomplete saved data')
    render(<ClueRecords {...props} />)
    expect(screen.getByRole('alert')).toHaveTextContent('无法读取')
    fireEvent.click(screen.getByRole('button', { name: '新增记录' }))
    fireEvent.change(screen.getByRole('textbox', { name: '记录内容' }), { target: { value: '新的文字' } })
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    expect(localStorage.getItem('aidm-records-room-1')).toBe('incomplete saved data')
  })
})
