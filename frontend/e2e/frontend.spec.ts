import { expect, test, type Page } from '@playwright/test';

const demoPassword = 'AdminDemo123!';
async function logInWithCredentials(page: Page, email: string, password: string) {
  await page.goto('/#/login');
  await page.getByLabel('Correo electrónico', { exact: true }).fill(email);
  await page.getByLabel('Contraseña', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click();
  await expect(page).toHaveURL(/#\/dashboard$/);
}

async function logIn(page: Page, role: 'admin' | 'user' = 'user') {
  await logInWithCredentials(
    page,
    role === 'admin' ? 'admin@tecpeopleflow.local' : 'usuario@tecpeopleflow.local',
    role === 'admin' ? demoPassword : 'UsuarioDemo123!',
  );
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
  await page.getByLabel('Correo electrónico', { exact: true }).fill('admin@tecpeopleflow.local');
  await page.getByLabel('Contraseña', { exact: true }).fill('ClaveIncorrecta123!');
  await page.getByRole('button', { name: 'Iniciar sesión', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page).toHaveURL(/#\/login$/);
  await expect(page.getByRole('link', { name: /registr/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /registr/i })).toHaveCount(0);
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

test('guarda credenciales derivadas y mantiene la sesión fuera de localStorage', async ({ page, context }) => {
  await logIn(page, 'admin');
  const storage = await page.evaluate(() => ({
    persistent: JSON.stringify(localStorage),
    session: JSON.stringify(sessionStorage),
    sessionKeys: Object.keys(sessionStorage),
    persistentKeys: Object.keys(localStorage),
  }));
  expect(storage.persistent).toContain('admin@tecpeopleflow.local');
  expect(storage.persistent).not.toContain(demoPassword);
  expect(storage.persistent).not.toContain('UsuarioDemo123!');
  expect(storage.session).not.toBe('{}');
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
    const email = `e2e.${role}@tecpeopleflow.local`;
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
  await dialog.getByLabel('Correo electrónico', { exact: true }).fill('e2e.user@tecpeopleflow.local');
  await dialog.getByLabel('Contraseña', { exact: true }).fill('UsuarioNuevo123!');
  await dialog.getByRole('button', { name: 'Crear usuario', exact: true }).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancelar', exact: true }).click();

  for (const role of ['user', 'admin'] as const) {
    await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).click();
    await logInWithCredentials(page, `e2e.${role}@tecpeopleflow.local`, 'UsuarioNuevo123!');
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
  await expect(page.getByRole('alert')).toHaveText(/MP4/);
  await expect(page.getByLabel('Vista previa del video original', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Anonimizar video', exact: true })).toBeDisabled();
});
