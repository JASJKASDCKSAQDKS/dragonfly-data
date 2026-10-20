(function () {
  'use strict';

  const SNAPSHOT_KEY = 'seline_dashboard_snapshot';

  function cacheSnapshot(payload) {
    try {
      sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify({
        savedAt: new Date().toISOString(),
        payload,
      }));
    } catch (err) {
      console.warn('Could not cache dashboard snapshot', err);
    }
  }

  function readCachedSnapshot() {
    try {
      const raw = sessionStorage.getItem(SNAPSHOT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }
  const $ = (id) => document.getElementById(id);
  const demoMode = new URLSearchParams(window.location.search).get('demo') === '1';
  const demoPayload = {
    revenue: { current: { revenue: 18462, transaction_count: 1284 }, change_pct: 12.4 },
    profit: { current: { gross_profit: 10731, margin_pct: 58.1 }, change_pct: 9.8 },
    revenue_chart: Array.from({ length: 90 }, (_, i) => ({ period: new Date(Date.now() - (89 - i) * 86400000).toISOString().slice(0, 10), revenue: Math.round(380 + (i % 7) * 48 + ((i * 137) % 530) + (i % 14 === 6 ? 280 : 0)) })),
    busy_hours: Array.from({ length: 42 }, (_, i) => ({ weekday: i % 7, hour_of_day: 12 + (i % 12), revenue: 40 + ((i * 19) % 180) })),
    stock_alerts: [{ name: 'House lager', days_of_stock_left: 1.8, suggested_reorder_qty: 48 }, { name: 'Limes', days_of_stock_left: 0.9, suggested_reorder_qty: 30 }, { name: 'Ginger beer', days_of_stock_left: 2.4, suggested_reorder_qty: 24 }],
    top_products: [{ name: 'Espresso martini', units_sold: 182, total_revenue: 2184, margin_pct: 71.2 }, { name: 'House lager', units_sold: 242, total_revenue: 1936, margin_pct: 54.6 }, { name: 'Chicken wings', units_sold: 96, total_revenue: 1482, margin_pct: 48.3 }, { name: 'Gin & tonic', units_sold: 85, total_revenue: 1265, margin_pct: 66.4 }],
    cash_flow: Array.from({ length: 14 }, (_, i) => ({ money_in: 500 + i * 18, money_out: 180 + i * 6 })),
  };
  let sessionId = null, selectedDays = 30, currency = localStorage.getItem('seline_currency') || 'EUR';
  const syncField = 'sync_completed_at';
  const noImportsLabel = 'No imports yet';
  const rates = { EUR: 1, RON: 4.97 };
  const money = (value) => new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(Number(value || 0) * rates[currency]);
  const errorBox = $('error');
  if (!demoMode && !window.SelineAuth.requireAuth()) return;
  const user = demoMode ? { role: 'client', email: 'demo@seline.example', client_display_name: 'The Lantern Cafe (Fictional)' } : (window.SelineAuth.getUser() || {});
  if (!demoMode && user.role !== 'client') { window.location.replace('/app'); return; }
  if (demoMode) { $('demo-mode-label').hidden = false; $('demo-mode-label').textContent = 'FICTIONAL DATA MODE · NOT CONNECTED TO A DATABASE'; }
  function showError(message) { errorBox.textContent = message; errorBox.style.display = message ? 'block' : 'none'; }
  function setLoading() { $('kpis').innerHTML = [1,2,3,4].map(() => '<div class="kpi skeleton"></div>').join(''); ['revenue-chart','busy-heatmap','cash-flow','stock-alerts','top-products'].forEach(id => $(id).innerHTML = '<div class="panel-skeleton skeleton"></div>'); }
  function dates() { const end = new Date(), start = new Date(end); start.setDate(end.getDate() - selectedDays + 1); return { start: $('range-start').value || start.toISOString().slice(0,10), end: $('range-end').value || end.toISOString().slice(0,10) }; }
  function renderKpis(data) {
    const rows = [['Revenue', data.revenue.current.revenue, data.revenue.change_pct], ['Gross profit', data.profit.current.gross_profit, data.profit.change_pct], ['Transactions', data.revenue.current.transaction_count, null], ['Profit margin', `${Number(data.profit.current.margin_pct || 0).toFixed(1)}%`, null]];
    $('kpis').innerHTML = rows.map(([label, value, change]) => `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${typeof value === 'string' ? value : money(value)}</div>${change == null ? '' : `<div class="kpi-change ${change < 0 ? 'negative' : ''}">${change >= 0 ? '↑' : '↓'} ${Math.abs(change)}% vs previous</div>`}<div class="sparkline">${[.4,.7,.5,.8,1].map(v => `<i style="height:${v*100}%"></i>`).join('')}</div></div>`).join('');
  }
  function renderChart(rows) { const values = rows || [], max = Math.max(...values.map(r => Number(r.revenue || 0)), 1); $('revenue-chart').innerHTML = values.length ? values.map(r => `<div class="bar" style="height:${Math.max(5, Number(r.revenue || 0) / max * 100)}%" title="${r.period}: ${money(r.revenue)}"><span>${String(r.period).slice(5)}</span></div>`).join('') : '<p class="muted">No sales recorded for this period.</p>'; }
  function renderHeatmap(rows) { const map = {}; (rows || []).forEach(r => map[`${r.weekday}-${r.hour_of_day}`] = Number(r.revenue || 0)); const max = Math.max(...Object.values(map), 1); $('busy-heatmap').innerHTML = Array.from({length: 7}, (_, d) => `<div class="heat-row"><b>${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][d]}</b>${Array.from({length: 24}, (_, h) => `<i title="${h}:00" style="opacity:${.15 + (map[`${d}-${h}`] || 0) / max * .85}"></i>`).join('')}</div>`).join(''); }
  function list(id, rows, empty, fn) { $(id).innerHTML = rows && rows.length ? rows.map(fn).join('') : `<p class="muted">${empty}</p>`; }
  async function loadDashboard() {
    showError(''); $('last-updated').textContent = 'Updating…'; setLoading();
    try {
      const d = dates(), payload = demoMode ? { ...demoPayload, revenue_chart: demoPayload.revenue_chart.slice(-selectedDays), cash_flow: demoPayload.cash_flow.slice(-Math.min(selectedDays, 14)) } : await fetch(`/api/analytics/phase2?start_date=${d.start}&end_date=${d.end}`).then(r => { if (!r.ok) throw Error(); return r.json(); });
      cacheSnapshot(payload);
      $('business-name').textContent = user.client_display_name || user.email || 'Your business'; renderKpis(payload);
      renderChart(payload.revenue_chart); renderHeatmap(payload.busy_hours);
      $('data-status').textContent = demoMode ? 'Live fictional simulation' : 'Connected';
      list('stock-alerts', payload.stock_alerts, 'Stock levels look healthy.', r => `<div class="list-row"><strong>${r.name || r.product_id}</strong><small>${Number(r.days_of_stock_left || 0).toFixed(0)} days · reorder ${r.suggested_reorder_qty || 0}</small></div>`);
      list('top-products', payload.top_products, 'No product sales yet.', r => `<div class="list-row"><strong>${r.name || r.product_id}</strong><small>${r.units_sold || 0} units · ${money(r.total_revenue)} · ${Number(r.margin_pct || 0).toFixed(1)}%</small></div>`);
      const flow = payload.cash_flow || []; const incoming = flow.reduce((s,r)=>s+Number(r.money_in||0),0), outgoing = flow.reduce((s,r)=>s+Number(r.money_out||0),0);
      $('cash-flow').innerHTML = `<div class="cash-grid"><strong>In ${money(incoming)}</strong><strong>Out ${money(outgoing)}</strong><strong>Net ${money(incoming-outgoing)}</strong></div><div class="forecast">Forecast: ${money((incoming-outgoing)/Math.max(flow.length,1)*14)}</div>`;
      $('last-updated').textContent = `Last synced ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
    } catch (e) {
      const cached = readCachedSnapshot();
      if (cached && cached.payload) {
        const payload = cached.payload;
        $('business-name').textContent = user.client_display_name || user.email || 'Your business';
        renderKpis(payload);
        renderChart(payload.revenue_chart);
        renderHeatmap(payload.busy_hours);
        list('stock-alerts', payload.stock_alerts, 'Stock levels look healthy.', r => `<div class="list-row"><strong>${r.name || r.product_id}</strong><small>${Number(r.days_of_stock_left || 0).toFixed(0)} days · reorder ${r.suggested_reorder_qty || 0}</small></div>`);
        list('top-products', payload.top_products, 'No product sales yet.', r => `<div class="list-row"><strong>${r.name || r.product_id}</strong><small>${r.units_sold || 0} units · ${money(r.total_revenue)} · ${Number(r.margin_pct || 0).toFixed(1)}%</small></div>`);
        showError('Offline: showing the last loaded snapshot.');
        $('last-updated').textContent = `Cached ${new Date(cached.savedAt).toLocaleString()}`;
      } else {
        showError('Business data could not be loaded. Try again.');
        $('last-updated').textContent = 'Unavailable';
      }
    }
  }
  async function askAssistant(event) { event.preventDefault(); const input = $('assistant-input'), message = input.value.trim(); if (!message) return; const box = $('assistant-messages'); box.innerHTML += `<div class="message user">${message}</div>`; input.value = ''; if (demoMode) { box.innerHTML += `<div class="message">Demo insight: revenue is up 12.4% versus the previous period. House lager and espresso martinis are leading sales; limes need reordering soon.</div>`; box.scrollTop=box.scrollHeight; return; } try { const r = await fetch('/api/assistant/chat/simple', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message, session_id:sessionId})}); if (!r.ok) throw Error(); const d=await r.json(); sessionId=d.session_id; box.innerHTML += `<div class="message">${d.reply}</div>`; } catch(e) { box.innerHTML += '<div class="message">Assistant is unavailable right now.</div>'; } box.scrollTop=box.scrollHeight; }
  document.querySelectorAll('.range-button').forEach(b => b.addEventListener('click', () => { selectedDays = Number(b.dataset.days); document.querySelectorAll('.range-button').forEach(x=>x.classList.toggle('active', x===b)); $('range-start').value=''; $('range-end').value=''; loadDashboard(); }));
  ['range-start','range-end'].forEach(id => $(id).addEventListener('change', () => { if ($('range-start').value && $('range-end').value) loadDashboard(); }));
  $('currency-select').value = currency; $('currency-select').addEventListener('change', e => { currency=e.target.value; localStorage.setItem('seline_currency', currency); loadDashboard(); });
  document.querySelectorAll('.chips button').forEach(b => b.addEventListener('click', () => { $('assistant-input').value=b.textContent; $('assistant-form').requestSubmit(); }));
  $('mic-button').addEventListener('click', () => { const SR=window.SpeechRecognition||window.webkitSpeechRecognition; if(!SR) return $('assistant-input').placeholder='Microphone unavailable'; const r=new SR(); r.lang='en-US'; r.onresult=e=>$('assistant-input').value=e.results[0][0].transcript; r.start(); });
  $('refresh-button').addEventListener('click', loadDashboard); $('assistant-form').addEventListener('submit', askAssistant); $('theme-toggle').addEventListener('click',()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='light'?'dark':'light';}); document.documentElement.dataset.theme=localStorage.getItem('seline_theme')||'dark'; loadDashboard(); if (demoMode) setInterval(loadDashboard, 15000);
})();
