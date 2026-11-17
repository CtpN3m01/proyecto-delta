declare global { interface Window { DELTA_CONFIG?: { coordinatorUrl: string; partyUrls: string[]; storageUrl: string; mode?: string } } }
export const config = {
  coordinatorUrl: window.DELTA_CONFIG?.coordinatorUrl ?? import.meta.env.VITE_DELTA_COORDINATOR_URL ?? 'http://127.0.0.1:8000',
  partyUrls: window.DELTA_CONFIG?.partyUrls ?? (import.meta.env.VITE_DELTA_PARTY_URLS ?? 'http://127.0.0.1:8100,http://127.0.0.1:8101,http://127.0.0.1:8102').split(','),
  storageUrl: window.DELTA_CONFIG?.storageUrl ?? import.meta.env.VITE_DELTA_STORAGE_URL ?? 'http://127.0.0.1:8200',
};
