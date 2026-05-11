import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
    testDir: './e2e',
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: 1,
    reporter: 'html',
    timeout: 60000,
    globalTimeout: process.env.CI ? 1800000 : 900000,
    expect: {
        timeout: 10000,
    },
    use: {
        baseURL: process.env.BASE_URL || 'http://localhost:8765',
        timezoneId: process.env.FS_E2E_TIMEZONE || process.env.TZ || 'Europe/Madrid',
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        navigationTimeout: 30000,
        actionTimeout: 15000,
    },
    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
    ],
});
