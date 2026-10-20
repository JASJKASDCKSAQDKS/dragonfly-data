(function () {
  'use strict';
  const auth = window.SelineAuth;
  const demoMode = new URLSearchParams(window.location.search).get('demo') === '1';
  if (!demoMode && (!auth || !auth.isAuthenticated() || !auth.getUser() || auth.getUser().role !== 'developer')) {
    window.location.replace('/login');
    return;
  }
  const $ = (id) => document.getElementById(id);
  let demoTenants = [{ id: 1, name: 'demo_cafe', display_name: 'The Lantern Cafe (Fictional)', db_name: 'demo_cafe', status: 'active' }];
  let demoClients = [{ db_name: 'demo_cafe', display_name: 'The Lantern Cafe (Fictional)', email: 'demo@seline.example', username: 'demo_cafe_owner', status: 'active' }];
  if (demoMode) $('preview-chart').innerHTML = Array.from({length: 30}, (_, i) => `<i style="height:${25 + ((i * 17) % 70)}%"></i>`).join('');
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function error(message) { $('console-error').textContent = message; $('console-error').classList.remove('hidden'); }
  async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || 'Request failed');
    return data;
  }
  function actionButton(label, action, value) { return `<button class="developer-button secondary" data-action="${action}" data-value="${esc(value)}">${label}</button>`; }
  async function loadTenants() {
    if (demoMode) {
      $('tenant-list').innerHTML = demoTenants.map((t) => `<article class="console-card"><div class="card-row"><div><div class="card-title">${esc(t.display_name)}</div><div class="card-meta">${esc(t.name)} · ${esc(t.db_name)}</div></div><span class="status">${esc(t.status)}</span></div><div class="card-actions">${actionButton(t.status === 'active' ? 'Suspend' : 'Reactivate', 'demo-tenant', t.id)} ${actionButton('Migrate','demo-migrate',t.id)}</div></article>`).join('');
      return;
    }
    const data = await api('/api/tenants');
    $('tenant-list').innerHTML = data.length ? data.map((t) => `<article class="console-card"><div class="card-row"><div><div class="card-title">${esc(t.display_name)}</div><div class="card-meta">${esc(t.name)} · ${esc(t.db_name)}</div></div><span class="status ${t.status === 'suspended' ? 'suspended' : ''}">${esc(t.status)}</span></div><div class="card-actions">${t.status === 'active' ? actionButton('Suspend','suspend-tenant',t.id) : actionButton('Reactivate','reactivate-tenant',t.id)} ${actionButton('Migrate','migrate-tenant',t.id)}</div></article>`).join('') : '<div class="empty">No managed tenants yet.</div>';
  }
  async function loadClients() {
    if (demoMode) {
      $('client-list').innerHTML = demoClients.map((c) => `<article class="console-card"><div class="card-row"><div><div class="card-title">${esc(c.display_name)}</div><div class="card-meta">${esc(c.db_name)} · ${esc(c.email)}</div></div><span class="status">${esc(c.status)}</span></div><div class="redacted">Username: ${esc(c.username)} · Password: redacted</div><div class="card-actions">${actionButton(c.status === 'active' ? 'Suspend' : 'Reactivate','demo-client',c.db_name)} ${actionButton('Regenerate password','demo-regenerate',c.db_name)}</div></article>`).join('');
      return;
    }
    const data = await api('/api/clients');
    $('client-list').innerHTML = (data.clients || []).length ? data.clients.map((c) => `<article class="console-card"><div class="card-row"><div><div class="card-title">${esc(c.display_name || c.db_name)}</div><div class="card-meta">${esc(c.db_name)} · ${esc(c.email)}</div></div><span class="status ${c.status === 'suspended' ? 'suspended' : ''}">${esc(c.status)}</span></div><div class="redacted">Username: ${esc(c.username)} · Password: redacted</div><div class="card-actions">${c.status === 'active' ? actionButton('Suspend','suspend-client',c.db_name) : actionButton('Reactivate','reactivate-client',c.db_name)} ${actionButton('Regenerate password','regenerate-client',c.db_name)}</div></article>`).join('') : '<div class="empty">No client accounts yet.</div>';
  }
  async function loadAudit() { if (demoMode) { $('audit-list').textContent = '[DEMO] TENANT CREATED · demo_cafe\n[DEMO] CLIENT ACCOUNT ACTIVE · demo@seline.example\n[DEMO] FICTIONAL DATA LOADED'; return; } const data = await api(`/api/audit?limit=${$('audit-limit').value}`); $('audit-list').textContent = (data.logs || []).join('\n'); }
  async function loadHealth() {
    const checks = demoMode ? [{ status: 'fulfilled' }, { status: 'fulfilled' }, { status: 'fulfilled' }] : await Promise.allSettled([api('/api/health/live'), api('/api/health/ready'), api('/api/status')]);
    const names = ['Liveness','Readiness','Application'];
    $('health-list').innerHTML = checks.map((r, i) => `<div class="health-row"><span>${names[i]}</span><strong class="${r.status === 'fulfilled' ? 'health-ok' : 'health-fail'}">${r.status === 'fulfilled' ? 'Operational' : 'Unavailable'}</strong></div>`).join('');
    const healthy = checks.every((r) => r.status === 'fulfilled'); $('health-summary').textContent = healthy ? '● All systems operational' : '● Degraded'; $('health-summary').classList.toggle('ok', healthy);
  }
  async function loadAll() { $('console-error').classList.add('hidden'); try { await Promise.all([loadTenants(), loadClients(), loadAudit(), loadHealth()]); } catch (e) { error(e.message); } }
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action]'); if (!button) return;
    const action = button.dataset.action; const value = encodeURIComponent(button.dataset.value);
    try {
      if (demoMode && action === 'demo-tenant') { const item = demoTenants.find((t) => String(t.id) === button.dataset.value); item.status = item.status === 'active' ? 'suspended' : 'active'; return loadAll(); }
      if (demoMode && action === 'demo-client') { const item = demoClients.find((c) => c.db_name === button.dataset.value); item.status = item.status === 'active' ? 'suspended' : 'active'; return loadAll(); }
      if (demoMode && action === 'demo-regenerate') { window.alert('Fictional demo password rotated: DemoOnly-4821'); return; }
      if (demoMode && action === 'demo-migrate') { window.alert('Fictional demo migration completed.'); return; }
      if (action === 'regenerate-client') { const data = await api(`/api/clients/${value}/regenerate`, {method:'POST'}); window.alert(`New one-time password for ${data.client.db_name}: ${data.client.password}`); }
      else if (action.endsWith('tenant')) await api(`/api/tenants/${value}/${action.split('-')[0]}`, {method:'POST'});
      else if (action.endsWith('client')) await api(`/api/clients/${value}/${action.split('-')[0]}`, {method:'POST'});
      await loadAll();
    } catch (e) { error(e.message); }
  });
  $('show-tenant-form').addEventListener('click', () => $('tenant-form').classList.toggle('hidden'));
  $('tenant-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const body = Object.fromEntries(new FormData(event.target)); body.business_day_start_hour = Number(body.business_day_start_hour); await api('/api/tenants', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); event.target.reset(); $('tenant-form').classList.add('hidden'); await loadAll(); } catch (e) { error(e.message); } });
  $('refresh-console').addEventListener('click', loadAll); $('audit-limit').addEventListener('change', loadAudit);
  loadAll();
})();
