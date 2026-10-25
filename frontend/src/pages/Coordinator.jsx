import { useState } from 'react';
import { api } from '../api/client.js';
import { navigate } from '../router.js';
import { Layout, Loader, StatusBadge, CalendarView, ConfirmDialog, useLoad, fmt } from '../components/ui.jsx';
import { useNotifications } from '../context/NotificationContext.jsx';

export function CoordinatorDashboard() {
  return (
    <Layout>
      <h1>Coordinator Sanctum</h1>
      <div className="card">
        <a href="#/coordinator/matching">Run matching and review drafts</a> · <a href="#/coordinator/notice">Broadcast a notice</a> · <a href="#/coordinator/calendar">Calendar</a>
      </div>
    </Layout>
  );
}

export function MatchingControl() {
  const { flash } = useNotifications();
  const [round, setRound] = useState(1);
  const [tries, setTries] = useState(0);
  const [busy, setBusy] = useState(false);
  const [drafts, e, reload] = useLoad(() => api('GET', `/coordinator/drafts?roundNo=${round}`), [round]);

  const run = async () => {
    setBusy(true);
    const before = drafts ? drafts.length : 0;
    try {
      await api('POST', '/coordinator/matching/run', { roundNo: round });
      let found = false;
      for (let i = 1; i <= 30; i++) {
        setTries(i);
        await new Promise((r) => setTimeout(r, 2000));
        const l = await api('GET', `/coordinator/drafts?roundNo=${round}`);
        if (l.length > before) { found = true; flash('New draft is ready'); break; }
      }
      if (!found) flash('No new draft appeared. Check that the Celery worker is running and that students have submitted preferences.');
    } catch (x) { flash(x.message); }
    setBusy(false);
    reload();
  };
  return (
    <Layout>
      <h1>Matching</h1>
      <div className="card row">
        <label>Round
          <select value={round} onChange={(e) => setRound(+e.target.value)}>
            <option value={1}>1 · Coding</option><option value={2}>2 · Tech</option><option value={3}>3 · HR</option>
          </select>
        </label>
        <button className="primary" disabled={busy} onClick={run}>{busy ? `Solving… (check ${tries})` : 'Run matching'}</button>
      </div>
      {!drafts && !e && <Loader />}
      {drafts && drafts.length === 0 && <p className="muted">No drafts for this round yet.</p>}
      {(drafts || []).map((d) => (
        <div key={d.draftId} className="card row">
          <span>v{d.version} · objective {d.objectiveValue} · matched {d.matched} · unmatched {d.unmatched}</span>
          <span><StatusBadge status={d.status} /> <button onClick={() => navigate('/coordinator/draft/' + d.draftId)}>Review</button></span>
        </div>
      ))}
    </Layout>
  );
}

export function DraftReview({ param }) {
  const { flash } = useNotifications();
  const [d, e, reload] = useLoad(() => api('GET', `/coordinator/drafts/${param}`));
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const waiting = d ? d.interviews.filter((i) => i.status === 'PROPOSED').length : 0;
  const approve = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api('POST', `/coordinator/drafts/${param}/approve`, { version: d.draft.version });
      flash(`Approved. ${r.committed} interviews committed.`);
      reload();
    } catch (x) { if (x.code === 'STALE_DRAFT') setStale(true); else flash(x.message); }
    finally { setBusy(false); }
  };
  return (
    <Layout>
      <h1>Draft Review</h1>
      {!d && !e && <Loader />}
      {e && <p className="err">{e.message}</p>}
      {d && (
        <>
          <p>Version {d.draft.version} <StatusBadge status={d.draft.status} /></p>
          <table className="card">
            <thead><tr><th>Student</th><th>Company</th><th>Time</th><th>Room</th><th>Interviewers</th><th>Status</th></tr></thead>
            <tbody>{d.interviews.map((i) => (
              <tr key={i.id}><td>{i.studentName}</td><td>{i.companyName} R{i.roundNo}</td><td>{fmt(i.start)}</td><td>{i.room}</td>
                <td>{i.panel.map((x) => x.name).join(', ')}</td><td><StatusBadge status={i.status} /></td></tr>
            ))}</tbody>
          </table>
          <section className="card"><h2>Unmatched</h2>
            {d.unmatchedStudents.length === 0 && <p className="muted">Everyone is matched.</p>}
            <ul>{d.unmatchedStudents.map((u) => <li key={u.studentId}>{u.studentName || 'Student ' + u.studentId}: {u.reason}</li>)}</ul>
          </section>
          {d.draft.status === 'DRAFT' && waiting > 0 && (
            <p className="muted">Waiting for interviewers to confirm: {waiting} of {d.interviews.length}. You can approve once all are confirmed.</p>
          )}
          <button className="primary" disabled={d.draft.status !== 'DRAFT' || busy || waiting > 0} onClick={approve}>{busy ? 'Approving…' : 'Approve this draft'}</button>
        </>
      )}
      {stale && (
        <ConfirmDialog title="Draft is outdated" confirmLabel="Refresh" onCancel={() => setStale(false)}
          onConfirm={() => { setStale(false); navigate('/coordinator/matching'); }}>
          <p>A newer draft exists. Refresh to review the latest version.</p>
        </ConfirmDialog>
      )}
    </Layout>
  );
}

export function NoticeBroadcast() {
  const { flash } = useNotifications();
  const [message, setMessage] = useState('');
  const [audience, setAudience] = useState('ALL');
  const send = async (e) => {
    e.preventDefault();
    if (!message.trim()) return flash('Write a message first');
    try { const r = await api('POST', '/coordinator/notice', { message, audience }); flash(`Queued for ${r.queued} people`); setMessage(''); }
    catch (x) { flash(x.message); }
  };
  return (
    <Layout>
      <h1>Broadcast Notice</h1>
      <form className="card" onSubmit={send}>
        <label>Audience
          <select value={audience} onChange={(e) => setAudience(e.target.value)}>
            <option value="ALL">Everyone</option><option value="STUDENT">Students</option><option value="INTERVIEWER">Interviewers</option>
          </select>
        </label>
        <label>Message<textarea value={message} onChange={(e) => setMessage(e.target.value)} /></label>
        <button className="primary">Send</button>
      </form>
    </Layout>
  );
}

export const CoordinatorCalendar = () => <Layout><h1>All Interviews</h1><CalendarView /></Layout>;