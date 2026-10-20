/* ==========================================================================
   Seline — Databases admin panel
   Browse / search / add / edit / delete rows in any registered database,
   plus a per-database activity feed. Talks to /api/dbadmin/*.
   ========================================================================== */

const dbState = {
  dbs: [],
  currentDb: null,
  tables: [],
  currentTable: null,   // or '__activity'
  schema: [],
  total: 0,
  offset: 0,
  limit: 50,
  search: '',
};

function dbEsc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function openDbPanel() {
  document.getElementById('db-overlay').classList.remove('hidden');
  loadDatabases();
  clearInterval(dbState._poll);
  dbState._poll = setInterval(refreshDbTabsQuiet, 5000);
}

function closeDbPanel() {
  document.getElementById('db-overlay').classList.add('hidden');
  clearInterval(dbState._poll);
  closeRowModal();
}

function renderDbTabs() {
  const rail = document.getElementById('db-tabs');
  rail.innerHTML = '';

  const tmpl = document.createElement('div');
  tmpl.className = 'db-tab' + (dbState.currentDb === '__template__' ? ' active' : '');
  tmpl.dataset.db = '__template__';
  tmpl.innerHTML =
    `<span class="db-tab-name">⭐ standard template</span>` +
    `<span class="db-tab-desc">what every NEW database starts with</span>`;
  tmpl.addEventListener('click', () => selectDb('__template__'));
  rail.appendChild(tmpl);

  for (const db of dbState.dbs) {
    const tab = document.createElement('div');
    tab.className = 'db-tab' + (db.name === dbState.currentDb ? ' active' : '');
    tab.dataset.db = db.name;
    tab.innerHTML =
      `<span class="db-tab-name">${dbEsc(db.display_name || db.name)}</span>` +
      `<span class="db-tab-desc">${dbEsc(db.description || '')}</span>` +
      `<span class="db-tab-meta">${db.reachable ? db.tables + ' tables' : 'unreachable'}</span>`;
    tab.addEventListener('click', () => selectDb(db.name));
    if (db.source === 'ai-created') {
      const del = document.createElement('span');
      del.className = 'db-tab-del';
      del.textContent = '🗑';
      del.title = `Delete database ${db.name}`;
      del.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteDatabase(db.name);
      });
      tab.appendChild(del);
    }
    rail.appendChild(tab);
  }
}

