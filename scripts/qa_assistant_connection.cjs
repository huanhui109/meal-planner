/* Run with playwright-cli run-code in the dedicated local development QA account. */
module.exports = async function qaAssistantConnection(page) {
  const origin = 'http://127.0.0.1:5173'
  const check = (value, message) => { if (!value) throw new Error(message) }
  const connect = () => page.getByRole('button', { name: /连接助手/ })
  const dialog = () => page.getByRole('dialog')
  const create = () => page.getByRole('button', { name: /创建 Skill 凭据/ })
  const refresh = () => page.getByRole('button', { name: '刷新助手连接' })
  const screenshot = (name) => page.screenshot({
    path: `output/playwright/${name}.png`, fullPage: true, animations: 'disabled',
  })
  const bounds = async (width, height) => {
    await page.waitForFunction(() => {
      const modal = document.querySelector('.ant-modal')
      return modal && getComputedStyle(modal).opacity === '1' && getComputedStyle(modal).transform === 'none'
    })
    const rect = await dialog().boundingBox()
    check(rect && rect.x >= 0 && rect.x + rect.width <= width + 1, `Horizontal dialog overflow at ${width}`)
    check(rect.y >= 0 && rect.y + rect.height <= height + 1, `Vertical dialog overflow at ${width}`)
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Page overflow at ${width}`)
  }
  const grantUrl = `${origin}/api/assistant/grants`
  const statusPattern = '**/api/assistant/workbuddy'
  const authorizePattern = '**/api/assistant/workbuddy/authorize'
  let actualGrant = null
  let creations = 0
  const countCreation = (request) => {
    if (request.url() === grantUrl && request.method() === 'POST') creations += 1
  }
  page.on('request', countCreation)
  try {
    await page.goto(`${origin}/me`)
    await page.getByText('网页直发未启用，可使用 Skill 连接', { exact: true }).waitFor()
    check(await connect().isEnabled(), 'Unconfigured host disabled the setup entry')
    check(await page.getByRole('heading', { name: 'Skill 访问凭据' }).count() === 0, 'Duplicate settings section')
    await connect().click()
    await create().waitFor()
    await dialog().getByText('网页直发', { exact: true }).click()
    await page.getByRole('button', { name: /使用 Skill 连接/ }).click()
    await create().waitFor()
    for (const [width, height] of [[360, 800], [768, 1024], [1440, 1000]]) {
      await page.setViewportSize({ width, height })
      await bounds(width, height)
      await screenshot(`connection-skill-${width}`)
    }
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
    await screenshot('connection-skill-dark')
    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'no-preference' })
    const created = page.waitForResponse((response) =>
      response.url() === grantUrl && response.request().method() === 'POST')
    await create().click({ clickCount: 2 })
    const response = await created
    check(response.ok(), 'Real credential creation failed')
    actualGrant = (await response.json()).data.id
    await page.getByRole('dialog', { name: '保存 Skill 连接凭据' }).waitFor()
    const credential = page.getByLabel('连接凭据', { exact: true })
    check(await credential.getAttribute('type') === 'password', 'Credential must be masked')
    check(Boolean(await credential.inputValue()), 'One-time credential was not shown')
    check(creations === 1, 'Double click created duplicate credentials')
    await page.setViewportSize({ width: 360, height: 800 })
    await bounds(360, 800)
    await screenshot('connection-credential-360')
    await page.getByRole('button', { name: '完成', exact: true }).click()
    await credential.waitFor({ state: 'detached' })
    check(await credential.count() === 0, 'Credential remains in the DOM after dismissal')
    await page.locator('.meal-grant').first().getByRole('button', { name: /撤销/ }).click()
    await page.getByRole('button', { name: '撤 销', exact: true }).click()
    await page.locator('.meal-grant').first().getByText('已撤销 · Skill', { exact: true }).waitFor()
    await page.reload()
    await page.getByText('网页直发未启用，可使用 Skill 连接', { exact: true }).waitFor()
    check(await credential.count() === 0, 'Reload must not recover a one-time credential')

    let statusMode = 'slow'
    const fulfill = (route, data) => route.fulfill({ json: { code: 0, message: 'ok', data } })
    await page.route(statusPattern, async (route) => {
      if (statusMode === 'slow') return
      if (statusMode === 'error') return route.abort('failed')
      return fulfill(route, {
        configured: true, connected: statusMode === 'online', online: statusMode === 'online' ? true : null,
        state: statusMode === 'online' ? 'online' : 'disconnected',
        message: statusMode === 'online' ? 'WorkBuddy 已连接，可以直接发送' : '请先授权连接 WorkBuddy',
      })
    })
    await page.goto(`${origin}/me`)
    await page.getByText('正在检查网页直发', { exact: true }).waitFor()
    await connect().click()
    check(await create().isEnabled(), 'Status probe must not block Skill setup')
    await dialog().getByRole('button', { name: 'Close', exact: true }).click()
    await dialog().waitFor({ state: 'hidden' })
    await page.getByText('助手连接请求超时，请重试；操作结果可刷新确认', { exact: true }).waitFor({ timeout: 20000 })
    check(await refresh().isEnabled(), 'Timed-out probe left the refresh spinning')
    statusMode = 'error'
    await refresh().click()
    await page.getByText('Network Error', { exact: true }).waitFor()
    check(await connect().isEnabled(), 'Probe failure disabled setup')
    statusMode = 'disconnected'
    await refresh().click()
    await page.getByText('请先授权连接 WorkBuddy', { exact: true }).waitFor()
    await connect().click()
    const authorize = page.getByRole('button', { name: /授权 WorkBuddy/ })
    await authorize.waitFor()
    let authMode = 'invalid'
    await page.route(authorizePattern, (route) => {
      if (authMode === 'error') return route.fulfill({
        status: 503, json: { detail: '授权服务暂不可用，请重试' },
      })
      return fulfill(route, { url: authMode === 'invalid'
        ? 'https://example.invalid/unsafe'
        : 'https://www.workbuddy.cn/openapi/v2/authorize?state=qa-browser-only' })
    })
    await authorize.click()
    await page.getByText('助手授权地址无效', { exact: true }).waitFor()
    check(await authorize.isEnabled(), 'Invalid redirect left authorization busy')
    authMode = 'error'
    await authorize.click()
    await page.getByText('授权服务暂不可用，请重试', { exact: true }).waitFor()
    check(await authorize.isEnabled(), 'Authorization failure left button busy')
    authMode = 'valid'
    await page.route('https://www.workbuddy.cn/openapi/v2/authorize?state=qa-browser-only',
      (route) => route.fulfill({ contentType: 'text/html', body: '<title>OAuth navigation QA</title>' }))
    await authorize.click()
    await page.waitForURL('https://www.workbuddy.cn/openapi/v2/authorize?state=qa-browser-only')
    check(creations === 1, 'Native authorization must not create a Skill grant')

    statusMode = 'online'
    await page.goto(`${origin}/me`)
    await page.getByRole('button', { name: /断开网页直连/ }).waitFor()
    await connect().click()
    check(await page.getByRole('button', { name: /重新授权 WorkBuddy/ }).isEnabled(), 'Connected setup lost reauthorization')
    await bounds(360, 800)
    await page.keyboard.press('Escape')
    await dialog().waitFor({ state: 'hidden' })
    return {
      scenarios: ['unconfigured-fallback', 'real-grant-create', 'double-click', 'one-time-secret',
        'real-grant-revoke', 'slow-probe', 'probe-timeout', 'probe-error',
        'authorization-error', 'unsafe-redirect', 'oauth-navigation-mocked', 'existing-connection'],
      viewports: [360, 768, 1440], creations,
    }
  } finally {
    page.off('request', countCreation)
    if (actualGrant) await page.request.delete(`${grantUrl}/${encodeURIComponent(actualGrant)}`)
    await page.unroute(statusPattern)
    await page.unroute(authorizePattern)
    await page.unroute('https://www.workbuddy.cn/openapi/v2/authorize?state=qa-browser-only')
    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'no-preference' })
    await page.goto(`${origin}/me`)
  }
}
