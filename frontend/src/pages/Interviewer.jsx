import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { Layout, Loader, CalendarView, ConfirmDialog, useLoad, fmt } from '../components/ui.jsx';
import { useNotifications } from '../context/NotificationContext.jsx';

const errMsg = (x) => (x && x.message) || 'Something went wrong. Please try again.';

/* ------------------------------------------------------------------ */
export function InterviewerDashboard() {
  const [p, err] = useLoad(() => api('GET', '/interviewer/proposals'));
  return (
    <Layout>
      <h1>Interviewer Hall</h1>
      <div className="card">
        <p className="big">
          {err ? 'Could not load proposals' : p ? `${p.length} proposal(s) awaiting your confirmation` : '…'}
        </p>
        <a href="#/interviewer/proposals">Review proposals</a> · <a href="#/interviewer/availability">Set availability</a>
      </div>
    </Layout>
  );
}

/* ------------------------------------------------------------------ */
export function ProfileForm() {
  const { flash } = useNotifications();
  const [companies] = useLoad(() => api('GET', '/companies'));
  const [me, meErr] = useLoad(() => api('GET', '/me'));
  const [companyId, setCompanyId] = useState('');
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const filled = useRef(false);

  // Pre-fill once from the saved profile (accepts camelCase or snake_case).
  useEffect(() => {
    if (!me || filled.current) return;
    filled.current = true;
    const p = me.profile || {};
    const cid = p.companyId ?? p.company_id;
    setCompanyId(cid ? String(cid) : '');
    setTags(p.skillTags ?? p.skill_tags ?? []);
  }, [me]);

  const toggle = (s) => setTags((t) => (t.includes(s) ? t.filter((x) => x !== s) : [...t, s]));

  const save = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!companyId || !tags.length) return flash('Pick a company and at least one skill');
    setBusy(true);
    try {
      await api('PUT', '/interviewer/profile', { companyId: +companyId, skillTags: tags });
      flash('Profile saved');
    } catch (x) {
      flash(errMsg(x));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <h1>Profile</h1>
      {meErr && <p className="muted">Could not load your saved profile: {errMsg(meErr)}</p>}
      <form className="card" onSubmit={save}>
        <label>Company
          <select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            <option value="">Select…</option>
            {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <fieldset><legend>Skill tags</legend>
          {['Coding', 'Tech', 'HR'].map((s) => (
            <label key={s} className="inline">
              <input type="checkbox" checked={tags.includes(s)} onChange={() => toggle(s)} /> {s}
            </label>
          ))}
        </fieldset>
        <button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      </form>
    </Layout>
  );
}

/* ------------------------------------------------------------------ */
const DAYS = 14, CELLS = 16; // 09:00-17:00 in 30-min cells, starting tomorrow (UTC)
const cellTime = (d, c) => {
  const t = new Date();
  t.setUTCHours(9, 0, 0, 0);
  t.setUTCDate(t.getUTCDate() + d + 1);
  return new Date(t.getTime() + c * 30 * 60000);
};
const iso = (d) => d.toISOString().replace('.000Z', 'Z');