async function deleteDatabase(name) {
  const typed = prompt(
    `Delete the database '${name}' and ALL its data forever?\n` +
    `Type the name exactly to confirm:`
  );
  if (typed === null) return;
  if (typed !== name) { alert('Name did not match — deletion cancelled.'); return; }
  try {
    const res = await fetch(`/api/dbadmin/${name}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.status === 'success') {
      if (dbState.currentDb === name) {
        dbState.currentDb = null;
        dbState.currentTable = null;
        document.getElementById('db-tables').innerHTML = '';
        showGridEmpty('Database deleted.');
      }
      loadDatabases();
    } else {
      alert(data.message || 'Delete failed.');
    }
  } catch (e) {
    alert('Delete failed — could not reach the server.');
  }
}

async function refreshDbTabsQuiet() {
  try {
    const res = await fetch('/api/dbadmin/databases');
    const data = await res.json();
    const fresh = data.databases || [];
    if (fresh.map(d => d.name).join(',') !== dbState.dbs.map(d => d.name).join(',')) {
      dbState.dbs = fresh;
      renderDbTabs();
    }
  } catch (e) { /* keep the current list */ }
}

// ---------------------------------------------------------------------------
// Databases (tabs)
// ---------------------------------------------------------------------------
async function loadDatabases() {
  const rail = document.getElementById('db-tabs');
  rail.innerHTML = '<div class="panel-empty" style="margin:8px">Loading…</div>';
  try {
    const res = await fetch('/api/dbadmin/databases');
    const data = await res.json();
    dbState.dbs = data.databases || [];
    renderDbTabs();
    if (!dbState.currentDb && dbState.dbs.length) {
      selectDb(dbState.dbs[0].name);
    } else if (dbState.currentDb) {
      selectDb(dbState.currentDb);
    }
  } catch (e) {
    rail.innerHTML = '<div class="panel-empty" style="margin:8px">Could not load databases.</div>';
  }
}

async function selectDb(name) {
  if (name === '__template__') {
    dbState.currentDb = '__template__';
    document.querySelectorAll('.db-tab').forEach(el =>
      el.classList.toggle('active', el.dataset.db === '__template__'));
    document.getElementById('db-tables').innerHTML = '';
    document.getElementById('db-grid-wrap').style.display = 'none';
    document.getElementById('db-activity').style.display = 'none';
    document.getElementById('db-template').style.display = 'block';
    loadTemplate();
    return;
  }

  dbState.currentDb = name;
  dbState.currentTable = null;
  dbState.offset = 0;
  dbState.search = '';
  document.getElementById('db-search').value = '';
  document.getElementById('db-template').style.display = 'none';
  document.getElementById('db-grid-wrap').style.display = 'flex';
  document.querySelectorAll('.db-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.db === name);
  });
  await loadTables();
}

// ---------------------------------------------------------------------------
// Tables (chips)
// ---------------------------------------------------------------------------
async function loadTables() {
  const bar = document.getElementById('db-tables');
  bar.innerHTML = '<span class="panel-empty">Loading…</span>';
  try {
    const res = await fetch(`/api/dbadmin/${dbState.currentDb}/tables`);
    const data = await res.json();
    dbState.tables = data.tables || [];
    renderTableChips();
    if (dbState.tables.length) selectTable(dbState.tables[0].name);
    else showGridEmpty('No tables in this database yet.');
  } catch (e) {
    bar.innerHTML = '<span class="panel-empty">Could not load tables.</span>';
  }
}

function renderTableChips() {
  const bar = document.getElementById('db-tables');
  bar.innerHTML = '';
  for (const t of dbState.tables) {
    const chip = document.createElement('button');
    chip.className = 'db-table-chip' + (t.name === dbState.currentTable ? ' active' : '');
    const viewMark = t.kind === 'view' ? ' 👁' : '';
    chip.innerHTML = `${dbEsc(t.name)}${viewMark}<span class="chip-count">${t.rows}</span>`;
    chip.title = t.kind === 'view' ? 'View (read-only analytics)' : 'Table (editable)';
    chip.addEventListener('click', () => selectTable(t.name));
    bar.appendChild(chip);
  }
  const act = document.createElement('button');
  act.className = 'db-table-chip' + (dbState.currentTable === '__activity' ? ' active' : '');
  act.textContent = '⚡ activity';
  act.addEventListener('click', () => selectTable('__activity'));
  bar.appendChild(act);
}

function currentKind() {
  const t = dbState.tables.find(t => t.name === dbState.currentTable);
  return t ? t.kind : 'table';
}

async function selectTable(name) {
  dbState.currentTable = name;
  dbState.offset = 0;
  renderTableChips();
  const isView = name !== '__activity' && currentKind() === 'view';
  document.getElementById('db-grid-wrap').style.display = name === '__activity' ? 'none' : 'flex';
  document.getElementById('db-activity').style.display = name === '__activity' ? 'block' : 'none';
  document.getElementById('db-add-row').style.display =
    (name === '__activity' || isView) ? 'none' : 'inline-block';
  document.getElementById('db-add-col').style.display =
    (name === '__activity' || isView) ? 'none' : 'inline-block';
  if (name === '__activity') {
    loadActivity();
  } else {
    await loadSchema();
    await loadRows();
  }
}

// ---------------------------------------------------------------------------
// Schema + rows grid
// ---------------------------------------------------------------------------
async function loadSchema() {
  const res = await fetch(`/api/dbadmin/${dbState.currentDb}/${dbState.currentTable}/schema`);
  const data = await res.json();
  dbState.schema = data.columns || [];
}

async function loadRows() {
  const grid = document.getElementById('db-grid');
  grid.innerHTML = '<div class="db-grid-empty">Loading…</div>';
  const params = new URLSearchParams({
    limit: dbState.limit, offset: dbState.offset, search: dbState.search,
  });
  try {
    const res = await fetch(`/api/dbadmin/${dbState.currentDb}/${dbState.currentTable}/rows?${params}`);
    const data = await res.json();
    dbState.total = data.total || 0;
    renderGrid(data.columns || [], data.rows || []);
    renderPager();
  } catch (e) {
    showGridEmpty('Could not load rows.');
  }
}

function pkColumn(columns) {
  const pk = dbState.schema.find(c => c.key === 'PRI');
  return pk ? pk.name : (columns[0] || null);
}

function renderGrid(columns, rows) {
  const grid = document.getElementById('db-grid');
  const pk = pkColumn(columns);
  let html = '<table><thead><tr>';
  for (const c of columns) html += `<th>${dbEsc(c)}</th>`;
  html += '<th></th></tr></thead><tbody>';
  for (const row of rows) {
    html += '<tr>';
    for (const c of columns) {
      const v = row[c];
      html += `<td title="${dbEsc(v)}">${v === null ? '<i style="opacity:.4">NULL</i>' : dbEsc(v)}</td>`;
    }
    if (currentKind() === 'view') {
      html += '<td></td></tr>';
    } else {
      html += `<td class="row-actions">` +
        `<button class="row-btn" data-edit="${dbEsc(row[pk])}">edit</button>` +
        `<button class="row-btn del" data-del="${dbEsc(row[pk])}">delete</button></td></tr>`;
    }
  }
  if (!rows.length) {
    html += `<tr><td colspan="${columns.length + 1}" style="text-align:center; color:var(--text-dim); padding:24px">` +
      `This table is empty — the columns above are real, there just isn't any data yet. ` +
      `Use <b>+ Add row</b> to create the first one.</td></tr>`;
  }
  html += '</tbody></table>';
  grid.innerHTML = html;
  grid.querySelectorAll('[data-edit]').forEach(btn =>
    btn.addEventListener('click', () => openRowModal('edit', rows.find(r => String(r[pk]) === btn.dataset.edit))));
  grid.querySelectorAll('[data-del]').forEach(btn =>
    btn.addEventListener('click', () => deleteRow(btn.dataset.del)));
}

function showGridEmpty(msg) {
  document.getElementById('db-grid').innerHTML = `<div class="db-grid-empty">${dbEsc(msg)}</div>`;
  renderPager();
}

function renderPager() {
  const pager = document.getElementById('db-pager');
  const from = dbState.total === 0 ? 0 : dbState.offset + 1;
  const to = Math.min(dbState.offset + dbState.limit, dbState.total);
  pager.innerHTML = `
    <span>${from}–${to} of ${dbState.total}</span>
    <span>
      <button id="db-prev" ${dbState.offset === 0 ? 'disabled' : ''}>← prev</button>
      <button id="db-next" ${to >= dbState.total ? 'disabled' : ''}>next →</button>
    </span>`;
  document.getElementById('db-prev')?.addEventListener('click', () => {
    dbState.offset = Math.max(0, dbState.offset - dbState.limit); loadRows();
  });
  document.getElementById('db-next')?.addEventListener('click', () => {
    dbState.offset += dbState.limit; loadRows();
  });
}

// ---------------------------------------------------------------------------
// Activity feed
// ---------------------------------------------------------------------------
async function loadActivity() {
  const box = document.getElementById('db-activity');
  box.innerHTML = '<div class="db-grid-empty">Loading…</div>';
  try {
    const res = await fetch(`/api/dbadmin/${dbState.currentDb}/activity`);
    const data = await res.json();
    const items = data.activity || [];
    if (!items.length) { box.innerHTML = '<div class="db-grid-empty">No activity recorded yet.</div>'; return; }
    box.innerHTML = items.map(i => `
      <div class="db-activity-item">
        <span class="act-kind">${dbEsc(i.kind)}</span>${dbEsc(i.text)}
        <span class="act-ts">${dbEsc(i.ts)}</span>
      </div>`).join('');
  } catch (e) {
    box.innerHTML = '<div class="db-grid-empty">Could not load activity.</div>';
  }
}

// ---------------------------------------------------------------------------
// Row modal (add / edit)
// ---------------------------------------------------------------------------
function enumOptions(type) {
  const m = /^enum\((.+)\)$/i.exec(type || '');
  if (!m) return null;
  return [...m[1].matchAll(/'((?:[^'\\]|\\.)*)'/g)].map(x => x[1]);
}

