import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateUserInput } from '../types';
import { createDemoAuthService, DEMO_ACCOUNTS } from './demo-auth';

const USERS_KEY = 'tecpeopleflow.demo.users.v1';
const SESSION_KEY = 'tecpeopleflow.demo.session.v1';

class MemoryStorage implements Storage {
  private values = new Map<string, string>();

  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

const newUser: CreateUserInput = {
  name: 'Ana Pérez',
  email: 'ana@example.local',
  password: 'NuevaDemo123!',
  role: 'user',
};

let seedData: string;
let local: MemoryStorage;
let session: MemoryStorage;
let auth: ReturnType<typeof createDemoAuthService>;

beforeAll(async () => {
  const initialLocal = new MemoryStorage();
  await createDemoAuthService(initialLocal, new MemoryStorage()).initialize();
  seedData = initialLocal.getItem(USERS_KEY)!;
});

beforeEach(() => {
  local = new MemoryStorage();
  session = new MemoryStorage();
  local.setItem(USERS_KEY, seedData);
  auth = createDemoAuthService(local, session);
});

async function loginAdmin() {
  return auth.login(DEMO_ACCOUNTS.admin.email, DEMO_ACCOUNTS.admin.password);
}

describe('autenticación demo local', () => {
  it('inicializa ambas cuentas una sola vez ante llamadas simultáneas y reinicios', async () => {
    local.clear();
    await Promise.all([auth.initialize(), auth.initialize(), auth.initialize()]);
    const initialized = local.getItem(USERS_KEY);
    await createDemoAuthService(local, session).initialize();
    expect(local.getItem(USERS_KEY)).toBe(initialized);
    const database = JSON.parse(initialized!);
    expect(database.users).toHaveLength(2);
    expect(database.users.map((user: { email: string }) => user.email)).toEqual([
      DEMO_ACCOUNTS.admin.email,
      DEMO_ACCOUNTS.user.email,
    ]);
    expect(database.users[0].password.salt).not.toBe(database.users[1].password.salt);
    expect(initialized).not.toContain(DEMO_ACCOUNTS.admin.password);
    expect(initialized).not.toContain(DEMO_ACCOUNTS.user.password);
  });

  it('coordina instancias independientes sin reemplazar las semillas existentes', async () => {
    local.clear();
    const second = createDemoAuthService(local, session);
    await Promise.all([auth.initialize(), second.initialize()]);
    const initialized = local.getItem(USERS_KEY);
    await auth.initialize();
    expect(local.getItem(USERS_KEY)).toBe(initialized);
    expect(JSON.parse(initialized!).users).toHaveLength(2);
  });

  it.each(['admin', 'user'] as const)('permite acceder con la cuenta %s y normaliza el correo', async (role) => {
    const account = DEMO_ACCOUNTS[role];
    const user = await auth.login(`  ${account.email.toUpperCase()}  `, account.password);
    expect(user).toMatchObject({ name: account.name, email: account.email, role });
    expect(Object.keys(user).sort()).toEqual(['createdAt', 'email', 'id', 'name', 'role']);
    expect(auth.getCurrentUser()).toEqual(user);
    const savedSession = JSON.parse(session.getItem(SESSION_KEY)!);
    expect(savedSession).toEqual({ version: 1, userId: user.id });
  });

  it('rechaza credenciales incorrectas sin crear una sesión', async () => {
    await expect(auth.login(DEMO_ACCOUNTS.admin.email, 'incorrecta123!')).rejects.toThrow('correo o la contraseña');
    await expect(auth.login('desconocida@example.local', 'incorrecta123!')).rejects.toThrow('correo o la contraseña');
    expect(auth.getCurrentUser()).toBeNull();
    expect(session.length).toBe(0);
  });

  it('conserva la sesión en una recarga y la limita al almacenamiento de esa pestaña', async () => {
    const user = await loginAdmin();
    expect(createDemoAuthService(local, session).getCurrentUser()).toEqual(user);
    expect(createDemoAuthService(local, new MemoryStorage()).getCurrentUser()).toBeNull();
    auth.logout();
    expect(auth.getCurrentUser()).toBeNull();
    expect(session.length).toBe(0);
    expect(local.getItem(USERS_KEY)).toBe(seedData);
  });

  it('permite al administrador crear usuarios persistentes y acceder con sus credenciales', async () => {
    await loginAdmin();
    const user = await auth.createUser({ ...newUser, name: '  Ana Pérez  ', email: ' ANA@EXAMPLE.LOCAL ' });
    expect(user).toMatchObject({ name: 'Ana Pérez', email: newUser.email, role: 'user' });
    expect(user).not.toHaveProperty('password');
    expect(local.getItem(USERS_KEY)).not.toContain(newUser.password);
    expect(auth.listUsers()).toHaveLength(3);
    const saved = local.getItem(USERS_KEY);
    const reloaded = createDemoAuthService(local, session);
    await reloaded.initialize();
    expect(local.getItem(USERS_KEY)).toBe(saved);
    expect(reloaded.listUsers()).toContainEqual(user);
    auth.logout();
    await expect(reloaded.login(newUser.email, newUser.password)).resolves.toEqual(user);
  });

  it('permite crear otro administrador y aplica su rol al gestionar usuarios', async () => {
    await loginAdmin();
    await auth.createUser({ ...newUser, role: 'admin' });
    auth.logout();
    await auth.login(newUser.email, newUser.password);
    expect(auth.listUsers()).toHaveLength(3);
    await expect(auth.createUser({ ...newUser, email: 'otra@example.local' })).resolves.toMatchObject({ role: 'user' });
  });

  it('bloquea la consulta y creación directa sin una sesión administradora', async () => {
    expect(() => auth.listUsers()).toThrow('Inicia sesión como administrador');
    await expect(auth.createUser(newUser)).rejects.toThrow('Inicia sesión como administrador');
    const user = await auth.login(DEMO_ACCOUNTS.user.email, DEMO_ACCOUNTS.user.password);
    user.role = 'admin';
    expect(() => auth.listUsers()).toThrow('Solo un administrador');
    await expect(auth.createUser(newUser)).rejects.toThrow('Solo un administrador');
    expect(local.getItem(USERS_KEY)).toBe(seedData);
  });

  it.each([
    [{ name: ' ' }, 'nombre'],
    [{ name: 'x'.repeat(81) }, 'nombre'],
    [{ email: 'correo-inválido' }, 'correo electrónico válido'],
    [{ password: 'corta' }, 'entre 8 y 128'],
    [{ password: 'x'.repeat(129) }, 'entre 8 y 128'],
    [{ role: 'superadmin' }, 'rol válido'],
  ])('valida los datos al crear un usuario: %j', async (invalid, message) => {
    await loginAdmin();
    await expect(auth.createUser({ ...newUser, ...invalid } as CreateUserInput)).rejects.toThrow(message);
    expect(auth.listUsers()).toHaveLength(2);
  });

  it('rechaza correos duplicados sin distinguir mayúsculas ni espacios', async () => {
    await loginAdmin();
    await expect(auth.createUser({ ...newUser, email: ` ${DEMO_ACCOUNTS.admin.email.toUpperCase()} ` }))
      .rejects.toThrow('Ya existe un usuario');
    expect(auth.listUsers()).toHaveLength(2);
  });

  it('conserva altas concurrentes y solo permite una alta para el mismo correo', async () => {
    await loginAdmin();
    const results = await Promise.allSettled([
      auth.createUser(newUser),
      auth.createUser({ ...newUser, email: newUser.email.toUpperCase() }),
      auth.createUser({ ...newUser, email: 'otra@example.local' }),
    ]);
    expect(results.filter((result) => result.status === 'fulfilled')).toHaveLength(2);
    expect(results.filter((result) => result.status === 'rejected')).toHaveLength(1);
    expect(auth.listUsers()).toHaveLength(4);
  });

  it('vuelve a comprobar el permiso cuando se cierra la sesión durante un alta', async () => {
    await loginAdmin();
    const originalDeriveBits = crypto.subtle.deriveBits.bind(crypto.subtle);
    let release!: () => void;
    const paused = new Promise<void>((resolve) => { release = resolve; });
    const deriveSpy = vi.spyOn(crypto.subtle, 'deriveBits').mockImplementation(async (...args) => {
      await paused;
      return originalDeriveBits(...args);
    });
    const creating = auth.createUser(newUser);
    // Dar paso al initialize asíncrono y a importKey antes de cerrar la sesión.
    await vi.waitFor(() => expect(deriveSpy).toHaveBeenCalled());
    auth.logout();
    release();
    await expect(creating).rejects.toThrow('Inicia sesión como administrador');
    expect(local.getItem(USERS_KEY)).toBe(seedData);
  });

  it('no permite modificar usuarios persistidos alterando los objetos públicos', async () => {
    await loginAdmin();
    const users = auth.listUsers();
    users[0].name = 'Cambio externo';
    users[1].role = 'admin';
    const current = auth.getCurrentUser()!;
    current.role = 'user';
    expect(auth.getCurrentUser()?.role).toBe('admin');
    expect(auth.listUsers()[0].name).toBe(DEMO_ACCOUNTS.admin.name);
    expect(auth.listUsers()[1].role).toBe('user');
    expect(local.getItem(USERS_KEY)).toBe(seedData);
  });

  it.each(['{malformado', JSON.stringify({ version: 1, users: [{}] })])(
    'informa datos locales corruptos y los conserva: %s',
    async (corrupted) => {
      local.setItem(USERS_KEY, corrupted);
      await expect(auth.initialize()).rejects.toThrow('datos de usuarios de la demo están dañados');
      expect(() => auth.getCurrentUser()).toThrow('datos de usuarios de la demo están dañados');
      expect(local.getItem(USERS_KEY)).toBe(corrupted);
    },
  );

  it('detecta usuarios duplicados en los datos persistidos', async () => {
    const database = JSON.parse(seedData);
    database.users.push(database.users[0]);
    local.setItem(USERS_KEY, JSON.stringify(database));
    await expect(auth.initialize()).rejects.toThrow('usuarios duplicados');
  });

  it.each(['{malformado', JSON.stringify({ version: 1, userId: 7 })])(
    'informa una sesión corrupta y permite cerrarla: %s',
    async (corrupted) => {
      session.setItem(SESSION_KEY, corrupted);
      await expect(auth.initialize()).rejects.toThrow('sesión de la demo está dañada');
      expect(() => auth.getCurrentUser()).toThrow('sesión de la demo está dañada');
      expect(session.getItem(SESSION_KEY)).toBe(corrupted);
      auth.logout();
      await expect(auth.initialize()).resolves.toBeUndefined();
      expect(auth.getCurrentUser()).toBeNull();
    },
  );

  it('trata una sesión de un usuario eliminado como una sesión sin acceso', () => {
    session.setItem(SESSION_KEY, JSON.stringify({ version: 1, userId: 'f'.repeat(32) }));
    expect(auth.getCurrentUser()).toBeNull();
    expect(() => auth.listUsers()).toThrow('Inicia sesión como administrador');
  });

  it('propaga fallos de lectura con un mensaje útil y permite reintentar initialize', async () => {
    const cause = new DOMException('Almacenamiento bloqueado', 'SecurityError');
    vi.spyOn(local, 'getItem').mockImplementationOnce(() => { throw cause; });
    await expect(auth.initialize()).rejects.toMatchObject({ message: expect.stringContaining('No se pudo leer'), cause });
    await expect(auth.initialize()).resolves.toBeUndefined();
  });

  it('informa errores al guardar semillas y no crea datos parciales', async () => {
    local.clear();
    vi.spyOn(local, 'setItem').mockImplementation(() => { throw new DOMException('Sin espacio', 'QuotaExceededError'); });
    await expect(auth.initialize()).rejects.toThrow('No se pudieron guardar');
    expect(local.length).toBe(0);
  });

  it('informa errores al guardar usuarios, abrir sesión y cerrar sesión', async () => {
    await loginAdmin();
    vi.spyOn(local, 'setItem').mockImplementation(() => { throw new DOMException('Sin espacio', 'QuotaExceededError'); });
    await expect(auth.createUser(newUser)).rejects.toThrow('No se pudieron guardar');
    expect(local.getItem(USERS_KEY)).toBe(seedData);
    auth.logout();
    vi.spyOn(session, 'setItem').mockImplementation(() => { throw new DOMException('Bloqueado', 'SecurityError'); });
    await expect(loginAdmin()).rejects.toThrow('No se pudieron guardar');
    expect(auth.getCurrentUser()).toBeNull();
    vi.spyOn(session, 'removeItem').mockImplementation(() => { throw new DOMException('Bloqueado', 'SecurityError'); });
    expect(() => auth.logout()).toThrow('No se pudo cerrar');
  });
});
