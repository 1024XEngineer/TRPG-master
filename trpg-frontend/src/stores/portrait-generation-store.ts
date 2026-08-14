/** 跨路由保存角色生图任务、头像版本覆盖和非阻塞通知。 */
import { create } from 'zustand'
import type { PortraitGenerationTaskRead } from 'trpg-sdk'

export type PortraitNotice = { id: string; message: string; tone: 'success' | 'error' | 'neutral' }
const active = new Set(['queued', 'generating', 'cancelling'])
const keyOf = (roomId: string, characterId: string) => `${roomId}/${characterId}`
const WATCHED_KEY = 'aidm-portrait-watched'
const NOTIFIED_KEY = 'aidm-portrait-notified'
const storedIds = (key: string): Set<string> => {
  try { return new Set(JSON.parse(sessionStorage.getItem(key) ?? '[]') as string[]) }
  catch { return new Set() }
}
const saveIds = (key: string, values: Set<string>) => {
  try { sessionStorage.setItem(key, JSON.stringify([...values].slice(-50))) } catch { /* 存储不可用不影响任务权威状态。 */ }
}

interface State {
  tasks: Record<string, PortraitGenerationTaskRead | null>
  cancelling: Record<string, boolean>
  portraitVersions: Record<string, string>
  notices: PortraitNotice[]
  setTask: (roomId: string, characterId: string, task: PortraitGenerationTaskRead | null, notify?: boolean) => void
  setCancelling: (roomId: string, characterId: string, value: boolean) => void
  dismissNotice: (id: string) => void
  clearPortraitVersion: (roomId: string) => void
}

export const usePortraitGenerationStore = create<State>((set) => ({
  tasks: {}, cancelling: {}, portraitVersions: {}, notices: [],
  setTask: (roomId, characterId, task, notify = false) => set((state) => {
    const key = keyOf(roomId, characterId)
    const previous = state.tasks[key]
    const notices = [...state.notices]
    const watched = storedIds(WATCHED_KEY)
    const notified = storedIds(NOTIFIED_KEY)
    if (task && active.has(task.status)) { watched.add(task.generationId); saveIds(WATCHED_KEY, watched) }
    const shouldNotify = task && !active.has(task.status) && !notified.has(task.generationId)
      && (notify || watched.has(task.generationId)) && previous?.status !== task.status
    if (shouldNotify && task) {
      const message = task.status === 'completed' ? '人物图片生成完成'
        : task.status === 'cancelled' ? '人物图片生成已终止' : '人物图片生成失败'
      notices.push({ id: task.generationId, message, tone: task.status === 'completed' ? 'success' : task.status === 'failed' ? 'error' : 'neutral' })
      notified.add(task.generationId); watched.delete(task.generationId)
      saveIds(NOTIFIED_KEY, notified); saveIds(WATCHED_KEY, watched)
    }
    return {
      tasks: { ...state.tasks, [key]: task },
      portraitVersions: task?.status === 'completed' && task.portraitVersion
        ? { ...state.portraitVersions, [roomId]: task.portraitVersion }
        : state.portraitVersions,
      notices,
    }
  }),
  setCancelling: (roomId, characterId, value) => set((state) => ({ cancelling: { ...state.cancelling, [keyOf(roomId, characterId)]: value } })),
  dismissNotice: (id) => set((state) => ({ notices: state.notices.filter((item) => item.id !== id) })),
  clearPortraitVersion: (roomId) => set((state) => {
    const versions = { ...state.portraitVersions }; delete versions[roomId]
    return { portraitVersions: versions }
  }),
}))

export const portraitTaskKey = keyOf
export const isPortraitTaskActive = (task: PortraitGenerationTaskRead | null | undefined) => !!task && active.has(task.status)
