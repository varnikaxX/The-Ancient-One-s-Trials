import { useEffect } from 'react';

export default function Toast({ msg, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4500);
    return () => clearTimeout(t);
  }, [msg]);
  return (
    <div className="toast" role="alert">
      {msg}
      <button aria-label="Dismiss notification" onClick={onClose}>×</button>
    </div>
  );
}