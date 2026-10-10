// One place for the backend address. Set VITE_API_URL (see web/.env.example) when deploying.
export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const WS = API.replace(/^http/, 'ws');
