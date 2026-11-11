import { expect, test } from '@playwright/test'

test.describe('MapSmith 前端', () => {
  test('首页显示对话入口与侧边栏', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByText('今天想做什么图？')).toBeVisible()
    await expect(page.locator('.nav button', { hasText: '对话生成' })).toBeVisible()
    await expect(page.locator('.nav button', { hasText: '高级表单' })).toBeVisible()
    await expect(page.locator('.composer textarea')).toBeVisible()
    await expect(page.locator('.composer .send')).toBeVisible()
  })

  test('高级表单出图并下载 PNG', async ({ page }) => {
    await page.goto('/')
    await page.locator('.nav button', { hasText: '高级表单' }).click()

    const mapType = page.locator('.field').filter({ hasText: '图种' }).locator('select')
    await mapType.selectOption('point')
    await page.getByRole('button', { name: '生成地图' }).click()

    await expect(page.getByAltText('地图预览')).toBeVisible({ timeout: 90_000 })
    const link = page.getByRole('link', { name: '下载 PNG' })
    await expect(link).toBeVisible()

    const href = await link.getAttribute('href')
    expect(href).toBeTruthy()
    const response = await page.request.get(new URL(href!, 'http://127.0.0.1:8501').toString())
    expect(response.ok()).toBeTruthy()
    expect((await response.body()).length).toBeGreaterThan(10_000)
  })

  test('未配置模型时对话给出中文提示', async ({ page }) => {
    const health = await (await page.request.get('/api/health')).json()
    test.skip(Boolean(health.llm_configured), '当前已配置模型，跳过未配置提示用例')

    await page.goto('/')
    await expect(page.locator('.hint').filter({ hasText: '未配置模型' })).toBeVisible()
    await expect(page.locator('.composer textarea')).toBeDisabled()
  })

  test('上传缺 CRS 文件弹出坐标系确认', async ({ page }) => {
    await page.goto('/')
    await page.locator('.composer input[type=file]').setInputFiles({
      name: 'sites.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(
        'station_name,lon,lat,PM2_5_24h\nA,117.18,34.22,45\nB,117.22,34.28,58\n',
      ),
    })

    await expect(page.locator('.dialog')).toBeVisible()
    await expect(page.locator('.dialog')).toContainText('确认坐标系')
    await page.getByRole('button', { name: '确认并继续' }).click()

    await expect(page.locator('.dialog')).toBeHidden()
    await expect(page.locator('.attachment')).toContainText('sites.csv')
  })

  test('移动端侧边栏可折叠', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')

    await expect(page.locator('.sidebar')).not.toHaveClass(/open/)
    await page.locator('.mobile-toggle').click()
    await expect(page.locator('.sidebar')).toHaveClass(/open/)
  })
})