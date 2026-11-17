import PocketBase, { BaseAuthStore, type RecordModel } from 'pocketbase';

const AUTH_STORAGE_KEY = 'tecpeopleflow.pocketbase.auth.v1';

class SessionAuthStore extends BaseAuthStore {
  constructor() {
    super();
    try {
      const saved = window.sessionStorage.getItem(AUTH_STORAGE_KEY);
      if (saved) {
        const value: unknown = JSON.parse(saved);
        if (typeof value === 'object' && value !== null && 'token' in value && typeof value.token === 'string') {
          this.save(value.token, 'record' in value ? value.record as RecordModel : null);
        }
      }
    } catch {
      window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
    }
  }

  override save(token: string, record?: RecordModel | null) {
    super.save(token, record);
    if (token) window.sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token, record: record ?? null }));
    else window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }

  override clear() {
    super.clear();
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }
}

const pocketbaseUrl = import.meta.env.VITE_POCKETBASE_URL || 'http://127.0.0.1:8090';
export const pb = new PocketBase(pocketbaseUrl, new SessionAuthStore());
