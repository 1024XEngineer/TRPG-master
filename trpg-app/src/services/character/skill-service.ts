import { ALL_SKILLS, getSkillById, type SkillDefinition } from '@/data/skills'

/**
 * SkillService — Mock service for fetching skill definitions.
 *
 * In production, swap the mock data for a real API call.
 */

const MOCK_DELAY = 150

export async function fetchSkills(): Promise<SkillDefinition[]> {
  await new Promise(r => setTimeout(r, MOCK_DELAY))
  return ALL_SKILLS
}

export async function fetchSkillById(id: string): Promise<SkillDefinition | null> {
  await new Promise(r => setTimeout(r, MOCK_DELAY))
  return getSkillById(id) ?? null
}
