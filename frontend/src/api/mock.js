const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const err = (code, message) => { throw Object.assign(new Error(message), { code }); };

const users = {
  'student@demo.com': { id: 1, name: 'Asha Student', email: 'student@demo.com', role: 'STUDENT' },
  'interviewer@demo.com': { id: 2, name: 'Dr. Rao', email: 'interviewer@demo.com', role: 'INTERVIEWER' },
  'coord@demo.com': { id: 3, name: 'Coordinator', email: 'coord@demo.com', role: 'COORDINATOR' },
};
const companies = [
  { id: 1, name: 'Acme Corp', roundsConfig: ['Coding', 'Tech', 'HR'] },
  { id: 2, name: 'Globex', roundsConfig: ['Coding', 'HR'] },
];
const base = new Date();
base.setUTCHours(9, 0, 0, 0);
base.setUTCDate(base.getUTCDate() + 3);
const at = (i) => new Date(base.getTime() + i * 30 * 60000).toISOString().replace('.000Z', 'Z');
const ALL = [1, 2, 3, 4, 5, 6].map((i) => ({
  slotId: i, companyId: i < 5 ? 1 : 2, start: at(i - 1), end: at(i), interviewerNames: ['Dr. Rao'], room: 'Room A',
}));

let taken = new Set();
let prefs = [];
let interviews = [];
let drafts = [];
let notes = [];
let nid = 1, iid = 1, slotTakenShown = false;

const note = (type, message, interviewId = null) =>
  notes.unshift({ id: nid++, type, payload: { interviewId, message }, readAt: null });

