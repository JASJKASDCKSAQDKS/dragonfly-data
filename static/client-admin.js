(function () {
  'use strict';

  const developerLink = document.getElementById('developer-console-link');
  if (developerLink && window.SelineAuth && window.SelineAuth.getUser()?.role === 'developer') {
    developerLink.style.display = '';
  }

  const overlay = document.getElementById('clients-overlay');
  const list = document.getElementById('clients-list');
  if (!overlay || !list) return;

  function escapeHtml(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function open() {
    overlay.classList.remove('hidden');
    load();
  }

  function close() {
    overlay.classList.add('hidden');
  }

  async function load() {
    list.innerHTML = '<div class="panel-empty">Loading…</div>';
    try {
      const response = await fetch('/api/clients');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.message || 'Could not load client logins.');
      const clients = data.clients || [];
      list.innerHTML = clients.length ? clients.map(render).join('') :
        '<div class="panel-empty">No client login has been generated yet. Create a database with the assistant, then open this panel.</div>';
      list.querySelectorAll('[data-regenerate]').forEach((button) => {
        button.addEventListener('click', () => regenerate(button.dataset.regenerate));
      });
    } catch (error) {
      list.innerHTML = `<div class="panel-empty">${escapeHtml(error.message)}</div>`;
    }
  }

  function render(client) {
    return `<article class="client-card">
      <div class="client-card-head">
        <div><div class="client-card-name">${escapeHtml(client.display_name || client.db_name)}</div>
        <div class="client-card-db">${escapeHtml(client.db_name)}</div></div>
        <span class="client-card-status">${escapeHtml(client.status)}</span>
      </div>
      <div class="client-credentials">
        <div><span>Email</span>${escapeHtml(client.email)}</div>
        <div><span>Username</span>${escapeHtml(client.username)}</div>
        <div><span>Password</span>${escapeHtml(client.password)}</div>
      </div>
      <div class="client-actions">
        <button class="client-action" data-regenerate="${escapeHtml(client.db_name)}">Generate new password</button>
      </div>
    </article>`;
  }

  async function regenerate(dbName) {
    if (!window.confirm(`Generate a new password for ${dbName}?`)) return;
    const response = await fetch(`/api/clients/${encodeURIComponent(dbName)}/regenerate`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) {
      window.alert(data.detail || data.message || 'Password regeneration failed.');
      return;
    }
    await load();
  }

  document.getElementById('clients-btn').addEventListener('click', open);
  document.getElementById('clients-close').addEventListener('click', close);
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
})();
