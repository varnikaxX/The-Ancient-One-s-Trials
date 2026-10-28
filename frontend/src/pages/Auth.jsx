import { useState } from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import { navigate, home } from '../router.js';

function AuthShell({ children }) {
  return (
    <div className="auth-shell">
      <aside className="auth-art">
        <span className="brand"><span className="mark" aria-hidden="true" />Aetherion</span>
        <div className="auth-copy">
          <h2>Shared thoughts.<br />Connected teams.</h2>
          <p>Bringing organisation into chaos,<br />one task at a time</p>
        </div>
      </aside>
      <main className="auth-panel">{children}</main>
    </div>
  );
}

const ROLES = [
  { key: 'STUDENT', label: 'Student', hint: 'Rank your slots and track your interviews.',
    icon: <><path d="M22 10 12 5 2 10l10 5 10-5z" /><path d="M6 12v5c3 2 9 2 12 0v-5" /></> },
  { key: 'INTERVIEWER', label: 'Interviewer', hint: 'Set availability, accept proposals and record results.',
    icon: <><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M8 9h8M8 13h5" /></> },
  { key: 'COORDINATOR', label: 'Coordinator', hint: 'Run matching, approve schedules and send notices.',
    icon: <><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18M9 16l2 2 4-4" /></> },
];
const LABEL = Object.fromEntries(ROLES.map((r) => [r.key, r.label]));

export function LoginPage() {
  const { login } = useAuth();
  const [role, setRole] = useState('STUDENT');
  const [f, setF] = useState({ email: '', password: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const pick = (k) => { setRole(k); setErr(''); };
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try { const u = await login(f.email, f.password, role); navigate(home(u.role)); }
    catch (x) {
      setErr(x && x.code === 'WRONG_ROLE'
        ? `This account belongs to the ${LABEL[x.role]} gateway. Please choose it above.`
        : (x && x.message) || 'Could not sign in');
    }
    finally { setBusy(false); }
  };
  const current = ROLES.find((r) => r.key === role);
  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit}>
        <h1>Sign in</h1>
        <div className="title-rule" />
        <p className="role-label" id="gateway-label">Please select your gateway</p>
        <div className="role-picker" role="radiogroup" aria-labelledby="gateway-label">
          {ROLES.map((r) => (
            <button key={r.key} type="button" role="radio" aria-checked={role === r.key} className="role-card" onClick={() => pick(r.key)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{r.icon}</svg>
              {r.label}
            </button>
          ))}
        </div>
        <p className="role-hint">{current.hint}</p>
        <label>Email address
          <input type="email" required autoComplete="email" placeholder="you@college.edu" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </label>
        <label>Password
          <input type="password" required autoComplete="current-password" placeholder="Password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </label>
        {err && <p className="err" role="alert">{err}</p>}
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : `Sign in as ${current.label}`}</button>
        {role === 'STUDENT'
          ? <p className="switch">New student? <a href="#/register">Create an account</a></p>
          : <p className="switch">{current.label} accounts are created by the placement cell.</p>}
      </form>
    </AuthShell>
  );
}

const SKILLS = ['Coding', 'Tech', 'HR'];

export function RegisterPage() {
  const { register } = useAuth();
  const [f, setF] = useState({ name: '', email: '', password: '', regNo: '', branch: '', skills: [] });
  const [errs, setErrs] = useState({});
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggle = (s) => setF({ ...f, skills: f.skills.includes(s) ? f.skills.filter((x) => x !== s) : [...f.skills, s] });

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    const v = {};
    if (!f.name.trim()) v.name = 'Name is required';
    if (!/^\S+@\S+\.\S+$/.test(f.email)) v.email = 'Enter a valid email';
    if (f.password.length < 8) v.password = 'At least 8 characters';
    if (!f.regNo.trim()) v.regNo = 'Registration number is required';
    if (!f.branch.trim()) v.branch = 'Branch is required';
    if (!f.skills.length) v.skills = 'Pick at least one skill';
    setErrs(v);
    if (Object.keys(v).length) return;
    setBusy(true);
    try { const u = await register(f); navigate(home(u.role)); }
    catch (x) { setErrs({ form: (x && x.message) || 'Could not create the account' }); }
    finally { setBusy(false); }
  };
  const field = (k, label, type = 'text', extra = {}) => (
    <label>{label}
      <input type={type} value={f[k]} onChange={set(k)} aria-invalid={!!errs[k]} {...extra} />
      {errs[k] && <span className="err">{errs[k]}</span>}
    </label>
  );
  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit} noValidate>
        <h1>Create account</h1>
        <p className="sub">Student sign-up. It takes a minute.</p>
        {field('name', 'Full name', 'text', { autoComplete: 'name' })}
        {field('email', 'Email address', 'email', { autoComplete: 'email' })}
        {field('password', 'Password', 'password', { autoComplete: 'new-password' })}
        <div className="two">
          {field('regNo', 'Registration no.')}
          {field('branch', 'Branch')}
        </div>
        <fieldset><legend>Skills</legend>
          {SKILLS.map((s) => (
            <label key={s} className="inline"><input type="checkbox" checked={f.skills.includes(s)} onChange={() => toggle(s)} />{s}</label>
          ))}
          {errs.skills && <span className="err">{errs.skills}</span>}
        </fieldset>
        {errs.form && <p className="err" role="alert">{errs.form}</p>}
        <button className="primary" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
        <p className="switch">Already have an account? <a href="#/login">Sign in</a></p>
      </form>
    </AuthShell>
  );
}