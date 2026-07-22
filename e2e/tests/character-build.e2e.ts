/**
 * 建卡链路的 SDK → 后端端到端验证。
 *
 * 这套用例的价值在于**它测的是 SDK 使用者能看到的契约**，跟前端长什么样无关：
 * 将来前端重写、甚至换一个客户端，这些断言依然成立。断的都是具体规则，不是
 * 「接口能通」。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  createRoomWithModule,
  fetchCoc7Ruleset,
  legalCharacterPayload,
  makeSdk,
  registerPlayer,
} from './helpers.ts'

test('ruleset 契约：属性、点数购买约束、年龄区间都由后端下发', async () => {
  const { ruleset } = await fetchCoc7Ruleset(makeSdk())

  // 9 项属性 = 8 项基础 + 幸运
  assert.equal(ruleset.attributes.length, 9)
  const luck = ruleset.attributes.find((a) => a.key === 'LUCK')
  assert.ok(luck, 'ruleset 里应该有 LUCK')
  assert.equal(luck.generation, '3d6*5')

  // 幸运不参与点数购买——客户端据此决定哪些属性可加点，不用自己维护名单
  assert.equal(luck.pointBuy, false)
  const pointBuyKeys = ruleset.attributes.filter((a) => a.pointBuy).map((a) => a.key)
  assert.deepEqual(pointBuyKeys, ['STR', 'CON', 'POW', 'DEX', 'APP', 'SIZ', 'INT', 'EDU'])

  // 点数购买约束必须由后端暴露：客户端要渲染「还剩多少点」「这项最多加到多少」，
  // 拿不到就只能自己硬编码一份，那正是 issue #96 要消灭的东西。
  assert.deepEqual(ruleset.attributePointBuy, {
    budget: 480,
    minValue: 10,
    maxValue: 90,
    defaultValue: 50,
  })

  // COC7 年龄档从 15-19 起、到 80-89 止
  assert.deepEqual(ruleset.ageRange, { minValue: 15, maxValue: 89 })

  // 幸运不参与任何职业技能点公式
  assert.equal(ruleset.occupations.length, 30)
  for (const occupation of ruleset.occupations) {
    assert.ok(
      !occupation.skillPointsFormula.includes('LUCK'),
      `职业「${occupation.name}」的技能点公式不应引用 LUCK`
    )
  }
})

test('建卡全流程：草稿 → 保存 → 读回 → 完成', async () => {
  const room = await createRoomWithModule('build')
  const { sdk } = room.host

  const draft = await sdk.characters.createDraft(room.roomId, room.reconnectToken)
  assert.equal(draft.status, 'draft')

  const attributes = {
    STR: 50, CON: 50, POW: 50, DEX: 50,
    APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
  }
  const payload = legalCharacterPayload(attributes)
  await sdk.characters.save(room.roomId, draft.characterId, payload, room.reconnectToken)

  // 读回：后端是角色卡的唯一事实来源，客户端不该在本地存一份权威副本
  const saved = await sdk.characters.get(room.roomId, draft.characterId, room.reconnectToken)
  assert.equal(saved.name, payload.name)
  assert.equal(saved.age, payload.age)
  assert.equal(saved.gender, payload.gender)
  assert.equal(saved.residence, payload.residence)
  assert.equal(saved.birthplace, payload.birthplace)
  assert.deepEqual(saved.attributes, attributes)
  assert.equal(saved.occupation, '会计师')
  // 走 PATCH 保存的卡默认是点数购买法
  assert.equal(saved.generationMethod, 'pointbuy')

  await sdk.characters.complete(room.roomId, draft.characterId, room.reconnectToken)
  const completed = await sdk.characters.get(room.roomId, draft.characterId, room.reconnectToken)
  assert.equal(completed.status, 'complete')

  // 衍生值由后端权威重算并覆盖，不信任客户端 PATCH 上来的那份
  const derived = completed.derivedStats ?? {}
  assert.equal(derived.HP, 10) // (SIZ 50 + CON 50) / 10
  assert.equal(derived.SAN, 50) // = POW
})

test('🔴 属性点预算：点数购买法超预算被拒，掷骰法不受该预算约束', async () => {
  // 这两条必须成对测。只测第一条的话，一个「无条件校验总预算」的实现也能过，
  // 但那会把合法掷出来的角色卡判成非法——掷骰法 8 项总和均值约 457、范围
  // 195–720，经常超过 480。
  const room = await createRoomWithModule('budget')
  const { sdk } = room.host

  // ① 点数购买法：5 项 90 + 3 项 50 = 600 > 480，必须被拒
  const overBudget = await sdk.characters.createDraft(room.roomId, room.reconnectToken)
  await sdk.characters.save(
    room.roomId,
    overBudget.characterId,
    legalCharacterPayload({
      STR: 90, CON: 90, POW: 90, DEX: 90, APP: 90,
      SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
    }),
    room.reconnectToken
  )
  await assert.rejects(
    () => sdk.characters.complete(room.roomId, overBudget.characterId, room.reconnectToken),
    (error: Error) => {
      assert.match(error.message, /CHARACTER_INVALID|超出预算|校验/)
      return true
    },
    '点数购买法超预算的卡必须被 complete 拒绝'
  )

  // ② 掷骰法：服务端掷出来的属性总和可能远超 480，必须放行
  const rolled = await sdk.characters.createDraft(room.roomId, room.reconnectToken)
  const rollResult = await sdk.characters.rollAttributes(
    room.roomId,
    rolled.characterId,
    room.reconnectToken
  )
  assert.ok(rollResult.attributes.LUCK >= 15 && rollResult.attributes.LUCK <= 90)

  const afterRoll = await sdk.characters.get(room.roomId, rolled.characterId, room.reconnectToken)
  assert.equal(afterRoll.generationMethod, 'roll', '掷过骰的卡要被标记成 roll')

  // ⚠️ 必须用**掷出来的那份属性原样提交**，不能自己写一份必然超预算的。
  //
  // 早先这里图省事直接写死 8 项全 90（=720），因为掷骰 8 项总和均值约 457、
  // 随机结果经常不到 480，写死才能稳定踩到「超预算」这个条件。但那条路径正是
  // PR #97 堵掉的伪造手法（掷一次骰、再把属性整组换掉，来源标记会退回
  // pointbuy），所以那样写现在必然失败——**测试的构造方式本身失效了，要测的
  // 意图没变**。
  //
  // 改成重复掷到总和真的超过 480 为止（只统计参与点数购买的 8 项，幸运不占
  // 预算）。单次超过 480 的概率约 28%，50 次全不中的概率约 1e-7，不会 flaky；
  // 真的一次都没掷出来就显式失败，而不是静默跳过这条断言。
  let rolledAttrs = rollResult.attributes
  const pointBuySum = (a: Record<string, number>) =>
    Object.entries(a).reduce((sum, [k, v]) => (k === 'LUCK' ? sum : sum + v), 0)
  for (let i = 0; i < 50 && pointBuySum(rolledAttrs) <= 480; i += 1) {
    rolledAttrs = (
      await sdk.characters.rollAttributes(room.roomId, rolled.characterId, room.reconnectToken)
    ).attributes
  }
  assert.ok(
    pointBuySum(rolledAttrs) > 480,
    `掷了 50 次都没掷出超过 480 的属性（最后一次 ${pointBuySum(rolledAttrs)}），无法验证掷骰法是否绕开预算`
  )

  await sdk.characters.save(
    room.roomId,
    rolled.characterId,
    legalCharacterPayload(rolledAttrs),
    room.reconnectToken
  )
  const stillRolled = await sdk.characters.get(room.roomId, rolled.characterId, room.reconnectToken)
  assert.equal(stillRolled.generationMethod, 'roll', '原样存回掷出来的属性，来源标记要保住')

  // 卡上记的是 roll，就不该拿点数购买法的预算去卡它
  await sdk.characters.complete(room.roomId, rolled.characterId, room.reconnectToken)
})

test('🔴 掷完骰再自己重填属性，来源退回点数购买法、照样受预算约束', async () => {
  // 上一条的对照面。`roll` 这个标记的意义是「这组属性是服务端掷出来的」，
  // 一旦客户端把属性整组换掉，标记描述的对象就不存在了——否则先掷一次、再把
  // 属性顶满提交，就能绕开 480 点预算（PR #97 review [1]）。
  const room = await createRoomWithModule('forged-roll')
  const { sdk } = room.host

  const draft = await sdk.characters.createDraft(room.roomId, room.reconnectToken)
  await sdk.characters.rollAttributes(room.roomId, draft.characterId, room.reconnectToken)

  // 8 项全顶到单项上限 90（=720 > 480）。用 90 而不是 99 是为了精确命中预算
  // 这条校验——99 会先被单项区间 [10, 90] 拦下，测到的就不是预算了。
  await sdk.characters.save(
    room.roomId,
    draft.characterId,
    legalCharacterPayload({
      STR: 90, CON: 90, POW: 90, DEX: 90,
      APP: 90, SIZ: 90, INT: 90, EDU: 90, LUCK: 50,
    }),
    room.reconnectToken
  )

  const afterForge = await sdk.characters.get(room.roomId, draft.characterId, room.reconnectToken)
  assert.equal(afterForge.generationMethod, 'pointbuy', '属性被整组换掉后，来源要退回点数购买法')

  await assert.rejects(
    () => sdk.characters.complete(room.roomId, draft.characterId, room.reconnectToken),
    (error: Error) => {
      assert.match(error.message, /ATTRIBUTE_POINTS_EXCEEDED|超出预算/)
      return true
    },
    '掷骰来源被撤销后，超预算的属性必须被拒'
  )
})

test('年龄超出 COC7 区间 [15, 89] 被拒', async () => {
  const room = await createRoomWithModule('age')
  const { sdk } = room.host
  const draft = await sdk.characters.createDraft(room.roomId, room.reconnectToken)

  const attributes = {
    STR: 50, CON: 50, POW: 50, DEX: 50,
    APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
  }
  await sdk.characters.save(
    room.roomId,
    draft.characterId,
    { ...legalCharacterPayload(attributes), age: 12 },
    room.reconnectToken
  )

  await assert.rejects(
    () => sdk.characters.complete(room.roomId, draft.characterId, room.reconnectToken),
    '12 岁不在 COC7 的 [15, 89] 区间内，应该被拒'
  )
})

test('信用评级必填：不填会被 CREDIT_OUT_OF_RANGE 拦下', async () => {
  const room = await createRoomWithModule('credit')
  const { sdk } = room.host
  const draft = await sdk.characters.createDraft(room.roomId, room.reconnectToken)

  const attributes = {
    STR: 50, CON: 50, POW: 50, DEX: 50,
    APP: 50, SIZ: 50, INT: 50, EDU: 50, LUCK: 50,
  }
  await sdk.characters.save(
    room.roomId,
    draft.characterId,
    { ...legalCharacterPayload(attributes), skills: {} },
    room.reconnectToken
  )

  await assert.rejects(
    () => sdk.characters.complete(room.roomId, draft.characterId, room.reconnectToken),
    '没填信用评级等于交了 0 分，落在会计师区间 [30,70] 之外'
  )
})

test('不能读别人的角色卡', async () => {
  const room = await createRoomWithModule('privacy')
  const draft = await room.host.sdk.characters.createDraft(room.roomId, room.reconnectToken)

  const intruder = await registerPlayer('intruder')
  const joined = await intruder.sdk.rooms.join(room.roomCode, { nickname: '闯入者' }, intruder.token)

  await assert.rejects(
    () =>
      intruder.sdk.characters.get(room.roomId, draft.characterId, joined.reconnectToken),
    '角色卡含背景故事/装备等属于该玩家的信息，同房间的其他人也不该直接拉到'
  )
})
