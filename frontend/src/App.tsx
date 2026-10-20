import { FormEvent, useEffect, useMemo, useState } from 'react';

type Language = 'en' | 'ro';
type Json = Record<string, any>;
const SNAPSHOT_KEY = 'seline-client-phase2';

const copy = {
  en: { signIn: 'Sign in', email: 'Email address', password: 'Password', welcome: 'Welcome back', loginHint: 'Sign in to view your business performance.', invalid: 'Enter your email and password.', loginFailed: 'Unable to sign in. Check your details and try again.', dashboard: 'Client dashboard', overview: 'A clear view of your business performance.', revenue: 'Revenue', profit: 'Profit', trend: 'Revenue trend', top: 'Top products', stock: 'Stock alerts', insight: 'Daily insight', refresh: 'Refresh data', signOut: 'Sign out', loading: 'Loading your dashboard…', offline: 'Showing the latest saved snapshot. Reconnect to refresh.', noData: 'No data available yet.', error: 'We could not load your dashboard.', retry: 'Try again', language: 'Language' },
  ro: { signIn: 'Autentificare', email: 'Adresă de email', password: 'Parolă', welcome: 'Bine ai revenit', loginHint: 'Autentifică-te pentru a vedea performanța afacerii.', invalid: 'Introdu emailul și parola.', loginFailed: 'Autentificarea a eșuat. Verifică datele și încearcă din nou.', dashboard: 'Panou client', overview: 'O privire clară asupra performanței afacerii.', revenue: 'Venituri', profit: 'Profit', trend: 'Evoluția veniturilor', top: 'Produse de top', stock: 'Alerte stoc', insight: 'Recomandarea zilei', refresh: 'Actualizează datele', signOut: 'Deconectare', loading: 'Se încarcă panoul…', offline: 'Se afișează ultima copie salvată. Reconectează-te pentru actualizare.', noData: 'Nu există date încă.', error: 'Panoul nu a putut fi încărcat.', retry: 'Încearcă din nou', language: 'Limbă' },
};

function value(data: Json | undefined, key: string): number {
  const current = data?.[key]?.current ?? data?.[key];
  return Number(current?.value ?? current?.amount ?? current ?? 0);
}
function money(n: number) { return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n); }

function LanguageToggle({ lang, setLang }: { lang: Language; setLang: (l: Language) => void }) {
  return <div className="language" role="group" aria-label={copy[lang].language}>
    <button className={lang === 'en' ? 'active' : ''} onClick={() => setLang('en')}>EN</button>
    <button className={lang === 'ro' ? 'active' : ''} onClick={() => setLang('ro')}>RO</button>
  </div>;
}

function Login({ lang, setLang, onSuccess }: { lang: Language; setLang: (l: Language) => void; onSuccess: () => void }) {
  const t = copy[lang]; const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState(''); const [requiresMfa, setRequiresMfa] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) {
    e.preventDefault(); setError('');
    if (!email.trim() || !password) { setError(t.invalid); return; }
    setBusy(true);
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email.trim(), password, ...(mfaCode ? { mfa_code: mfaCode } : {}) }) });
      const data = await response.json().catch(() => ({}));
      if (data.requires_mfa) { setRequiresMfa(true); setError('Enter the six-digit authenticator code.'); return; }
      if (!response.ok) throw new Error(data.detail || t.loginFailed);
      onSuccess();
    } catch { setError(t.loginFailed); } finally { setBusy(false); }
  }
  return <main className="login-shell"><section className="login-card">
    <header className="brand"><span className="brand-mark">S</span><span>Seline</span><LanguageToggle lang={lang} setLang={setLang} /></header>
    <div className="login-heading"><p className="eyebrow">CLIENT PORTAL</p><h1>{t.welcome}</h1><p>{t.loginHint}</p></div>
    <form onSubmit={submit} noValidate><label>{t.email}<input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>{t.password}<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
      {requiresMfa && <label>Authenticator code<input inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" value={mfaCode} onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))} /></label>}
      {error && <div className="notice error" role="alert">{error}</div>}<button className="primary full" disabled={busy}>{busy ? '…' : t.signIn}</button>
    </form>
  </section></main>;
}

