import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

const zip = resolve(import.meta.dirname, '../../test-results/sample.zip')

test('import an archive, review it, inspect a finding, give feedback', async ({ page }) => {
  // Register
  await page.goto('/login')
  await page.getByRole('button', { name: 'Create one' }).click()
  await page.getByLabel('Email').fill(`e2e-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('e2e-password-123')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
  await expect(page.getByText('No repositories yet')).toBeVisible()

  // Import the sample archive
  await page.getByRole('button', { name: 'Add repository' }).click()
  await page.getByLabel('Name').fill('inventory-e2e')
  await page.getByLabel('Archive').setInputFiles(zip)
  await page.getByRole('button', { name: 'Import repository' }).click()
  await expect(page.getByRole('heading', { name: 'inventory-e2e' })).toBeVisible()
  await expect(page.getByText(/files? · .* · indexed/)).toBeVisible()

  // Search
  await page.getByRole('tab', { name: 'Search' }).click()
  await page.getByLabel('Search code').fill('apply_discount')
  await page.getByLabel('Search mode').selectOption('identifier')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByText('inventory/pricing.py:4')).toBeVisible()

  // Review
  await page.getByRole('button', { name: 'Start review' }).click()
  await expect(page.getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  const findings = page.getByRole('list', { name: 'Findings' })
  await expect(findings.getByText('B602: subprocess_popen_with_shell_equals_true')).toBeVisible()

  // Open the cited source line
  await findings.getByText('B602: subprocess_popen_with_shell_equals_true').click()
  await expect(page.locator('p', { hasText: 'inventory/store.py:27' })).toBeVisible()
  const cited = page.locator('tr.bg-hl')
  await expect(cited).toHaveCount(1)
  await expect(cited).toContainText('shell=True')

  // Filter, then feedback
  await page.getByRole('button', { name: 'high', exact: true }).click()
  await expect(findings.getByRole('button')).toHaveCount(1)
  await page.getByRole('button', { name: 'Useful' }).click()
  await expect(page.getByRole('button', { name: 'Useful' })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Useful' })).toHaveAttribute('aria-pressed', 'true')

  // History
  await page.getByRole('link', { name: 'Repository' }).click()
  await expect(page.getByRole('link', { name: /Whole repository completed/ })).toBeVisible()
})

test('unauthenticated users are sent to sign in', async ({ page }) => {
  await page.goto('/repositories/1')
  await expect(page).toHaveURL(/\/login$/)
})
