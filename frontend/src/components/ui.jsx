import { useEffect, useRef, useState } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import listPlugin from '@fullcalendar/list';
import { api, downloadIcs } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useNotifications } from '../context/NotificationContext.jsx';

export const fmt = (iso) => new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

export function useLoad(fn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;                // always call the latest fetcher
  const seq = useRef(0);             // ignore out-of-order / stale responses
  const alive = useRef(true);
  const reload = () => {
    const id = ++seq.current;
    return fnRef.current()
      .then((x) => { if (alive.current && id === seq.current) { setData(x); setError(null); } })
      .catch((e) => { if (alive.current && id === seq.current) setError(e); });
  };
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { setData(null); reload(); }, deps);   // clear old data when inputs change
  return [data, error, reload];
}

export const Loader = () => <div className="loader" role="status" aria-label="Loading" />;

export const StatusBadge = ({ status }) => (
  <span className={'badge b-' + status}>{String(status).replace(/_/g, ' ')}</span>
);

const NAV = {
  STUDENT: [['dashboard', 'Dashboard'], ['companies', 'Companies'], ['calendar', 'Calendar']],
  INTERVIEWER: [['dashboard', 'Dashboard'], ['profile', 'Profile'], ['availability', 'Availability'],
    ['proposals', 'Proposals'], ['results', 'Results'], ['calendar', 'Calendar']],
  COORDINATOR: [['dashboard', 'Dashboard'], ['matching', 'Matching'], ['notice', 'Notice'], ['calendar', 'Calendar']],
};

export function Navbar() {
  const { user, logout } = useAuth();
  const { unread } = useNotifications();
  const role = user.role.toLowerCase();
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const h = () => setHash(window.location.hash);
    window.addEventListener('hashchange', h);
    return () => window.removeEventListener('hashchange', h);
  }, []);
  return (
    <header className="nav">
      <span className="brand"><span className="mark" aria-hidden="true" />Aetherion</span>
      <nav aria-label="Main">
        {NAV[user.role].map(([k, label]) => {
          const active = hash.startsWith(`#/${role}/${k}`);
          return <a key={k} href={`#/${role}/${k}`} className={active ? 'active' : ''} aria-current={active ? 'page' : undefined}>{label}</a>;
        })}
      </nav>
      <span className="grow" />
      <a className="bell" href={`#/${role}/notifications`} aria-label={`Notifications, ${unread} unread`}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {unread > 0 && <span className="dot">{unread}</span>}
      </a>
      <span className="who">{user.name}</span>
      <button onClick={logout}>Log out</button>
    </header>
  );
}

export const Layout = ({ children }) => (<><Navbar /><main className="wrap">{children}</main></>);

export function SlotCard({ slot, children }) {
  return (
    <div className="card slot">
      <div>
        <strong>{fmt(slot.start)}</strong> to {new Date(slot.end).toLocaleTimeString([], { timeStyle: 'short' })}
        <div className="muted">{slot.interviewerNames.join(', ')} · {slot.room}</div>
      </div>
      <div className="actions">{children}</div>
    </div>
  );
}

export function ConfirmDialog({ title, children, onConfirm, onCancel, confirmLabel = 'Confirm' }) {
  return (
    <div className="overlay">
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        {children}
        <div className="actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

export function CalendarView() {
  const { flash } = useNotifications();
  const [events, setEvents] = useState([]);
  const [sel, setSel] = useState(null);
  const load = (info) =>
    api('GET', `/calendar?from=${encodeURIComponent(info.startStr)}&to=${encodeURIComponent(info.endStr)}`)
      .then(setEvents).catch(() => {});
  return (
    <>
      <FullCalendar
        plugins={[dayGridPlugin, timeGridPlugin, listPlugin]}
        initialView="dayGridMonth"
        headerToolbar={{ left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,listWeek' }}
        events={events}
        datesSet={load}
        eventClick={(e) => setSel(events.find((x) => String(x.id) === e.event.id))}
        height="auto"
      />
      {sel && (
        <ConfirmDialog title={sel.title} confirmLabel="Download .ics" onCancel={() => setSel(null)}
          onConfirm={() => downloadIcs(sel.id).catch((x) => flash((x && x.message) || 'Download failed'))}>
          <p>{fmt(sel.start)}</p>
          <p>Room: {sel.room}</p>
          <p>Interviewers: {sel.interviewerNames.join(', ')}</p>
          <StatusBadge status={sel.status} />
        </ConfirmDialog>
      )}
    </>
  );
}