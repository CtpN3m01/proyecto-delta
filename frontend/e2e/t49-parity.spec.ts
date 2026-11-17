import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
test('T49 OpenCV / browser parity on the exact same lossless frames', async ({ page }) => {
  test.skip(process.env.RUN_T49_PARITY !== '1');
  test.setTimeout(180_000);
  const root = path.resolve('../.runtime/t49-reference');
  const reference = JSON.parse(await fs.readFile(path.join(root, 'reference.json'), 'utf8'));
  const metrics: unknown[] = [];
  await page.goto('/catalog.html');
  await page.evaluate(() => { document.body.innerHTML = '<input type="file">'; });
  for (const [name, expected] of Object.entries(reference) as [string, Record<string, { box: number[]; score: number; kind?: string }[]>][]) {
    await page.locator('input').setInputFiles(path.join(root, name));
    const actual = await page.evaluate(async () => {
      const worker = new Worker('/e2e/probe.worker.ts', { type: 'module' });
      return new Promise<Record<string, { box: number[]; score: number; kind?: string }[]>>((resolve, reject) => {
        worker.onerror = e => reject(new Error(e.message));
        worker.onmessage = ({ data }) => { worker.terminate(); if (data.status === 'error') reject(new Error(data.message)); else resolve(data.result); };
        worker.postMessage(document.querySelector('input')!.files![0]);
      });
    });
    for (const kind of ['faces', 'plates', 'objects']) {
      expect(actual[kind].length, `${name} ${kind}`).toBe(expected[kind].length);
      let maxBoxDelta = 0, maxScoreDelta = 0;
      for (let i = 0; i < actual[kind].length; i++) {
        const a = actual[kind][i], b = expected[kind][i];
        expect(a.kind).toBe(b.kind);
        maxBoxDelta = Math.max(maxBoxDelta, ...a.box.map((v, axis) => Math.abs(v - b.box[axis])));
        maxScoreDelta = Math.max(maxScoreDelta, Math.abs(a.score - b.score));
      }
      metrics.push({ name, kind, detections: actual[kind].length, maxBoxDelta, maxScoreDelta });
      expect(maxBoxDelta, `${name} ${kind} geometry`).toBeLessThan(3);
      expect(maxScoreDelta, `${name} ${kind} confidence`).toBeLessThan(.025);
    }
  }
  console.log('PARITY', JSON.stringify(metrics));
  await fs.mkdir(path.resolve('../.runtime/t49-evidence'), { recursive: true });
  await fs.writeFile(path.resolve('../.runtime/t49-evidence/parity.json'), JSON.stringify(metrics, null, 2));
});
