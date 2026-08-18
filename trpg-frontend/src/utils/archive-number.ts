export function archiveNumber(userId: string | null): string {
  if (!userId) return '----'

  let hash = 0
  for (const character of userId) {
    hash = (hash * 31 + character.charCodeAt(0)) % 10_000
  }
  return hash.toString().padStart(4, '0')
}
