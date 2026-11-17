import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

test('Brave/web → API Docker → tres parties → conteos y descarga reales', async ({ page }) => {
  test.skip(process.env.RUN_WEB_MPC_E2E !== '1', 'Prueba opt-in con Docker y un clip H.264 corto');
  test.setTimeout(240_000);
  if (!process.env.E2E_USER_EMAIL || !process.env.E2E_USER_PASSWORD) {
    throw new Error('Configura E2E_USER_EMAIL y E2E_USER_PASSWORD con una cuenta de aplicación antes de ejecutar la prueba.');
  }
  const source = process.env.WEB_MPC_VIDEO_PATH;
  if (!source) throw new Error('WEB_MPC_VIDEO_PATH debe apuntar a un clip corto, no al video completo');
  const started = Date.now();
  await page.goto('/#/login');
  await page.getByLabel('Correo electrónico', { exact: true }).fill(process.env.E2E_USER_EMAIL ?? '');
  await page.getByLabel('Contraseña', { exact: true }).fill(process.env.E2E_USER_PASSWORD ?? '');
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click();
  await expect(page).toHaveURL(/#\/dashboard$/);
  await page.getByLabel('Seleccionar archivo MP4', { exact: true }).setInputFiles(source);
  await expect(page.getByLabel('Vista previa del video original', { exact: true })).toBeVisible();
  const registration = page.waitForResponse(response =>
    response.url().endsWith('/api/v1/jobs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Anonimizar video', exact: true }).click();
  const response = await registration;
  expect(response.status()).toBe(202);
  const { id } = await response.json();
  await expect(page.getByText('Video anonimizado correctamente', { exact: true })).toBeVisible({ timeout: 210_000 });
  await expect(page.getByRole('region', { name: 'Conteo del video' })).toBeVisible();
  const job = await page.evaluate(async (jobId) => {
    const response = await fetch(`http://127.0.0.1:8001/api/v1/jobs/${jobId}`);
    return response.json();
  }, id);
  expect(job.status).toBe('COMPLETED');
  expect(job.counts.frames_analyzed).toBeGreaterThanOrEqual(3);
  expect(job.counts.people).toBeGreaterThanOrEqual(1);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Descargar video anonimizado', exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('video-anonimizado.mp4');
  const folder = path.resolve('../.runtime/T38_T45');
  await fs.mkdir(folder, { recursive: true });
  await download.saveAs(path.join(folder, 'browser-result.mp4'));
  expect((await fs.stat(path.join(folder, 'browser-result.mp4'))).size).toBeGreaterThan(0);
  await page.screenshot({ path: path.join(folder, 'browser-completed.png'), fullPage: true });
  await fs.writeFile(path.join(folder, 'browser-summary.json'), JSON.stringify({
    source, id, elapsed_seconds: (Date.now()-started)/1000, counts: job.counts, logs: job.logs,
  }, null, 2));
});
