import { useState } from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import { navigate, home } from '../router.js';

// Decorative timetable: highlighted cells hint at booked slots
const ART = Array.from({ length: 24 }, (_, i) => (i === 2 || i === 9 || i === 20 ? 'hi' : i === 14 ? 'ac' : ''));

function AuthShell({ children }) {
  return (
    <div className="auth-shell">
      <aside className="auth-art">
        <span className="brand"><span className="mark" aria-hidden="true" />Aetherion</span>
        <div className="art-grid" aria-hidden="true">{ART.map((c, i) => <span key={i} className={c} />)}</div>
        <div className="auth-copy">
          <h2>Interviews, scheduled without the chaos.</h2>
          <p>Rank your preferred slots and let the scheduler find the best conflict-free plan for everyone.</p>
        </div>
      </aside>
      <main className="auth-panel">{children}</main>
    </div>
  );
}

export function LoginPage() {
  const { login } = useAuth();
  const [f, setF] = useState({ email: '', password: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try { const u = await login(f.email, f.password); navigate(home(u.role)); }
    catch (x) { setErr((x && x.message) || 'Could not sign in'); }
    finally { setBusy(false); }
  };
  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit}>
        <h1>Sign in</h1>
        <p className="sub">Welcome back! Enter your details below.</p>
        <label>Email address
          <input type="email" required autoComplete="email" placeholder="you@college.edu" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </label>
        <label>Password
          <input type="password" required autoComplete="current-password" placeholder="Password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </label>
        {err && <p className="err" role="alert">{err}</p>}
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="switch">New student? <a href="#/register">Create an account</a></p>
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
