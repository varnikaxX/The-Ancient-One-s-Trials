import { useEffect, useState } from 'react';

export const navigate = (p) => { location.hash = '#' + p; };
export const home = (role) => '/' + role.toLowerCase() + '/dashboard';

export function useHash() {
  const read = () => location.hash.slice(1) || '/login';
  const [h, setH] = useState(read);
  useEffect(() => {
    const f = () => setH(read());
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  return h;
}

// Role guard: returns the path the user is actually allowed to see.
export function guard(path, user) {
  const seg = path.split('/')[1];
  if (seg === 'login' || seg === 'register') return user ? home(user.role) : path;
  if (!user) return '/login';
  if (seg !== user.role.toLowerCase()) return home(user.role);
  return path;
}