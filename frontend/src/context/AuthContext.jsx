import { createContext, useContext, useEffect, useState } from 'react';
import { api, setToken, setOnUnauthorized } from '../api/client.js';
import { navigate } from '../router.js';

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    const s = JSON.parse(sessionStorage.getItem('auth') || 'null');
    if (s) setToken(s.token);
    return s;
  });

  const save = (data) => {
    setToken(data.token);
    sessionStorage.setItem('auth', JSON.stringify(data));
    setAuth(data);
    return data.user;
  };
  const logout = () => {
    setToken(null);
    sessionStorage.removeItem('auth');
    setAuth(null);
    navigate('/login');
  };
  useEffect(() => { setOnUnauthorized(logout); }, []);

  const login = async (email, password) => save(await api('POST', '/auth/login', { email, password }));
  const register = async (form) => save(await api('POST', '/auth/register', form));

  return <Ctx.Provider value={{ auth, user: auth && auth.user, login, register, logout }}>{children}</Ctx.Provider>;
}