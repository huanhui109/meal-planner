/* Run through playwright-cli run-code with a dedicated local development account. */
module.exports = async function qaAssistantWeb(page) {
  const origin = 'http://127.0.0.1:5173'
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  const aiButton = () => page.getByRole('button', { name: /交给 AI 调整/ })
  const sendButton = () => page.getByRole('button', { name: /发送给助手/ })
  const input = () => page.getByRole('textbox', { name: '调整要求', exact: true })
  const screenshot = (name) => page.screenshot({
    path: `output/playwright/${name}.png`, fullPage: true, animations: 'disabled',
  })
  await page.goto(`${origin}/?slot=dinner`)
  await aiButton().waitFor()
  await aiButton().click()
  await input().fill('今晚两个人，不想开火，清淡一点')
  await page.getByText('服务尚未配置 WorkBuddy，仍可复制任务到助手').waitFor()
  check(await sendButton().isDisabled(), 'An unconfigured host must not appear sendable')
  check(await page.getByRole('button', { name: /复制调整任务/ }).isEnabled(), 'Edited task must remain copyable')
  for (const [width, height] of [[360, 800], [768, 1024], [1440, 1000]]) {
    await page.setViewportSize({ width, height })
    await page.waitForFunction(() => {
      const modal = document.querySelector('.ant-modal')
      return modal && getComputedStyle(modal).opacity === '1' && getComputedStyle(modal).transform === 'none'
    })
    await screenshot(`assistant-offline-${width}`)
    const bounds = await page.getByRole('dialog').boundingBox()
    check(bounds.x >= 0 && bounds.x + bounds.width <= width + 1, `Modal overflow at ${width}`)
    check(bounds.y >= 0 && bounds.y + bounds.height <= height + 1, `Modal vertical overflow at ${width}`)
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Page overflow at ${width}`)
  }
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
  await screenshot('assistant-dark-1440')
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'no-preference' })
  await page.keyboard.press('Escape')
  await page.getByRole('link', { name: '偏好与助手设置' }).click()
  await page.getByRole('heading', { name: '助手连接', exact: true }).waitFor()
  check(await page.getByRole('button', { name: /连接助手/ }).isEnabled(), 'Setup must work without OAuth config')
  await page.setViewportSize({ width: 360, height: 800 })
  await screenshot('assistant-settings-360')

  const response = await page.request.get(`${origin}/api/meals/current?meal_slot=dinner`)
  const baseline = (await response.json()).data
  let job = null
  let resultView = null
  let advance = false
  let sent = 0
  let polls = 0
  let mode = 'success'
  const patterns = [
    '**/api/assistant/workbuddy', '**/api/assistant/adjustments**',
    '**/api/meals/current?**', '**/api/meals/qa-web-*/viewed',
  ]
  const fulfill = (route, data) => route.fulfill({ json: { code: 0, message: 'ok', data } })
  await page.route(patterns[0], (route) => fulfill(route, {
    configured: true, connected: true, online: true, state: 'online', message: 'WorkBuddy 已连接，可以直接发送',
  }))
  await page.route(patterns[1], async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST' && path.endsWith('/adjustments')) {
      const payload = request.postDataJSON()
      sent += 1; polls = 0
      check(payload.instruction.trim().length > 0, 'Instruction is missing')
      check(Number.isInteger(payload.expected_revision), 'Revision is missing')
      job = {
        id: payload.request_id, instruction: payload.instruction, context: payload.context,
        status: 'waiting', phase: 'context', error: null, proposal_id: null,
        poll_after_ms: 1000, expires_at: new Date(Date.now() + 300000).toISOString(),
      }
      if (mode === 'ambiguous') return route.abort('failed')
      return fulfill(route, job)
    }
    if (path.endsWith('/current')) {
      return fulfill(route, job && ['sending', 'waiting'].includes(job.status) ? job : null)
    }
    if (path.endsWith('/cancel')) {
      check(path === `/api/assistant/adjustments/${job.id}/cancel`, 'Cancel targeted an older receipt')
      job = { ...job, status: 'cancelled', error: '已取消等待，本次回复不会保存' }
      return fulfill(route, job)
    }
    if (job && advance && job.status === 'waiting') {
      polls += 1
      if (polls === 1) job = { ...job, phase: 'proposal' }
      else if (mode === 'failure') {
        job = { ...job, status: 'failed', error: '这些条件下没有合适候选，原方案未改变' }
      } else {
        const id = `qa-web-${job.id}`
        job = { ...job, status: 'completed', proposal_id: id }
        resultView = {
          ...baseline, revision: baseline.revision + 1,
          proposal: {
            ...baseline.proposal, id, source: 'assistant', status: 'proposed',
            assistant_note: '网页回执模拟验收：新方案已保存，仍待用户选定',
          },
        }
      }
    }
    return fulfill(route, job)
  })
  await page.route(patterns[2], (route) => resultView ? fulfill(route, resultView) : route.continue())
  await page.route(patterns[3], (route) => fulfill(route, {}))
  try {
    await page.goto(`${origin}/?slot=dinner`)
    await aiButton().click()
    await input().fill('给我换一个完整方案，并说明搭配理由')
    await page.getByText('WorkBuddy 已连接，可以直接发送').waitFor()
    await sendButton().click()
    await page.getByText('助手正在理解你的要求', { exact: true }).first().waitFor()
    check(await input().isDisabled(), 'Editing during a send would break idempotency')
    check(await sendButton().isDisabled(), 'Duplicate sends must be disabled')
    await screenshot('assistant-waiting-360')
    check(sent === 1, 'Initial send was duplicated')
    await page.reload()
    await page.getByText('助手正在理解你的要求', { exact: true }).first().waitFor()
    advance = true
    await page.getByText('AI 已调整这一餐，请确认新方案', { exact: true }).waitFor()
    check(sent === 1, 'Reload must only restore and poll, never resend')
    check(await page.getByRole('button', { name: /就吃这个/ }).isEnabled(), 'AI must leave the meal unaccepted')
    await screenshot('assistant-completed-360')

    advance = false
    await aiButton().click()
    await input().fill('先测试取消等待')
    await sendButton().click()
    await page.getByRole('button', { name: /取消等待/ }).click()
    await page.getByText('已取消等待，本次回复不会保存', { exact: true }).waitFor()
    check(await input().isEnabled(), 'Cancellation must allow editing again')

    mode = 'failure'; advance = true
    await input().fill('再测试不能满足的要求')
    await sendButton().click()
    await page.getByText('这些条件下没有合适候选，原方案未改变', { exact: true }).waitFor()
    check(await input().inputValue() === '再测试不能满足的要求', 'Failure lost the edited request')

    mode = 'ambiguous'; advance = false
    await input().fill('测试发送结果丢失后只查询状态')
    await sendButton().click()
    const recover = page.getByRole('button', { name: /查询发送状态/ })
    await recover.waitFor()
    const before = sent
    await recover.click()
    await page.getByText('助手正在理解你的要求', { exact: true }).first().waitFor()
    check(sent === before, 'An uncertain POST must not be resent')
    await page.getByRole('button', { name: /取消等待/ }).click()
    await page.getByText('已取消等待，本次回复不会保存', { exact: true }).waitFor()
    await input().fill('测试状态不明时取消的是这次请求')
    await sendButton().click()
    await recover.waitFor()
    await page.getByRole('button', { name: /取消等待/ }).click()
    await page.getByText('已取消等待，本次回复不会保存', { exact: true }).waitFor()
    check(sent === 5, 'Unexpected number of explicit sends')
    return { viewports: [360, 768, 1440], scenarios: ['offline-copy', 'dark', 'send', 'reload', 'complete', 'cancel', 'failure', 'ambiguous-recovery', 'ambiguous-cancel'], sends: sent }
  } finally {
    for (const pattern of patterns) await page.unroute(pattern)
    await page.goto(`${origin}/?slot=dinner`)
  }
}
