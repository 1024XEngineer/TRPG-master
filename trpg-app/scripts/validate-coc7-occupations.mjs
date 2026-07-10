import fs from 'node:fs'
import path from 'node:path'

const rootDir = path.resolve(import.meta.dirname, '..')
const dataPath = path.join(rootDir, 'src/data/generated/coc7-occupations.json')
const skillsPath = path.join(rootDir, 'src/data/skills.ts')

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

function collectSkillIds() {
  const text = fs.readFileSync(skillsPath, 'utf8')
  return new Set([...text.matchAll(/id: '([^']+)'/g)].map(match => match[1]))
}

const data = readJson(dataPath)
const skills = collectSkillIds()
const occupations = data.occupations

assert(data.metadata?.sourceSheet === '职业列表', 'metadata.sourceSheet must be 职业列表')
assert(Array.isArray(occupations), 'occupations must be an array')
assert(occupations.length === 230, `expected 230 occupations, got ${occupations.length}`)
assert(new Set(occupations.map(occupation => occupation.icon)).size >= 12, 'occupation icons should vary by occupation theme')

const ids = new Set()
const excelNos = new Set()
const categories = new Map()

for (const occupation of occupations) {
  assert(Number.isInteger(occupation.id), `occupation ${occupation.name} id must be an integer`)
  assert(Number.isInteger(occupation.excelNo), `occupation ${occupation.name} excelNo must be an integer`)
  assert(!ids.has(occupation.id), `duplicate id ${occupation.id}`)
  assert(!excelNos.has(occupation.excelNo), `duplicate excelNo ${occupation.excelNo}`)
  ids.add(occupation.id)
  excelNos.add(occupation.excelNo)

  assert(typeof occupation.name === 'string' && occupation.name.trim(), `occupation ${occupation.id} needs name`)
  assert(typeof occupation.skillPoints === 'string' && occupation.skillPoints.trim(), `${occupation.name} needs skillPoints`)
  assert(occupation.pointFormula?.kind, `${occupation.name} needs parsed pointFormula`)
  assert(Array.isArray(occupation.skillIds), `${occupation.name} needs skillIds array`)
  assert(typeof occupation.skillsText === 'string' && occupation.skillsText.trim(), `${occupation.name} needs skillsText`)
  assert(typeof occupation.category === 'string' && occupation.category.trim(), `${occupation.name} needs category`)
  categories.set(occupation.category, (categories.get(occupation.category) ?? 0) + 1)
  assert(!/使用前请征得KP同意|呼唤调查员伴侣/.test(occupation.shortDesc), `${occupation.name} shortDesc should describe the occupation, not source-book usage notes`)
  assert(occupation.source?.sheet === '职业列表', `${occupation.name} needs source sheet`)

  for (const skillId of occupation.skillIds) {
    assert(skills.has(skillId), `${occupation.name} references missing skill id ${skillId}`)
  }
}

assert([...categories.values()].reduce((sum, count) => sum + count, 0) === occupations.length, 'categories must cover every occupation')
assert(categories.size >= 8, `expected at least 8 occupation categories, got ${categories.size}`)

const accountant = occupations.find(occupation => occupation.name === '会计师')
assert(accountant, '会计师 must exist')
assert(accountant.creditRange === '30-70', `会计师 creditRange expected 30-70, got ${accountant.creditRange}`)
assert(accountant.skillIds.includes('accounting'), '会计师 should include accounting')
assert(accountant.skillIds.includes('law'), '会计师 should include law')

const artist = occupations.find(occupation => occupation.name === '艺术家')
assert(artist, '艺术家 must exist')
assert(artist.pointFormula.kind === 'choice', '艺术家 formula should preserve attribute choice')

console.log(`Validated ${occupations.length} COC7 occupations from ${data.metadata.sourceSheet}.`)