export function AvailabilityEditor() {
  const { flash } = useNotifications();
  const key = (d, c) => d + '-' + c;

  const [on, setOn] = useState(new Set());          // FREE cells the user has toggled on
  const [locked, setLocked] = useState(new Set());  // BOOKED/HELD cells (read-only)
  const [outside, setOutside] = useState([]);       // existing FREE slots not shown in this grid
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const mode = useRef(null);
  const init = useRef(false);

  // Existing slots come back inside GET /me (profile.slots).
  const [me, loadErr] = useLoad(() => api('GET', '/me'));
  const existing = me ? (me.profile && me.profile.slots) || [] : null;
  useEffect(() => {
    if (!existing || init.current) return;
    init.current = true;
    const byTime = new Map(existing.map((x) => [new Date(x.start).getTime(), x]));
    const free = new Set(), lock = new Set(), used = new Set();
    for (let d = 0; d < DAYS; d++) for (let c = 0; c < CELLS; c++) {
      const t = cellTime(d, c).getTime();
      const x = byTime.get(t);
      if (!x) continue;
      used.add(t);
      (x.status === 'FREE' ? free : lock).add(key(d, c));
    }
    // Keep future FREE slots that the grid can't show, so saving never deletes them.
    const now = Date.now();
    const out = existing
      .filter((x) => x.status === 'FREE' && !used.has(new Date(x.start).getTime()) && new Date(x.start).getTime() > now)
      .map((x) => ({ start: x.start, end: x.end }));
    setOn(free); setLocked(lock); setOutside(out);
  }, [me]);

  useEffect(() => {
    const up = () => { mode.current = null; };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  }, []);

  // Warn before leaving with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const h = (e) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [dirty]);

  const apply = (d, c) => {
    const k = key(d, c);
    if (locked.has(k)) return;
    setOn((s) => { const n = new Set(s); mode.current ? n.add(k) : n.delete(k); return n; });
    setDirty(true);
  };

  const ready = init.current || !!loadErr; // don't allow saving before existing slots are known

  const submit = async () => {
    if (busy) return;
    if (!ready) return flash('Still loading your current slots, try again in a moment');
    const slots = [...outside];
    for (let d = 0; d < DAYS; d++) for (let c = 0; c < CELLS; c++) if (on.has(key(d, c))) {
      const s = cellTime(d, c);
      slots.push({ start: iso(s), end: iso(new Date(s.getTime() + 30 * 60000)) });
    }
    if (loadErr && !window.confirm('Your current slots could not be loaded. Saving will replace them with what you see here. Continue?')) return;
    if (slots.length === 0 && !window.confirm('This will remove all of your free slots. Continue?')) return;
    setBusy(true);
    try {
      const saved = await api('PUT', '/interviewer/availability', { slots });
      const n = Array.isArray(saved) ? saved.length : slots.length;
      flash(n < slots.length
        ? `Saved ${n} of ${slots.length} slots (the rest had no free room or were in the past)`
        : `Saved ${n} slots`);
      setDirty(false);
    } catch (x) {
      flash(errMsg(x));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <h1>Availability</h1>
      <p className="muted">Click or drag to toggle 30-minute cells. Times are UTC. Booked cells are locked.</p>
      {loadErr && <p className="muted">Could not load your saved slots ({errMsg(loadErr)}). The grid below may not show them.</p>}
      {!existing && !loadErr && <Loader />}
      <div className="grid-wrap" style={{ userSelect: 'none' }}>
        <div className="grid" style={{ gridTemplateColumns: `70px repeat(${DAYS}, 1fr)` }}>
          <span />
          {Array.from({ length: DAYS }, (_, d) => (
            <strong key={d}>{cellTime(d, 0).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })}</strong>
          ))}
          {Array.from({ length: CELLS }, (_, c) => [
            <span key={'l' + c} className="muted">{cellTime(0, c).toISOString().slice(11, 16)}</span>,
            ...Array.from({ length: DAYS }, (_, d) => {
              const k = key(d, c);
              const isLocked = locked.has(k);
              return (
                <button key={k} type="button" disabled={isLocked}
                  title={isLocked ? 'Booked' : undefined}
                  className={'cell' + (on.has(k) ? ' on' : '') + (isLocked ? ' booked' : '')}
                  aria-pressed={on.has(k)}
                  aria-label={cellTime(d, c).toUTCString()}
                  onMouseDown={() => { mode.current = !on.has(k); apply(d, c); }}
                  onMouseEnter={() => { if (mode.current !== null) apply(d, c); }}
                  onClick={(e) => { if (e.detail === 0) { mode.current = !on.has(k); apply(d, c); mode.current = null; } }} />
              );
            }),
          ])}
        </div>
      </div>
      {outside.length > 0 && <p className="muted">{outside.length} more free slot(s) outside this grid will be kept.</p>}
      <button className="primary" onClick={submit} disabled={busy || !ready}>{busy ? 'Saving…' : 'Save availability'}</button>
    </Layout>
  );
}

