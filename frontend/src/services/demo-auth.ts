import type { CreateUserInput, DemoUser, UserRole } from '../types';

export const DEMO_ACCOUNTS = {
  admin: {
    name: 'Administrador demo',
    email: 'admin@tecpeopleflow.local',
    password: 'AdminDemo123!',
    role: 'admin',
  },
  user: {
    name: 'Usuario demo',
    email: 'usuario@tecpeopleflow.local',
    password: 'UsuarioDemo123!',
    role: 'user',
  },
} as const;

const USERS_KEY = 'tecpeopleflow.demo.users.v1';
const SESSION_KEY = 'tecpeopleflow.demo.session.v1';
const HASH_ITERATIONS = 210_000;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface StoredUser extends DemoUser {
  password: {
    salt: string;
    hash: string;
    iterations: number;
  };
}

interface UserDatabase {
  version: 1;
  users: StoredUser[];
}

export interface DemoAuthService {
  initialize(): Promise<void>;
  login(email: string, password: string): Promise<DemoUser>;
  logout(): void;
  getCurrentUser(): DemoUser | null;
  listUsers(): DemoUser[];
  createUser(input: CreateUserInput): Promise<DemoUser>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isRole(value: unknown): value is UserRole {
  return value === 'admin' || value === 'user';
}

function validEmail(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 254 && EMAIL_PATTERN.test(value);
}

function normalizeEmail(value: string): string {
  const email = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (!validEmail(email)) throw new Error('Escribe un correo electrónico válido.');
  return email;
}

function validateInput(input: CreateUserInput): CreateUserInput {
  if (!input || typeof input.name !== 'string' || input.name.trim().length < 2 || input.name.trim().length > 80) {
    throw new Error('El nombre debe tener entre 2 y 80 caracteres.');
  }
  const email = normalizeEmail(input.email);
  if (typeof input.password !== 'string' || input.password.length < 8 || input.password.length > 128) {
    throw new Error('La contraseña debe tener entre 8 y 128 caracteres.');
  }
  if (!isRole(input.role)) throw new Error('Selecciona un rol válido: administrador o usuario.');
  return { name: input.name.trim(), email, password: input.password, role: input.role };
}

function publicUser(user: StoredUser): DemoUser {
  return { id: user.id, name: user.name, email: user.email, role: user.role, createdAt: user.createdAt };
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function fromHex(value: string): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(value.match(/.{2}/g) ?? [], (byte) => Number.parseInt(byte, 16));
}

function browserCrypto(): Crypto {
  if (!globalThis.crypto?.subtle || !globalThis.crypto.getRandomValues) {
    throw new Error('Este navegador necesita un contexto seguro (HTTPS o localhost) para usar la demo.');
  }
  return globalThis.crypto;
}

async function deriveHash(password: string, salt: string, iterations: number): Promise<string> {
  const crypto = browserCrypto();
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: fromHex(salt), iterations },
    key,
    256,
  );
  return toHex(new Uint8Array(bits));
}

async function storedUser(input: CreateUserInput): Promise<StoredUser> {
  const crypto = browserCrypto();
  const salt = toHex(crypto.getRandomValues(new Uint8Array(16)));
  const hash = await deriveHash(input.password, salt, HASH_ITERATIONS);
  return {
    id: toHex(crypto.getRandomValues(new Uint8Array(16))),
    name: input.name,
    email: input.email,
    role: input.role,
    createdAt: new Date().toISOString(),
    password: { salt, hash, iterations: HASH_ITERATIONS },
  };
}

function isStoredUser(value: unknown): value is StoredUser {
  if (!isRecord(value) || !isRecord(value.password)) return false;
  return (
    typeof value.id === 'string' && /^[a-f0-9]{32}$/.test(value.id) &&
    typeof value.name === 'string' && value.name === value.name.trim() && value.name.length >= 2 && value.name.length <= 80 &&
    validEmail(value.email) && value.email === value.email.trim().toLowerCase() &&
    isRole(value.role) &&
    typeof value.createdAt === 'string' && Number.isFinite(Date.parse(value.createdAt)) &&
    typeof value.password.salt === 'string' && /^[a-f0-9]{32}$/.test(value.password.salt) &&
    typeof value.password.hash === 'string' && /^[a-f0-9]{64}$/.test(value.password.hash) &&
    value.password.iterations === HASH_ITERATIONS
  );
}

