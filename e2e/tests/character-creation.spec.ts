import { expect, test } from '@playwright/test'

/**
 * 核心流程端到端验证（issue #94）：注册 → 建房 → 选模组 → 建卡 → 完成。
 *
 * 这套用例存在的意义不是「点一遍没崩」，而是把之前只能靠人工点浏览器才发现的
 * 那类缺陷固化成机器可重复的断言——所以下面每一步都断言**具体数值**
 * （属性项数、点数预算、幸运是否计入），而不是只断言页面没报错。
 */

const BACKEND = 'http://127.0.0.1:8000/api/v1'

/** 每次跑用不同账号，避免重名；数据库虽然每次是新的，但这样本地手工重跑也安全。 */
function uniqueSuffix(): string {
  return `${Date.now()}${Math.floor(Math.random() * 1000)}`
}

test('后端 ruleset 契约：COC7 返回 9 项属性且含幸运', async ({ request }) => {
  /**
   * 从 games → systems 反查 COC7，不写死 UUID（种子数据的 id 是实现细节）。
   *
   * 注意是**遍历所有游戏**去找 COC7，而不是假定它在 `games[0]` 下面：
   * `GET /games` 没有排序保证，以后多种一个游戏（比如 DND5e 那条线），
   * 取第一个就可能翻错了系统列表，于是 COC7 明明是好的、测试却红——
   * 这种假失败会很快消耗掉大家对这套测试的信任。
   */
  const gamesResponse = await request.get(`${BACKEND}/games`)
  expect(gamesResponse.ok()).toBeTruthy()
  const games = (await gamesResponse.json()).data
  expect(games.length, '种子数据里至少要有一个游戏').toBeGreaterThan(0)

  let coc7: { id: string } | undefined
  for (const game of games) {
    const systemsResponse = await request.get(`${BACKEND}/games/${game.id}/systems`)
    expect(systemsResponse.ok()).toBeTruthy()
    const systems = (await systemsResponse.json()).data
    coc7 = systems.find((s: { name: string }) => s.name === 'COC7')
    if (coc7) break
  }
  // 用 throw 而不是 `expect(...).toBeTruthy()` + `coc7!`：前者能让 TS 真正收窄
  // 类型，后者只是用 `!` 跟类型系统打包票，编译器信了但运行时并没有多一层保障。
  if (!coc7) {
    throw new Error('种子数据里应该有 COC7 规则系统，但遍历所有游戏都没找到')
  }

  const rulesetResponse = await request.get(`${BACKEND}/systems/${coc7.id}/ruleset`)
  expect(rulesetResponse.ok()).toBeTruthy()
  const ruleset = (await rulesetResponse.json()).data

  // issue #87 验收标准 1：9 项属性（8 基础 + 幸运），幸运生成公式是独立的 3d6*5
  expect(ruleset.attributes).toHaveLength(9)
  const luck = ruleset.attributes.find((a: { key: string }) => a.key === 'LUCK')
  expect(luck, ' ruleset 里应该有 LUCK').toBeTruthy()
  expect(luck.generation).toBe('3d6*5')

  /**
   * 幸运不参与任何职业技能点公式——这条规则约束在后端单测里也固化了，
   * 这里再从对外契约的角度确认一次，防止公式数据被改坏后只有内部测试拦得住。
   *
   * ⚠️ 循环之前**必须先断言职业数量**：`for (const o of [])` 一次都不执行、
   * 测试照样绿，也就是说 occupations 万一是空的或被截断，下面这圈断言会
   * 「真空通过」，嘴上说守了 30 个公式、实际一个都没验到。
   *
   * 这里刻意断言精确的 30 而不是 `> 0`：职业目录后续要扩到 229（MS2 后续），
   * 那时这行会红——这是有意的，扩目录的人应该顺手确认新导入的职业公式同样
   * 不引用 LUCK，而不是让它悄悄溜过去。
   */
  expect(ruleset.occupations).toHaveLength(30)
  for (const occupation of ruleset.occupations) {
    expect(
      occupation.skillPointsFormula,
      `职业「${occupation.name}」的技能点公式不应引用 LUCK`
    ).not.toContain('LUCK')
  }
})