function Dashboard({ lang, setLang, onLogout }: { lang: Language; setLang: (l: Language) => void; onLogout: () => void }) {
  const t = copy[lang]; const [data, setData] = useState<Json | null>(null); const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false); const [offline, setOffline] = useState(false);
  const fetchData = async () => {
    setLoading(true); setError(false);
    try {
      const response = await fetch('/api/analytics/phase2', { credentials: 'include' });
      if (!response.ok) throw new Error();
      const next = await response.json(); localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(next)); setData(next); setOffline(false);
    } catch {
      const saved = localStorage.getItem(SNAPSHOT_KEY);
      if (saved) { setData(JSON.parse(saved)); setOffline(true); } else { setError(true); }
    } finally { setLoading(false); }
  };
  useEffect(() => { fetchData(); }, []);
  const chart = useMemo(() => (data?.revenue_chart?.data || data?.revenue_chart || []).slice(-14), [data]);
  const max = Math.max(...chart.map((p: Json) => Number(p.revenue ?? p.value ?? p.amount ?? 0)), 1);
  return <main className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark">S</span><span>Seline</span></div><div className="top-actions"><LanguageToggle lang={lang} setLang={setLang} /><button className="quiet" onClick={onLogout}>{t.signOut}</button></div></header>
    <div className="dashboard"><div className="welcome-row"><div><p className="eyebrow">OVERVIEW</p><h1>{t.dashboard}</h1><p className="subtle">{t.overview}</p></div><button className="primary" onClick={fetchData} disabled={loading}>{t.refresh}</button></div>
      {offline && <div className="notice offline" role="status">{t.offline}</div>}{error && <div className="notice error" role="alert">{t.error} <button onClick={fetchData}>{t.retry}</button></div>}
      {loading ? <div className="loading-card" aria-live="polite"><span className="spinner" />{t.loading}</div> : data && <><section className="kpis">
        <article><span>{t.revenue}</span><strong>{money(value(data, 'revenue'))}</strong></article><article><span>{t.profit}</span><strong>{money(value(data, 'profit'))}</strong></article><article><span>{t.insight}</span><strong className="insight">{data.insight || t.noData}</strong></article>
      </section><section className="grid"><article className="panel"><div className="panel-title"><div><p className="eyebrow">PERFORMANCE</p><h2>{t.trend}</h2></div></div><div className="chart" aria-label={t.trend}>{chart.length ? chart.map((p: Json, i: number) => <div className="bar-wrap" key={i}><div className="bar" style={{ height: `${Math.max(8, Number(p.revenue ?? p.value ?? p.amount ?? 0) / max * 100)}%` }} title={money(Number(p.revenue ?? p.value ?? p.amount ?? 0))} /><small>{String(p.date ?? p.day ?? '').slice(5)}</small></div>) : <p className="subtle">{t.noData}</p>}</div></article>
        <article className="panel"><p className="eyebrow">PRODUCTS</p><h2>{t.top}</h2><ul className="data-list">{(data.top_products || []).map((p: Json, i: number) => <li key={i}><span>{p.name || p.product_name || t.noData}</span><strong>{money(Number(p.revenue ?? p.amount ?? 0))}</strong></li>)}</ul></article>
        <article className="panel"><p className="eyebrow">INVENTORY</p><h2>{t.stock}</h2><ul className="data-list">{(data.stock_alerts || []).map((p: Json, i: number) => <li key={i}><span>{p.name || p.product_name || t.noData}</span><strong className="warning">{p.stock ?? p.quantity ?? '—'}</strong></li>)}</ul></article>
      </section></>}
    </div></main>;
}

export default function App() {
  const [lang, setLang] = useState<Language>(() => (localStorage.getItem('seline-language') as Language) || 'en');
  const [authenticated, setAuthenticated] = useState(() => sessionStorage.getItem('seline-client-auth') === '1');
  const changeLanguage = (next: Language) => { setLang(next); localStorage.setItem('seline-language', next); };
  const logout = async () => { await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => undefined); sessionStorage.removeItem('seline-client-auth'); setAuthenticated(false); };
  return authenticated ? <Dashboard lang={lang} setLang={changeLanguage} onLogout={logout} /> : <Login lang={lang} setLang={changeLanguage} onSuccess={() => { sessionStorage.setItem('seline-client-auth', '1'); setAuthenticated(true); }} />;
}
