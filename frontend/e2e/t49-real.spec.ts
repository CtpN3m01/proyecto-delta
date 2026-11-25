import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import { login } from './auth';
test.use({ trace: 'off' });

/**
 * El navegador solo detecta y entrega shares; después se CIERRA la pestaña y
 * el MPC debe terminar en el servidor y aparecer en el historial del usuario.
 */
const sources = process.env.E2E_VIDEO_PATH ? [process.env.E2E_VIDEO_PATH] : process.env.T49_VIDEO ? [process.env.T49_VIDEO] : ['video1.mp4', 'video2.mp4', 'video3.mp4'];
for (const source of sources) test(`MPC en segundo plano tras cerrar la pestaña: ${path.basename(source)}`, async ({ page, context }) => {
  const name = path.basename(source);
  test.skip(process.env.RUN_WEB_MPC_E2E !== '1', 'Requires real Docker parties, browser and root videos');
  test.setTimeout(21_600_000);
  const evidence = path.resolve('../.runtime/t49-evidence');
  await fs.mkdir(evidence, { recursive: true });
  const started = Date.now();
  let ticket: string | undefined;
  context.on('request', request => {
    if (request.method() !== 'POST') return;
    const url = request.url(), bytes = request.postDataBuffer()?.length ?? 0;
    // Party 1 y 2 reciben solo una clave; el coordinator, metadata.
    if (!url.includes(':8100/')) expect(bytes).toBeLessThan(4096);
    expect(request.headers()['content-type'] ?? '').not.toContain('multipart');
  });
  context.on('response', async response => {
    if (response.url().endsWith('/api/v1/browser-jobs') && response.status() === 201) ticket = (await response.json()).id;
  });
  await login(page);
  await page.getByLabel('Seleccionar archivo MP4', { exact: true }).setInputFiles(path.resolve('../..', source));
  await expect(page.getByText('Tu parte terminó: el MPC continúa en el servidor', { exact: true })).toBeVisible({ timeout: 21_000_000 });
  expect(ticket).toBeTruthy();
  const detectionSeconds = (Date.now() - started) / 1000;
  await page.close(); // el usuario se retira

  const history = await context.newPage();
  await login(history);
  await history.goto('/#/historial');
  const row = history.getByRole('row').filter({ hasText: name }).first();
  await expect(row).toBeVisible();
  await expect(row.getByText('Anonimizado', { exact: true })).toBeVisible({ timeout: 21_000_000 });
  await history.screenshot({ path: path.join(evidence, `${name}.history.png`), fullPage: true });

  const catalog = await context.newPage();
  await catalog.goto(process.env.T49_CATALOG_URL ?? 'http://localhost:8081');
  const downloadPromise = catalog.waitForEvent('download');
  await catalog.locator('a[href$="/download"]').first().click();
  const download = await downloadPromise;
  await download.saveAs(path.join(evidence, `${name}.anonymous.mp4`));
  expect((await fs.stat(path.join(evidence, `${name}.anonymous.mp4`))).size).toBeGreaterThan(100);
  const summary = { source: name, ticket, detection_seconds: detectionSeconds, total_seconds: (Date.now() - started) / 1000 };
  await fs.writeFile(path.join(evidence, `${name}.summary.json`), JSON.stringify(summary, null, 2));
  console.log('BACKGROUND MPC COMPLETED', JSON.stringify(summary));
});
