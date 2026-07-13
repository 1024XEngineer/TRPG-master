import { create } from 'zustand'
import type { Attributes, InvestigatorInfo } from '@/data/character-model'

export interface CompletedCharacter {
  info: InvestigatorInfo
  attr: Attributes
  skillAlloc: Record<string, number>
  equipment: string
  background: string
  notes: string
  derived: { hp: number; san: number; mp: number; db: string; move: number }
}

interface CharacterState {
  character: CompletedCharacter | null
  setCharacter: (c: CompletedCharacter) => void
  clear: () => void
}

export const useCharacterStore = create<CharacterState>((set) => ({
  character: null,
  setCharacter: (character) => set({ character }),
  clear: () => set({ character: null }),
}))