export async function mockHandle(method, path, body) {
  await wait(150);
  const [p, qs] = path.split('?');
  const q = new URLSearchParams(qs || '');
  let m;

  if (p === '/auth/login') {
    const u = users[body.email];
    if (!u) err('UNAUTHORIZED', 'Unknown user. Try student@demo.com, interviewer@demo.com or coord@demo.com');
    return { token: 'mock-' + u.id, user: u };
  }
  if (p === '/auth/register') {
    return { token: 'mock-1', user: { id: 1, name: body.name, email: body.email, role: 'STUDENT' } };
  }
  if (p === '/me') return { user: users['student@demo.com'], profile: {} };

  if (p === '/companies') {
    return companies.map((c) => ({ ...c, openSlotCount: ALL.filter((s) => s.companyId === c.id && !taken.has(s.slotId)).length }));
  }
  if ((m = p.match(/^\/companies\/(\d+)\/slots$/))) {
    return ALL.filter((s) => s.companyId === +m[1] && !taken.has(s.slotId));
  }

  if (p === '/interviewer/profile') return body;
  if (p === '/interviewer/availability') {
    return body.slots.map((s, i) => ({ slotId: 100 + i, ...s, status: 'FREE' }));
  }
  if (p === '/interviewer/proposals') return interviews.filter((i) => i.status === 'PROPOSED');
  if ((m = p.match(/^\/interviewer\/interviews\/(\d+)\/(confirm|cancel|result)$/))) {
    const iv = interviews.find((i) => i.id === +m[1]);
    if (!iv) err('NOT_FOUND', 'Interview not found');
    if (m[2] === 'confirm') {
      iv.status = 'INTERVIEWER_CONFIRMED';
      note('INTERVIEW_CONFIRMED', 'Interviewer confirmed your interview', iv.id);
      return iv;
    }
    if (m[2] === 'cancel') {
      iv.status = 'FLAGGED';
      note('INTERVIEW_CANCELLED', 'An interview was cancelled: ' + (body.reason || ''), iv.id);
      return { flaggedInterviews: [iv.id] };
    }
    iv.status = 'COMPLETED';
    note('RESULT_RELEASED', `Result: ${body.verdict}`, iv.id);
    return { verdict: body.verdict, score: body.score };
  }

  if (p === '/student/preferences') {
    if (body.choices.some((c) => c.slotId === 3) && !slotTakenShown) {
      slotTakenShown = true;
      taken.add(3);
      err('SLOT_TAKEN', 'Slot just taken, please pick another');
    }
    prefs = prefs.filter((x) => !(x.companyId === body.companyId && x.roundNo === body.roundNo));
    body.choices.forEach((c) => {
      const s = ALL.find((x) => x.slotId === c.slotId);
      prefs.push({ slotId: c.slotId, rank: c.rank, companyId: body.companyId, roundNo: body.roundNo, status: 'PENDING', start: s && s.start });
    });
    prefs.sort((a, b) => a.rank - b.rank);
    return { status: 'PENDING' };
  }
  if (p === '/student/status') {
    const live = interviews.filter((i) => i.status !== 'CANCELLED');
    const statusText = live.some((i) => i.status === 'CONFIRMED') ? 'Confirmed. See your calendar.'
      : live.length ? 'Matched. Awaiting confirmation.'
      : prefs.length ? 'Pending. Matching has not run yet.' : 'No preferences submitted yet.';
    return { preferences: prefs, interviews, statusText };
  }
  if ((m = p.match(/^\/student\/interviews\/(\d+)\/ics$/))) {
    return `BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:mock-${m[1]}@trials\nSUMMARY:Interview\nEND:VEVENT\nEND:VCALENDAR`;
  }

  if (p === '/coordinator/matching/run') {
    setTimeout(() => {
      const version = drafts.length + 1;
      drafts.forEach((d) => { if (d.status === 'DRAFT') d.status = 'SUPERSEDED'; });
      interviews = interviews.filter((i) => i.status === 'CONFIRMED');
      const mine = prefs.filter((x) => x.roundNo === body.roundNo && x.rank === 1);
      mine.forEach((x) => {
        const s = ALL.find((y) => y.slotId === x.slotId);
        const c = companies.find((y) => y.id === x.companyId);
        interviews.push({
          id: iid++, studentId: 1, studentName: 'Asha Student', companyId: c.id, companyName: c.name,
          roundNo: x.roundNo, type: 'ONE_ON_ONE', start: s.start, end: s.end, room: s.room,
          status: 'PROPOSED', version, draftId: version,
          panel: [{ interviewerId: 2, name: 'Dr. Rao', skill: 'Coding' }],
        });
        x.status = 'MATCHED';
      });
      drafts.push({ draftId: version, version, status: 'DRAFT', objectiveValue: 100 * mine.length, matched: mine.length, unmatched: 0, roundNo: body.roundNo });
      note('NOTICE', 'Your interview has been proposed');
    }, 2500);
    return { jobId: 'job-' + Date.now() };
  }
  if (p === '/coordinator/drafts') return drafts.filter((d) => d.roundNo === +q.get('roundNo'));
  if ((m = p.match(/^\/coordinator\/drafts\/(\d+)$/))) {
    const d = drafts.find((x) => x.draftId === +m[1]);
    return { draft: d, interviews: interviews.filter((i) => i.draftId === d.draftId), unmatchedStudents: [] };
  }
  if ((m = p.match(/^\/coordinator\/drafts\/(\d+)\/approve$/))) {
    const d = drafts.find((x) => x.draftId === +m[1]);
    const latest = Math.max(...drafts.map((x) => x.version));
    if (body.version !== latest || d.status !== 'DRAFT') err('STALE_DRAFT', 'A newer draft exists. Please refresh.');
    d.status = 'APPROVED';
    const mine = interviews.filter((i) => i.draftId === d.draftId);
    mine.forEach((i) => { i.status = 'CONFIRMED'; note('INTERVIEW_CONFIRMED', 'Your interview is confirmed', i.id); });
    return { committed: mine.length };
  }
  if (p === '/coordinator/notice') { note('NOTICE', body.message); return { queued: 3 }; }

  if (p === '/calendar') {
    return interviews.filter((i) => i.status !== 'CANCELLED').map((i) => ({
      id: i.id, title: `${i.companyName} R${i.roundNo}`, start: i.start, end: i.end,
      room: i.room, interviewerNames: i.panel.map((x) => x.name), status: i.status,
    }));
  }
  if (p === '/notifications') return notes;
  if ((m = p.match(/^\/notifications\/(\d+)\/read$/))) {
    const n = notes.find((x) => x.id === +m[1]);
    if (n) n.readAt = new Date().toISOString();
    return n;
  }
  err('NOT_FOUND', `No mock for ${method} ${p}`);
}