function isRequired(col) {
  const extra = (col.extra || '').toLowerCase();
  return !col.nullable && (col.default === null || col.default === undefined)
    && !extra.includes('auto_increment') && !extra.includes('generated');
}

function openRowModal(mode, row) {
  const modal = document.getElementById('db-row-modal');
  const form = document.getElementById('db-form');
  document.getElementById('db-modal-title').textContent =
    mode === 'add' ? `Add row → ${dbState.currentTable}` : `Edit row in ${dbState.currentTable}`;
  document.getElementById('db-form-error').textContent = '';
  form.innerHTML = '';
  form.dataset.mode = mode;

  for (const col of dbState.schema) {
    const extra = (col.extra || '').toLowerCase();
    if (extra.includes('auto_increment') || extra.includes('generated')) continue;
    if (mode === 'add' && col.name === 'created_at') continue;

    const wrap = document.createElement('div');
    wrap.className = 'form-field';
    const val = mode === 'edit' ? (row[col.name] ?? '') : '';
    const isSecret = col.secret;
    const long = /text/i.test(col.type);
    const opts = enumOptions(col.type);
    const req = isRequired(col);
    const reqMark = req ? ' <b style="color:var(--danger)">*</b>' : '';

    let input;
    if (opts) {
      input = `<select data-col="${dbEsc(col.name)}" ${req ? 'data-req="1"' : ''}>` +
        (req ? '' : '<option value="">—</option>') +
        opts.map(o => `<option value="${dbEsc(o)}" ${String(val) === o ? 'selected' : ''}>${dbEsc(o)}</option>`).join('') +
        '</select>';
    } else if (long) {
      input = `<textarea data-col="${dbEsc(col.name)}" rows="3" ${req ? 'data-req="1"' : ''}>${dbEsc(val)}</textarea>`;
    } else {
      input = `<input data-col="${dbEsc(col.name)}" value="${dbEsc(isSecret && mode === 'edit' ? '' : val)}" ${req ? 'data-req="1"' : ''} ` +
        (isSecret ? 'type="password" placeholder="' + (mode === 'edit' ? 'leave empty to keep unchanged' : '') + '"' : '') + '>';
    }

    wrap.innerHTML =
      `<label>${dbEsc(col.name)}${reqMark} <span style="opacity:.55">${dbEsc(col.type)}</span></label>` +
      input +
      (isSecret ? '<span class="field-note">stored hashed (SHA-256) — never shown</span>' : '');
    form.appendChild(wrap);
  }
  modal.classList.remove('hidden');
}

