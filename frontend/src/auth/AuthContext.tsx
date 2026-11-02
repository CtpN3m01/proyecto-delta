import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { demoAuth } from '../services/demo-auth';
import type { CreateUserInput, DemoUser } from '../types';

interface AuthState {
  user: DemoUser | null;
  users: DemoUser[];
  loading: boolean;
  startupError: string | null;
  login: (email: string, password: string) => Promise<DemoUser>;
  logout: () => void;
  createUser: (input: CreateUserInput) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<DemoUser | null>(null);
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    const current = demoAuth.getCurrentUser();
    setUser(current);
    setUsers(current?.role === 'admin' ? demoAuth.listUsers() : []);
  }, []);

  useEffect(() => {
    let active = true;
    demoAuth.initialize().then(() => {
      if (active) refresh();
    }).catch((error: unknown) => {
      if (active) setStartupError(error instanceof Error ? error.message : 'No pudimos iniciar la demostración.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const current = await demoAuth.login(email, password);
    refresh();
    return current;
  }, [refresh]);

  const logout = useCallback(() => {
    demoAuth.logout();
    setUser(null);
    setUsers([]);
  }, []);

  const createUser = useCallback(async (input: CreateUserInput) => {
    await demoAuth.createUser(input);
    refresh();
  }, [refresh]);

  const value = useMemo(() => ({ user, users, loading, startupError, login, logout, createUser }),
    [user, users, loading, startupError, login, logout, createUser]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth debe usarse dentro de AuthProvider.');
  return context;
}
