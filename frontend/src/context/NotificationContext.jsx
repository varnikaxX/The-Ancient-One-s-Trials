import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { api, BASE, USE_MOCK } from '../api/client.js';
import { useAuth } from './AuthContext.jsx';
import Toast from '../components/Toast.jsx';

const Ctx = createContext(null);
export const useNotifications = () => useContext(Ctx);

export function NotificationProvider({ children }) {
  const { auth } = useAuth();
  const [items, setItems] = useState([]);
  const [toast, setToast] = useState(null);
  const seen = useRef(new Set());

  const load = async (first) => {
    try {
      const list = await api('GET', '/notifications');
      list.forEach((n) => {
        if (!seen.current.has(n.id)) {
          seen.current.add(n.id);
          if (!first && !n.readAt) setToast(n.payload.message);
        }
      });
      setItems(list);
    } catch { /* ignore, next poll retries */ }
  };

  useEffect(() => {
    if (!auth) { setItems([]); return; }
    seen.current = new Set();
    load(true);
    // Mock mode: a fast interval stands in for SSE. Real mode: SSE plus a 15s fallback poll.
    const timer = setInterval(() => load(false), USE_MOCK ? 4000 : 15000);
    let es;
    if (!USE_MOCK && 'EventSource' in window) {
      es = new EventSource(`${BASE}/events?token=${encodeURIComponent(auth.token)}`);
      es.onmessage = () => load(false);
    }
    return () => { clearInterval(timer); if (es) es.close(); };
  }, [auth]);

  const markRead = async (id) => {
    await api('POST', `/notifications/${id}/read`, {});
    setItems((l) => l.map((n) => (n.id === id ? { ...n, readAt: new Date().toISOString() } : n)));
  };
  const unread = items.filter((n) => !n.readAt).length;

  return (
    <Ctx.Provider value={{ items, unread, markRead, flash: setToast }}>
      {children}
      {toast && <Toast msg={toast} onClose={() => setToast(null)} />}
    </Ctx.Provider>
  );
}