function closeRowModal() {
  const form = document.getElementById('db-form');
  delete form.dataset.target;
  delete form.dataset.tmplTable;
  document.getElementById('db-row-modal').classList.add('hidden');
}

async function submitRow() {
  const form = document.getElementById('db-form');
  const errBox = document.getElementById('db-form-error');
  const mode = form.dataset.mode;
  const body = {};
  const missing = [];
  form.querySelectorAll('[data-col]').forEach(el => {
    if (el.value !== '') body[el.dataset.col] = el.value;
    else if (el.dataset.req === '1') missing.push(el.dataset.col);
  });

  if (missing.length) {
    errBox.textContent = `Required field(s) empty: ${missing.join(', ')}`;
    return;
  }

  const db = dbState.currentDb, table = dbState.currentTable;
  try {
    let res;
    if (form.dataset.target === 'template') {
      res = await fetch('/api/dbadmin/template/rows', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table: form.dataset.tmplTable, values: body }),
      });
    } else if (mode === 'add') {
      res = await fetch(`/api/dbadmin/${db}/${table}/rows`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
    } else {
      res = await fetch(`/api/dbadmin/${db}/${table}/rows/${encodeURIComponent(form.dataset.pk)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
    }
    const data = await res.json();
    if (data.status === 'success') {
      const wasTemplate = form.dataset.target === 'template';
      closeRowModal();
      if (wasTemplate) loadTemplate();
      else { loadRows(); loadTablesQuiet(); }
    } else {
      errBox.textContent = data.message || 'Save failed.';
    }
  } catch (e) {
    errBox.textContent = 'Save failed — could not reach the server.';
  }
}

async function deleteRow(pk) {
  if (!confirm(`Delete row ${pk} from ${dbState.currentTable}? This cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/dbadmin/${dbState.currentDb}/${dbState.currentTable}/rows/${encodeURIComponent(pk)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.status !== 'success') alert(data.message || 'Delete failed.');
    loadRows();
    loadTablesQuiet();
  } catch (e) {
    alert('Delete failed.');
  }
}

async function loadTablesQuiet() {
  try {
    const res = await fetch(`/api/dbadmin/${dbState.currentDb}/tables`);
    const data = await res.json();
    dbState.tables = data.tables || [];
    renderTableChips();
  } catch (e) { /* ignore */ }
}

// Patch openRowModal to remember the pk for edits
const _openRowModal = openRowModal;
openRowModal = function (mode, row) {
  _openRowModal(mode, row);
  if (mode === 'edit') {
    const pk = pkColumn([]);
    document.getElementById('db-form').dataset.pk = row[pk];
  }
};

// ---------------------------------------------------------------------------
// Standard template view — add columns / seed rows for FUTURE databases
// ---------------------------------------------------------------------------
async function loadTemplate() {
  const box = document.getElementById('db-template');
  box.innerHTML = '<div class="db-grid-empty">Loading…</div>';
  try {
    const res = await fetch('/api/dbadmin/template/structure');
    const data = await res.json();
    renderTemplate(data.tables || []);
  } catch (e) {
    box.innerHTML = '<div class="db-grid-empty">Could not load the template.</div>';
  }
}

function renderTemplate(tables) {
  const box = document.getElementById('db-template');
  if (!tables.length) {
    box.innerHTML = '<div class="db-grid-empty">Template file is empty or missing.</div>';
    return;
  }
  box.innerHTML =
    `<div class="tmpl-note">Changes here affect every database created <b>after</b> you make them — existing databases stay as they are.</div>` +
    tables.map((t, i) => `
    <div class="tmpl-table">
      <div class="tmpl-head">
        <span class="tmpl-name">${dbEsc(t.name)}</span>
        <span class="tmpl-meta">${t.columns.length} columns · ${t.seed_rows} seed row(s)</span>
        <span class="tmpl-actions">
          <button class="db-add-row" data-tmpl-col="${i}">+ column</button>
          <button class="db-add-row" data-tmpl-row="${i}">+ seed row</button>
        </span>
      </div>
      <div class="tmpl-cols">${t.columns.map(c =>
        `<span class="tmpl-col">${dbEsc(c.name)} <i>${dbEsc(c.type)}</i></span>`).join('')}</div>
    </div>`).join('');

  box.querySelectorAll('[data-tmpl-col]').forEach(btn =>
    btn.addEventListener('click', () => {
      dbState.colTarget = { scope: 'template', table: tables[btn.dataset.tmplCol].name };
      openColModal();
    }));
  box.querySelectorAll('[data-tmpl-row]').forEach(btn =>
    btn.addEventListener('click', () => openTemplateRowModal(tables[btn.dataset.tmplRow])));
}

function openTemplateRowModal(t) {
  dbState.schema = t.columns.map(c => ({
    name: c.name,
    type: c.type.split(' ')[0],
    nullable: true,
    key: '',
    default: null,
    extra: '',
    secret: /pass/i.test(c.name),
  }));
  openRowModal('add');
  document.getElementById('db-modal-title').textContent = `Add seed row → template.${t.name}`;
  const form = document.getElementById('db-form');
  form.dataset.target = 'template';
  form.dataset.tmplTable = t.name;
}

// ---------------------------------------------------------------------------
// Add-column modal
// ---------------------------------------------------------------------------
function openColModal() {
  document.getElementById('db-col-name').value = '';
  document.getElementById('db-col-error').textContent = '';
  document.getElementById('db-col-modal').classList.remove('hidden');
  document.getElementById('db-col-name').focus();
}

function closeColModal() {
  document.getElementById('db-col-modal').classList.add('hidden');
}

async function submitColumn() {
  const name = document.getElementById('db-col-name').value.trim();
  const type = document.getElementById('db-col-type').value;
  const errBox = document.getElementById('db-col-error');
  if (!name) { errBox.textContent = 'Column name is required.'; return; }

  const target = dbState.colTarget;
  const url = target && target.scope === 'template'
    ? '/api/dbadmin/template/columns'
    : `/api/dbadmin/${dbState.currentDb}/${dbState.currentTable}/columns`;
  const payload = target && target.scope === 'template'
    ? { table: target.table, name, type }
    : { name, type };

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.status === 'success') {
      closeColModal();
      if (target && target.scope === 'template') {
        dbState.colTarget = null;
        loadTemplate();
      } else {
        await loadSchema();
        await loadRows();
      }
    } else {
      errBox.textContent = data.message || 'Could not add column.';
    }
  } catch (e) {
    errBox.textContent = 'Could not reach the server.';
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('dbadmin-btn').addEventListener('click', openDbPanel);
  document.getElementById('db-close').addEventListener('click', closeDbPanel);
  document.getElementById('db-add-row').addEventListener('click', () => openRowModal('add'));
  document.getElementById('db-add-col').addEventListener('click', () => {
    dbState.colTarget = null;
    openColModal();
  });
  document.getElementById('db-col-cancel').addEventListener('click', closeColModal);
  document.getElementById('db-col-save').addEventListener('click', submitColumn);
  document.getElementById('db-modal-cancel').addEventListener('click', closeRowModal);
  document.getElementById('db-modal-save').addEventListener('click', submitRow);

  let searchTimer = null;
  document.getElementById('db-search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      dbState.search = e.target.value.trim();
      dbState.offset = 0;
      loadRows();
    }, 350);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !document.getElementById('db-overlay').classList.contains('hidden')) {
      closeDbPanel();
    }
  });
});