/* ------------------------------------------------------------------ */
export function ProposalsReview() {
  const { flash } = useNotifications();
  const [list, e, reload] = useLoad(() => api('GET', '/interviewer/proposals'));
  const [range] = useState(() => ({
    from: new Date().toISOString(),
    to: new Date(Date.now() + 60 * 864e5).toISOString(),
  }));
  const [upcoming, , reloadUp] = useLoad(() => api('GET', `/calendar?from=${range.from}&to=${range.to}`));
  const [cancelId, setCancelId] = useState(null);
  const [reason, setReason] = useState('');
  const [busyId, setBusyId] = useState(null);
  const refresh = () => { reload(); reloadUp(); };

  const confirm = async (id) => {
    if (busyId) return;
    setBusyId(id);
    try { await api('POST', `/interviewer/interviews/${id}/confirm`, {}); flash('Accepted. Waiting for the coordinator to approve.'); }
    catch (x) { flash(errMsg(x)); }
    finally { setBusyId(null); refresh(); }
  };
  const cancel = async (id, why) => {
    if (busyId) return;
    setBusyId(id);
    try {
      const r = await api('POST', `/interviewer/interviews/${id}/cancel`, { reason: why });
      flash(r && r.declined && r.declined.length
        ? 'Proposal declined. The coordinator has been asked to re-run matching.'
        : 'Cancelled. Rescheduling has started.');
    } catch (x) { flash(errMsg(x)); }
    finally { setBusyId(null); refresh(); }
  };

  const mine = (upcoming || []).filter((x) => x.status === 'INTERVIEWER_CONFIRMED' || x.status === 'CONFIRMED');
  return (
    <Layout>
      <h1>Proposals</h1>
      {!list && !e && <Loader />}
      {e && <p className="muted">Could not load proposals: {errMsg(e)}</p>}
      {list && list.length === 0 && <p className="muted">No proposals waiting for you.</p>}
      {(list || []).map((i) => (
        <div key={i.id} className="card row">
          <span>{i.studentName} · {i.companyName} R{i.roundNo} · {fmt(i.start)} · {i.room}</span>
          <span>
            <button className="primary" disabled={busyId === i.id} onClick={() => confirm(i.id)}>Accept</button>
            <button disabled={busyId === i.id} onClick={() => { setCancelId(i.id); setReason(''); }}>Decline</button>
          </span>
        </div>
      ))}

      <h2>Your accepted and confirmed interviews</h2>
      {upcoming && mine.length === 0 && <p className="muted">Nothing accepted yet.</p>}
      {mine.map((x) => (
        <div key={x.id} className="card row">
          <span>{x.title} · {fmt(x.start)} · {x.status === 'CONFIRMED' ? 'Confirmed' : 'Accepted, awaiting coordinator'}</span>
          <button disabled={busyId === x.id} onClick={() => { setCancelId(x.id); setReason(''); }}>Cancel</button>
        </div>
      ))}

      {cancelId && (
        <ConfirmDialog title="Decline or cancel this interview" confirmLabel="Submit" onCancel={() => setCancelId(null)}
          onConfirm={() => {
            if (!reason.trim()) return flash('Please give a reason');
            const id = cancelId;
            setCancelId(null);
            cancel(id, reason.trim());
          }}>
          <label>Reason<textarea value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        </ConfirmDialog>
      )}
    </Layout>
  );
}

/* ------------------------------------------------------------------ */
export function ResultsEntry() {
  const { flash } = useNotifications();
  // Include the past: interviews are finished before results are entered.
  const [range] = useState(() => ({
    from: new Date(Date.now() - 30 * 864e5).toISOString(),
    to: new Date(Date.now() + 60 * 864e5).toISOString(),
  }));
  const [events, e, reload] = useLoad(() => api('GET', `/calendar?from=${range.from}&to=${range.to}`));
  const [form, setForm] = useState({});
  const [busyId, setBusyId] = useState(null);

  const set = (id, k, v) => setForm((f) => ({ ...f, [id]: { ...f[id], [k]: v } }));

  const submit = async (id) => {
    if (busyId) return;
    const f = form[id] || {};
    if (!f.verdict) return flash('Choose Pass or Fail');
    const score = Number(f.score);
    if (f.score === undefined || f.score === '' || Number.isNaN(score) || score < 0 || score > 100) {
      return flash('Enter a score between 0 and 100');
    }
    setBusyId(id);
    try {
      await api('POST', `/interviewer/interviews/${id}/result`, { verdict: f.verdict, score });
      flash('Result saved');
      reload();
    } catch (x) {
      flash(errMsg(x));
    } finally {
      setBusyId(null);
    }
  };

  const rows = (events || []).filter((x) => x.status === 'CONFIRMED');
  return (
    <Layout>
      <h1>Enter Results</h1>
      {!events && !e && <Loader />}
      {e && <p className="muted">Could not load interviews: {errMsg(e)}</p>}
      {events && rows.length === 0 && <p className="muted">No confirmed interviews awaiting a result.</p>}
      {rows.map((x) => (
        <div key={x.id} className="card row">
          <span>{x.title} · {fmt(x.start)}</span>
          <span>
            <select aria-label="Verdict" value={(form[x.id] || {}).verdict || ''} onChange={(ev) => set(x.id, 'verdict', ev.target.value)}>
              <option value="">Verdict…</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option>
            </select>
            <input aria-label="Score" type="number" min="0" max="100" placeholder="Score"
              value={(form[x.id] || {}).score ?? ''} onChange={(ev) => set(x.id, 'score', ev.target.value)} />
            <button className="primary" disabled={busyId === x.id} onClick={() => submit(x.id)}>Save</button>
          </span>
        </div>
      ))}
    </Layout>
  );
}

export const InterviewerCalendar = () => <Layout><h1>Interview Calendar</h1><CalendarView /></Layout>;