export function createDemoAuthService(local: Storage, session: Storage): DemoAuthService {
  let initialization: Promise<void> | undefined;

  function read(storage: Storage, key: string): string | null {
    try {
      return storage.getItem(key);
    } catch (cause) {
      throw new Error('No se pudo leer el almacenamiento de la demo. Revisa los permisos del navegador.', { cause });
    }
  }

  function write(storage: Storage, key: string, value: unknown): void {
    try {
      storage.setItem(key, JSON.stringify(value));
    } catch (cause) {
      throw new Error('No se pudieron guardar los datos de la demo. Revisa el espacio y los permisos del navegador.', { cause });
    }
  }

  function readDatabase(): UserDatabase | null {
    const raw = read(local, USERS_KEY);
    if (raw === null) return null;
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch (cause) {
      throw new Error('Los datos de usuarios de la demo están dañados. Revisa el almacenamiento local.', { cause });
    }
    if (!isRecord(value) || value.version !== 1 || !Array.isArray(value.users) || !value.users.every(isStoredUser)) {
      throw new Error('Los datos de usuarios de la demo están dañados. Revisa el almacenamiento local.');
    }
    const ids = new Set(value.users.map((user) => user.id));
    const emails = new Set(value.users.map((user) => user.email));
    if (ids.size !== value.users.length || emails.size !== value.users.length) {
      throw new Error('Los datos de usuarios de la demo están dañados: hay usuarios duplicados.');
    }
    return { version: 1, users: value.users };
  }

  function readSession(): string | null {
    const raw = read(session, SESSION_KEY);
    if (raw === null) return null;
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch (cause) {
      throw new Error('La sesión de la demo está dañada. Cierra la sesión e inténtalo de nuevo.', { cause });
    }
    if (!isRecord(value) || value.version !== 1 || typeof value.userId !== 'string' || !/^[a-f0-9]{32}$/.test(value.userId)) {
      throw new Error('La sesión de la demo está dañada. Cierra la sesión e inténtalo de nuevo.');
    }
    return value.userId;
  }

  function requireAdmin(): UserDatabase {
    const database = readDatabase();
    const userId = readSession();
    const user = database?.users.find((candidate) => candidate.id === userId);
    if (!user) throw new Error('Inicia sesión como administrador para gestionar usuarios.');
    if (user.role !== 'admin') throw new Error('Solo un administrador puede gestionar usuarios.');
    return database!;
  }

  async function initializeStorage(): Promise<void> {
    const database = readDatabase();
    readSession();
    if (database) return;
    const users = await Promise.all(Object.values(DEMO_ACCOUNTS).map((account) => storedUser(account)));
    // Otra instancia puede haber inicializado el mismo almacenamiento durante el hash.
    if (readDatabase() === null) write(local, USERS_KEY, { version: 1, users });
  }

  async function initialize(): Promise<void> {
    if (initialization) return initialization;
    const pending = initializeStorage();
    initialization = pending;
    try {
      await pending;
    } finally {
      if (initialization === pending) initialization = undefined;
    }
  }

  return {
    initialize,

    async login(email, password) {
      await initialize();
      const normalizedEmail = normalizeEmail(email);
      const user = readDatabase()?.users.find((candidate) => candidate.email === normalizedEmail);
      if (!user || typeof password !== 'string' || password.length < 8 || password.length > 128) {
        throw new Error('El correo o la contraseña son incorrectos.');
      }
      const hash = await deriveHash(password, user.password.salt, user.password.iterations);
      let difference = 0;
      for (let index = 0; index < hash.length; index += 1) {
        difference |= hash.charCodeAt(index) ^ user.password.hash.charCodeAt(index);
      }
      if (difference !== 0) throw new Error('El correo o la contraseña son incorrectos.');
      write(session, SESSION_KEY, { version: 1, userId: user.id });
      return publicUser(user);
    },

    logout() {
      try {
        session.removeItem(SESSION_KEY);
      } catch (cause) {
        throw new Error('No se pudo cerrar la sesión de la demo. Revisa los permisos del navegador.', { cause });
      }
    },

    getCurrentUser() {
      const database = readDatabase();
      const userId = readSession();
      const user = database?.users.find((candidate) => candidate.id === userId);
      return user ? publicUser(user) : null;
    },

    listUsers() {
      return requireAdmin().users.map(publicUser);
    },

    async createUser(input) {
      await initialize();
      const database = requireAdmin();
      const validated = validateInput(input);
      if (database.users.some((user) => user.email === validated.email)) {
        throw new Error('Ya existe un usuario con ese correo electrónico.');
      }
      const user = await storedUser(validated);
      // Verificar de nuevo evita perder altas concurrentes o usar una sesión cerrada.
      const currentDatabase = requireAdmin();
      if (currentDatabase.users.some((candidate) => candidate.email === user.email)) {
        throw new Error('Ya existe un usuario con ese correo electrónico.');
      }
      write(local, USERS_KEY, { version: 1, users: [...currentDatabase.users, user] });
      return publicUser(user);
    },
  };
}

function browserStorage(key: 'localStorage' | 'sessionStorage'): Storage {
  // El acceso diferido permite informar errores de almacenamiento desde la interfaz.
  return {
    get length() { return window[key].length; },
    clear() { window[key].clear(); },
    key(index) { return window[key].key(index); },
    getItem(name) { return window[key].getItem(name); },
    setItem(name, value) { window[key].setItem(name, value); },
    removeItem(name) { window[key].removeItem(name); },
  };
}

export const demoAuth = createDemoAuthService(browserStorage('localStorage'), browserStorage('sessionStorage'));