test('完整建卡流程：注册 → 建房 → 选模组 → 建卡 → 完成', async ({ page }) => {
  const suffix = uniqueSuffix()
  const account = `e2e_${suffix}`

  // ── 注册 ───────────────────────────────────────────────────────────
  await page.goto('/auth/register')
  await page.getByPlaceholder('账号').fill(account)
  await page.getByPlaceholder('密码').fill('e2e-test-1234')
  await page.getByPlaceholder('昵称').fill(`E2E ${suffix}`)
  // 用精确名字：页面上还有一个「注册」是登录/注册的切换 tab，
  // 模糊匹配会同时命中两个按钮触发 strict mode 报错。
  await page.getByRole('button', { name: '注册并进入' }).click()

  // 注册成功应该进到首页菜单
  await expect(page).toHaveURL(/\/home/, { timeout: 15_000 })

  // ── 创建房间 ───────────────────────────────────────────────────────
  await page.getByText('创建房间', { exact: false }).first().click()
  await expect(page).toHaveURL(/\/home\/create/)

  await page.getByPlaceholder('例如：阿卡姆调查团').fill(`E2E 房间 ${suffix}`)

  // ── 选游戏 / 规则系统 / 模组 ────────────────────────────────────────
  await page.getByRole('button', { name: '选择游戏' }).click()
  await expect(page).toHaveURL(/\/games/)
  // 游戏选择页列的是产品分类（跑团 / 血染钟楼 / 狼人杀 / 剧本杀），
  // 只有「跑团」是已实现的，点进去才是规则系统（COC7）和模组。
  await page.getByText('跑团', { exact: true }).click()
  // 「选择世界」列的是规则系统，COC7 在这里显示为「克苏鲁的呼唤」。
  await page.getByRole('heading', { name: '克苏鲁的呼唤' }).click()
  await page.getByText('追书人').first().click()

  // 选完模组应该回到创建页，且概览里显示已选内容
  await expect(page).toHaveURL(/\/home\/create/)

  await page.getByRole('button', { name: /创建房间/ }).click()

  // ── 大厅 → 背景介绍 → 建卡 ─────────────────────────────────────────
  await expect(page).toHaveURL(/\/room\/lobby/, { timeout: 15_000 })

  /**
   * 房主要显式点「开始游戏」才推进（不是全员就绪自动跳）。
   *
   * ⚠️ 这里**不要**写成 `if (await button.isVisible()) { click() }`。
   * `isVisible()` 是即时检查、不等待：本地大厅渲染快，按钮已经在了；CI runner
   * 慢一拍，这个判断就会在按钮出现之前返回 false，于是**静默跳过点击**，测试
   * 一路卡到超时才报错，而且报的是「URL 不对」这种离根因很远的现象。
   * （这个坑就是本 PR 在真 CI 上第一次跑挂时暴露出来的，本地跑 10 次都是绿的。）
   *
   * `click()` 本身就会自动等待元素可见可交互，直接点即可——需要「条件式」判断
   * 的地方，通常说明流程本身不确定，那才是该先想清楚的问题。
   */
  await page.getByRole('button', { name: /开始游戏/ }).click()

  // 背景介绍页（StoryPage）：读完模组开场，点「继续」进建卡。
  await expect(page).toHaveURL(/\/room\/story/, { timeout: 15_000 })
  await page.getByRole('button', { name: /继续/ }).click()

  await expect(page).toHaveURL(/\/room\/character/, { timeout: 15_000 })

  // ── 建卡 · 第一步：调查员信息 + 选职业 ─────────────────────────────
  await page.getByRole('textbox', { name: '角色姓名' }).fill('E2E 调查员')
  // 选会计师：技能点公式是 EDU*4、信用区间 [30,70]，是后端单测也在用的固定夹具，
  // 数字好算，方便断言。
  await page.getByText('会计师', { exact: true }).click()
  await page.getByRole('button', { name: /下一步/ }).click()

  // ── 建卡 · 第二步：属性分配（本套测试最核心的断言）─────────────────
  await expect(page.getByRole('heading', { name: '属性分配' })).toBeVisible()

  /**
   * 加点网格必须正好 8 项。
   *
   * COC7 里幸运只能掷、不能用属性点购买，所以它不该出现在这个可加点网格里。
   * 每个可加点属性都带一个 number 输入框（spinbutton），只读的幸运卡片没有，
   * 所以数 spinbutton 的个数就能把「幸运有没有混进加点网格」钉死。
   */
  await expect(page.getByRole('spinbutton')).toHaveCount(8)

  /**
   * 总点数 400/480，且加点后按 ±5 变化。
   *
   * 480 是本项目的**自订规则**（COC7 官方点数购买法是 460 点），不是笔误。
   * 这条断言真正要防的回归是「幸运被算进属性点预算」——那样初始值会变成
   * 450/480（多算了幸运的 50），玩家凭空少 50 点可分配。
   */
  const totalPoints = page.getByText(/^\d+\/480$/)
  await expect(totalPoints).toHaveText('400/480')

  // 幸运只读展示：值可见，但这一行没有可编辑的输入框（已由上面的 8 个 spinbutton 保证）。
  await expect(page.getByText('LUCK')).toBeVisible()
  await expect(page.getByText(/不占属性点数/)).toBeVisible()

  /**
   * 把第一项属性从 50 改成 55，总数应该跟着变成 405——再次确认幸运没被卷进这个预算。
   *
   * 这里直接改输入框而不是点 +/− 按钮：那两个按钮是纯图标、没有可访问名称
   * （`getByRole('button', { name: ... })` 定位不到），只能靠 DOM 结构去点，
   * 那种选择器一改布局就碎。改输入框反而更稳，也顺带覆盖了手动输入这条路径。
   * 按钮缺 aria-label 本身是个可访问性问题，但修它属于前端改动，不在本 issue 范围。
   */
  const firstAttribute = page.getByRole('spinbutton').first()
  await firstAttribute.fill('55')
  await firstAttribute.blur() // 数值是在 onBlur 时提交的
  await expect(totalPoints).toHaveText('405/480')

  // ── 建卡 · 剩余步骤 → 完成 ─────────────────────────────────────────
  // 技能、装备背景两步都用默认值走过去：本用例要守的是「流程能跑通 + 属性/幸运
  // 的规则约束」，技能分配的细节由后端单测覆盖，不在这里重复。
  await page.getByRole('button', { name: /下一步/ }).click()
  await page.getByRole('button', { name: /下一步/ }).click()

  /**
   * 建卡完成不能被后端拒绝。
   *
   * `complete` 会做 COC7 权威校验，不合法返回 422 `CHARACTER_INVALID`。
   * 直接监听这个响应，比只看「有没有跳页」更能说明问题——万一将来失败了，
   * 报错会直接指出是被校验拒了，而不是让人对着一个超时的 URL 断言猜原因。
   */
  const completeResponse = page.waitForResponse(
    (response) => response.url().includes('/complete') && response.request().method() === 'POST'
  )
  await page.getByRole('button', { name: /完成|创建角色/ }).click()
  expect((await completeResponse).status(), '建卡完成不应被 COC7 校验拒绝').toBe(200)

  // ── 人物卡准备页：角色卡应该显示 9 项属性（含幸运）─────────────────
  await expect(page).toHaveURL(/\/room\/ready/, { timeout: 15_000 })
  await page.getByRole('button', { name: /查看/ }).click()

  // 幸运必须出现在角色卡上——加幸运那轮的真实缺口就是「建卡页有、角色卡没有」，
  // 三处硬编码的属性列表漏了一处，只有走到这一步才看得出来。
  await expect(page.getByText('LUCK')).toBeVisible()
  for (const key of ['STR', 'CON', 'POW', 'DEX', 'APP', 'SIZ', 'INT', 'EDU']) {
    await expect(page.getByText(key, { exact: true })).toBeVisible()
  }
})
