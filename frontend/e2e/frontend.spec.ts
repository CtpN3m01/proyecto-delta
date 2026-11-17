import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

const adminEmail = process.env.E2E_ADMIN_EMAIL ?? '';
const adminPassword = process.env.E2E_ADMIN_PASSWORD ?? '';
const userEmail = process.env.E2E_USER_EMAIL ?? '';
const userPassword = process.env.E2E_USER_PASSWORD ?? '';

function requireCredentials(role: 'admin' | 'user') {
  const values = role === 'admin' ? [adminEmail, adminPassword] : [userEmail, userPassword];
  if (values.some((value) => !value)) throw new Error(`Configura E2E_${role.toUpperCase()}_EMAIL y E2E_${role.toUpperCase()}_PASSWORD para ejecutar las pruebas autenticadas.`);
  return values as [string, string];
}
const sampleVideo = process.env.E2E_VIDEO_PATH
  ? path.resolve(process.env.E2E_VIDEO_PATH)
  : path.resolve(import.meta.dirname, 'fixtures/sample.mp4');
const sampleVideoName = sampleVideo ? path.basename(sampleVideo) : 'recorrido-e2e.mp4';

async function logInWithCredentials(page: Page, email: string, password: string) {
  await page.goto('/#/login');
  await page.getByLabel('Correo electrónico', { exact: true }).fill(email);
  await page.getByLabel('Contraseña', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click();
  await expect(page).toHaveURL(/#\/dashboard$/);
}

async function logIn(page: Page, role: 'admin' | 'user' = 'user') {
  const [email, password] = requireCredentials(role);
  await logInWithCredentials(page, email, password);
}

async function chooseSampleVideo(page: Page) {
  const input = page.getByLabel('Seleccionar archivo MP4', { exact: true });
  if (sampleVideo) {
    await input.setInputFiles(sampleVideo);
  } else {
    const videoBytes = await page.evaluate(async () => {
      const mimeType = [
        'video/mp4;codecs=avc1.42001E',
        'video/mp4;codecs=avc1',
        'video/mp4',
      ].find((candidate) => MediaRecorder.isTypeSupported(candidate));
      if (!mimeType) throw new Error('Edge no permite generar el MP4 de prueba mediante MediaRecorder.');
      const canvas = document.createElement('canvas');
      canvas.width = 160;
      canvas.height = 90;
      const drawing = canvas.getContext('2d');
      if (!drawing) throw new Error('No se pudo preparar el video de prueba.');
      const stream = canvas.captureStream(15);
      const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 100_000 });
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      const finished = new Promise<Blob>((resolve, reject) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: 'video/mp4' }));
        recorder.onerror = () => reject(new Error('No se pudo grabar el MP4 de prueba.'));
      });
      try {
        recorder.start();
        for (let frame = 0; frame < 12; frame += 1) {
          drawing.fillStyle = '#302874';
          drawing.fillRect(0, 0, canvas.width, canvas.height);
          drawing.fillStyle = '#7ce4cf';
          drawing.fillRect(10 + frame * 8, 28, 24, 24);
          await new Promise((resolve) => setTimeout(resolve, 70));
        }
        recorder.stop();
        return Array.from(new Uint8Array(await (await finished).arrayBuffer()));
      } finally {
        stream.getTracks().forEach((track) => track.stop());
      }
    });
    await input.setInputFiles({ name: sampleVideoName, mimeType: 'video/mp4', buffer: Buffer.from(videoBytes) });
  }
  await expect(page.getByLabel('Vista previa del video original', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Anonimizar video', exact: true })).toBeEnabled();
}

test('redirige las rutas privadas al inicio de sesión', async ({ page }) => {
  await page.goto('/#/dashboard');
  await expect(page).toHaveURL(/#\/login$/);
  await expect(page.getByRole('button', { name: 'Iniciar sesión', exact: true })).toBeVisible();
  await page.goto('/#/admin/users');
  await expect(page).toHaveURL(/#\/login$/);
});

test('rechaza credenciales incorrectas y no ofrece registro público', async ({ page }) => {
  await page.goto('/#/login');
  await page.getByLabel('Correo electrónico', { exact: true }).fill(adminEmail || 'no-existe@example.test');
  await page.getByLabel('Contraseña', { exact: true }).fill('ClaveIncorrecta123!');
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page).toHaveURL(/#\/login$/);
  await expect(page.getByRole('link', { name: /registr/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /registr/i })).toHaveCount(0);
});

test('PocketBase impide listar y crear cuentas desde la sesión de usuario', async ({ page }) => {
  await logIn(page, 'user');
  const result = await page.evaluate(async (baseUrl) => {
    const saved = JSON.parse(sessionStorage.getItem('tecpeopleflow.pocketbase.auth.v1') ?? '{}');
    const headers = { Authorization: saved.token, 'Content-Type': 'application/json' };
    const list = await fetch(`${baseUrl}/api/collections/users/records`, { headers });
    const listBody = await list.json();
    const create = await fetch(`${baseUrl}/api/collections/users/records`, {
      method: 'POST', headers, body: JSON.stringify({
        name: 'Escalamiento', email: 'escalamiento@example.test', password: 'Password123!',
        passwordConfirm: 'Password123!', role: 'admin',
      }),
    });
    return { listStatus: list.status, listedItems: listBody.items?.length, createStatus: create.status };
  }, process.env.VITE_POCKETBASE_URL || 'http://127.0.0.1:8090');
  expect(result.listStatus).toBe(200);
  expect(result.listedItems).toBe(0);
  expect(result.createStatus).toBe(400);
});

test('mantiene la sesión al recargar, restringe administración y permite salir', async ({ page }) => {
  await logIn(page);
  await expect(page.getByRole('heading', { name: 'Subir video', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Usuarios', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page).toHaveURL(/#\/dashboard$/);
  await expect(page.getByRole('heading', { name: 'Subir video', exact: true })).toBeVisible();
  await page.goto('/#/admin/users');
  await expect(page).toHaveURL(/#\/dashboard$/);
  await page.getByText('Cerrar sesión', { exact: true }).click();
  await expect(page).toHaveURL(/#\/login$/);
  await page.goto('/#/dashboard');
  await expect(page).toHaveURL(/#\/login$/);
});

test('mantiene el dashboard limpio y aprovecha el ancho de carga en escritorio y móvil', async ({ page }) => {
  await logIn(page);
  await expect(page.locator('.page-heading, .outline-badge, .local-status, .topbar-divider, .demo-label, .upload-guide, .transparency-note, .sidebar-note, .upload-local-note')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Seleccionar video', exact: true })).toBeVisible();
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const layout = await page.locator('.upload-card-body').evaluate((element) => {
      const style = getComputedStyle(element);
      const contentWidth = element.clientWidth - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight);
      const uploadWidth = element.querySelector('.upload-main')!.getBoundingClientRect().width;
      return { widthDifference: Math.abs(contentWidth - uploadWidth), overflow: document.documentElement.scrollWidth > innerWidth };
    });
    expect(layout.widthDifference).toBeLessThan(1);
    expect(layout.overflow).toBe(false);
  }
});

test('mantiene la sesión en sessionStorage y no en localStorage', async ({ page, context }) => {
  await logIn(page, 'admin');
  const storage = await page.evaluate(() => ({
    persistent: JSON.stringify(localStorage),
    session: JSON.stringify(sessionStorage),
    sessionKeys: Object.keys(sessionStorage),
    persistentKeys: Object.keys(localStorage),
  }));
  expect(storage.persistent).toBe('{}');
  expect(storage.session).not.toBe('{}');
  expect(storage.session).not.toContain(adminPassword);
  expect(storage.sessionKeys.some((key) => storage.persistentKeys.includes(key))).toBe(false);

  const separateTab = await context.newPage();
  await separateTab.goto('/#/dashboard');
  await expect(separateTab).toHaveURL(/#\/login$/);
  await separateTab.close();
});

test('el administrador crea cuentas de ambos roles y evita correos duplicados', async ({ page }) => {
  await logIn(page, 'admin');
  await page.getByRole('link', { name: 'Usuarios', exact: true }).click();
  await expect(page).toHaveURL(/#\/admin\/users$/);
  await expect(page.getByRole('heading', { name: 'Personas y accesos', exact: true })).toBeVisible();

  for (const role of ['user', 'admin'] as const) {
    const email = `e2e.${role}@example.test`;
    await page.getByRole('button', { name: 'Crear usuario', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Crear usuario', exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Nombre completo', { exact: true }).fill(`Prueba ${role}`);
    await dialog.getByLabel('Correo electrónico', { exact: true }).fill(email);
    await dialog.getByLabel('Contraseña', { exact: true }).fill('UsuarioNuevo123!');
    await dialog.getByLabel('Rol de acceso', { exact: true }).selectOption(role);
    await dialog.getByRole('button', { name: 'Crear usuario', exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('row', { name: new RegExp(email.replaceAll('.', '\\.')) })).toBeVisible();
  }

  await page.getByRole('button', { name: 'Crear usuario', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Crear usuario', exact: true });
  await dialog.getByLabel('Nombre completo', { exact: true }).fill('Correo repetido');
  await dialog.getByLabel('Correo electrónico', { exact: true }).fill('e2e.user@example.test');
  await dialog.getByLabel('Contraseña', { exact: true }).fill('UsuarioNuevo123!');
  await dialog.getByRole('button', { name: 'Crear usuario', exact: true }).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancelar', exact: true }).click();

  for (const role of ['user', 'admin'] as const) {
    await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).click();
    await logInWithCredentials(page, `e2e.${role}@example.test`, 'UsuarioNuevo123!');
    if (role === 'admin') {
      await expect(page.getByRole('link', { name: 'Usuarios', exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole('link', { name: 'Usuarios', exact: true })).toHaveCount(0);
      await page.goto('/#/admin/users');
      await expect(page).toHaveURL(/#\/dashboard$/);
    }
  }
});

test('rechaza archivos de otro tipo y MP4 corruptos', async ({ page }) => {
  await logIn(page);
  const input = page.getByLabel('Seleccionar archivo MP4', { exact: true });
  await input.setInputFiles({ name: 'documento.txt', mimeType: 'text/plain', buffer: Buffer.from('Prueba E2E') });
  await expect(page.getByRole('alert')).toHaveText('Selecciona un video en formato MP4.');
  await expect(page.getByLabel('Vista previa del video original', { exact: true })).toHaveCount(0);
  await input.setInputFiles({ name: 'corrupto.mp4', mimeType: 'video/mp4', buffer: Buffer.from('MP4 no válido') });
  await expect(page.getByRole('alert')).toHaveText(/No pudimos abrir este MP4/);
  await expect(page.getByLabel('Vista previa del video original', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Anonimizar video', exact: true })).toBeDisabled();
});

test('envía el video al cliente local y muestra un mensaje al completar', async ({ page }) => {
  await logIn(page);
  const requests: string[] = [];
  let uploadedName = '';
  await page.route('http://127.0.0.1:8001/api/v1/jobs', async (route) => {
    uploadedName = route.request().postDataBuffer()?.toString().includes(sampleVideoName) ? sampleVideoName : 'uploaded';
    await route.fulfill({ status: 202, headers: { 'access-control-allow-origin': 'http://127.0.0.1:5173' }, contentType: 'application/json', body: JSON.stringify({ id: 'local-job', status: 'PROCESSING' }) });
  });
  await page.route('http://127.0.0.1:8001/api/v1/jobs/local-job', async (route) => {
    await route.fulfill({ headers: { 'access-control-allow-origin': 'http://127.0.0.1:5173' }, contentType: 'application/json', body: JSON.stringify({ id: 'local-job', status: 'COMPLETED', stage: 4, result_url: '/api/v1/jobs/local-job/result', counts: { people: 1, cars: 2, frames_analyzed: 90 }, logs: ['[OK] MPC listo'] }) });
  });
  page.on('request', (request) => {
    if (['fetch', 'xhr'].includes(request.resourceType()) || !['GET', 'HEAD'].includes(request.method())) {
      requests.push(request.url());
    }
  });
  await chooseSampleVideo(page);

  const preview = page.getByLabel('Vista previa del video original', { exact: true });
  await expect(preview).toHaveAttribute('src', /^blob:/);
  await expect(page.getByText(sampleVideoName, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Anonimizar video', exact: true }).click();
  const stages = page.getByRole('list', { name: 'Etapas del recorrido', exact: true });
  await expect(stages.getByRole('listitem')).toHaveCount(4);
  await expect(page.getByText('Video anonimizado correctamente', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(stages.locator('[data-state="complete"]')).toHaveCount(4);
  await expect(preview).toHaveAttribute('src', /^blob:/);
  await expect(page.getByRole('button', { name: 'Descargar video anonimizado', exact: true })).toBeEnabled();
  await expect(page.getByRole('region', { name: 'Conteo del video' })).toContainText('Personas: 1 · Carros: 2');
  await page.getByText('Registro del procesamiento', { exact: true }).click();
  await expect(page.getByText('[OK] MPC listo', { exact: true })).toBeVisible();
  expect(uploadedName).toBe(sampleVideoName);
  expect(requests.some((url) => url === 'http://127.0.0.1:8001/api/v1/jobs')).toBe(true);
  await page.getByRole('button', { name: 'Quitar video', exact: true }).click();
  await expect(preview).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Anonimizar video', exact: true })).toBeDisabled();
});

test('muestra el error cuando el cliente local no está disponible', async ({ page }) => {
  await logIn(page);
  await chooseSampleVideo(page);
  await page.route('http://127.0.0.1:8001/api/v1/jobs', (route) => route.abort());
  await page.getByRole('button', { name: 'Anonimizar video', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('No se pudo contactar al cliente local.');
  await expect(page.getByText('No se pudo anonimizar el video', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Anonimizar video', exact: true })).toBeEnabled();
});
