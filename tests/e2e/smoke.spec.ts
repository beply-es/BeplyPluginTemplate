import { expect, type Page, test } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8765';
const LOGIN_USER = process.env.E2E_USER || 'e2e_admin';
const LOGIN_PASSWORD = process.env.E2E_PASSWORD || 'e2e_admin';
const RUNTIME_ERROR_PATTERN = /Fatal error|Deprecated:|Warning:|Error procesando el XML/i;

async function login(page: Page): Promise<void> {
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[name="fsNick"]', LOGIN_USER);
    await page.fill('input[name="fsPassword"]', LOGIN_PASSWORD);
    await page.locator('form[action$="login"] button[type="submit"]').first().click();
    await page.waitForLoadState('networkidle');
    await expect(page).not.toHaveURL(/\/login$/);
}

test('template plugin can be enabled in a real browser runtime', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/AdminPlugins`);
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    await expect(body).not.toContainText(RUNTIME_ERROR_PATTERN);
    await expect(body).toContainText('BeplyPluginTemplate');
});
