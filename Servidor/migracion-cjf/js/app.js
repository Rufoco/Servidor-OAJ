/* Migración de Usuarios — app.js (diseño Gestor AD · búsqueda por cuenta o expediente · licencias M365 desde Excel) */
(function () {
'use strict';

const LM365_URL = 'data/LM365.xlsx';
const $ = id => document.getElementById(id);
const norm = v => String(v == null ? '' : v).trim().toLowerCase();
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const esExpediente = s => /^\d{3,}$/.test(s);

let tok = sessionStorage.getItem('mc_token') || null;
let dl = 'cjf', dark = true;
let rows = [], lic = null, licError = '', avisoTimer = null, expError = '';

const ICO_MOON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
const ICO_SUN = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
function applyTheme() {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  $('theme-toggle').innerHTML = dark ? ICO_MOON : ICO_SUN;
}

async function api(m, p, b) {
  const h = { 'Content-Type': 'application/json' };
  if (tok) h['Authorization'] = 'Bearer ' + tok;
  const r = await fetch(p, { method: m, headers: h, body: b ? JSON.stringify(b) : undefined });
  const d = await r.json().catch(() => ({}));
  return { s: r.status, d };
}

async function checkSess() {
  if (!tok) return showLogin();
  const { s, d } = await api('GET', '/api/session');
  if (s === 200 && d.ok !== false) showApp(d.display);
  else { tok = null; sessionStorage.removeItem('mc_token'); showLogin(); }
}
function showLogin() {
  $('lo').style.display = 'flex';
  $('app').style.display = 'none';
  setTimeout(() => $('lu').focus(), 80);
}
function showApp(disp) {
  $('lo').style.display = 'none';
  $('app').style.display = 'flex';
  $('husr').textContent = disp || '—';
}
async function doLogin() {
  const u = $('lu').value.trim(), p = $('lp').value, e = $('lerr');
  e.style.display = 'none';
  if (!u || !p) { e.textContent = '⚠ Ingresa usuario y contraseña'; e.style.display = 'block'; return; }
  const b = $('lbtn'); b.disabled = true; b.innerHTML = '<span class="spin"></span> Verificando…';
  try {
    const { s, d } = await api('POST', '/api/login', { user: u, password: p, dominio: dl });
    if (s === 200 && d.ok) {
      tok = d.token; sessionStorage.setItem('mc_token', tok);
      $('lp').value = '';
      showApp(d.display);
    } else {
      e.textContent = '⚠ ' + (d.error || 'Credenciales incorrectas'); e.style.display = 'block';
    }
  } catch (err) {
    e.textContent = '⚠ Error de red: ' + err.message; e.style.display = 'block';
  }
  b.disabled = false; b.innerHTML = 'Iniciar sesión';
}
async function doLogout() {
  await api('POST', '/api/logout').catch(() => {});
  tok = null; sessionStorage.removeItem('mc_token');
  limpiar();
  $('lu').value = '';
  showLogin();
}

function limpiar() {
  $('user-list').value = '';
  $('input-count').textContent = '';
  $('card-result').style.display = 'none';
  rows = []; expError = '';
}
function contar() {
  const n = $('user-list').value.split('\n').map(l => l.trim()).filter(Boolean).length;
  $('input-count').textContent = n > 0 ? n + ' líneas' : '';
}

/* Registro de /api/ad/buscar -> mismos nombres de campo que /api/usuarios */
function normalizar(u) {
  return {
    ID: u.ID, Nombre: u.Nombre, Apellido: u.Apellido, Usuario: u.Usuario, Correo: u.Correo,
    DisplayName: u.DisplayName, description: u.description, Office: u.Office,
    telephoneNumber: u.telephoneNumber != null ? u.telephoneNumber : u.Telefono,
    title: u.title != null ? u.title : u.Cargo,
    department: u.department != null ? u.department : u.Departamento,
    company: u.company != null ? u.company : u.Empresa,
    streetAddress: u.streetAddress, l: u.l, st: u.st, postalCode: u.postalCode,
    hab: u.hab != null ? u.hab : u.habilitado
  };
}

/* Busca un expediente con el mismo endpoint que usa Gestor AD (/api/ad/buscar, dominio CJF) */
async function buscarExpediente(q) {
  const { s, d } = await api('POST', '/api/ad/buscar', { query: q, dominio: 'cjf' });
  if (s === 401) return { auth: true };
  if (s === 403) return { error: 'Necesitas sesión en CJF para buscar por expediente' };
  if (s !== 200 || !Array.isArray(d)) return { error: d.error || ('HTTP ' + s) };
  if (!d.length) return { lista: [] };
  let m = d.filter(u => norm(u.ID) === q);
  if (!m.length) m = d.filter(u => new RegExp('(^|\\D)' + q + '(\\D|$)').test(String(u.description || '')));
  if (!m.length && d.length === 1) m = d;
  return { lista: m };
}

async function procesar() {
  const lineas = [...new Set($('user-list').value.split('\n').map(l => l.trim().toLowerCase()).filter(Boolean))];
  if (!lineas.length) { alert('Escribe al menos un usuario o expediente.'); return; }
  const cuentas = lineas.filter(l => !esExpediente(l));
  const expedientes = lineas.filter(esExpediente);
  const btn = $('btn-generar');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Consultando AD…';
  expError = '';
  try {
    const porExp = {};
    for (let i = 0; i < expedientes.length; i += 5) {
      const lote = expedientes.slice(i, i + 5);
      const res = await Promise.all(lote.map(buscarExpediente));
      for (let j = 0; j < lote.length; j++) {
        const r = res[j];
        if (r.auth) { await doLogout(); return; }
        if (r.error) { expError = r.error; porExp[lote[j]] = []; }
        else porExp[lote[j]] = r.lista;
      }
    }
    const nombres = new Set(cuentas);
    Object.values(porExp).forEach(l => l.forEach(u => { if (u.Usuario) nombres.add(norm(u.Usuario)); }));

    let datos = {};
    if (nombres.size) {
      const { s, d } = await api('POST', '/api/usuarios', { users: [...nombres] });
      if (s === 401) { await doLogout(); return; }
      if (s !== 200) { alert('Error al consultar el AD:\n' + (d.error || ('HTTP ' + s))); return; }
      datos = d;
    }

    rows = [];
    for (const l of lineas) {
      if (esExpediente(l)) {
        const lista = porExp[l] || [];
        if (!lista.length) rows.push({ _input: l, _found: false, _exp: true });
        else lista.forEach(u => {
          const completo = datos[norm(u.Usuario)];
          rows.push(Object.assign({ _input: l, _found: true, _exp: true }, normalizar(u), completo || {}));
        });
      } else {
        rows.push(datos[l] ? Object.assign({ _input: l, _found: true }, datos[l]) : { _input: l, _found: false });
      }
    }
    await verificarLicencias(false);
    $('card-result').style.display = 'block';
    $('btn-m365').style.display = rows.some(r => r._found) ? 'inline-flex' : 'none';
    renderTabla(); avisoLicencias();
    $('card-result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) {
    alert('No se pudo conectar con el servidor:\n' + err.message);
  } finally {
    btn.disabled = false; btn.innerHTML = 'Generar lista';
  }
}

async function cargarLicencias(forzar) {
  if (lic && !forzar) return lic;
  if (!window.XLSX) throw new Error('No se cargó js/xlsx.full.min.js');
  const res = await fetch(LM365_URL + '?v=' + Date.now(), { cache: 'no-store' });
  if (!res.ok) throw new Error('No se encontró el archivo (HTTP ' + res.status + ')');
  const fecha = res.headers.get('Last-Modified');
  const wb = XLSX.read(await res.arrayBuffer(), { type: 'array' });
  const ws = wb.Sheets['BD'] || wb.Sheets[wb.SheetNames[0]];
  const filas = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' });
  let cab = -1, col = -1;
  for (let i = 0; i < Math.min(filas.length, 10) && col < 0; i++) {
    const j = filas[i].findIndex(c => ['red', 'correo', 'email', 'e-mail'].includes(norm(c)));
    if (j >= 0) { cab = i; col = j; }
  }
  if (col < 0) throw new Error('No se encontró la columna "RED" en el Excel');
  const correos = new Set(), usuarios = new Set();
  for (let i = cab + 1; i < filas.length; i++) {
    const mail = norm(filas[i][col]);
    if (!mail) continue;
    correos.add(mail); usuarios.add(mail.split('@')[0]);
  }
  lic = { correos, usuarios, total: correos.size, fecha: fecha ? new Date(fecha).toLocaleDateString('es-MX') : '' };
  return lic;
}
async function verificarLicencias(forzar) {
  try { await cargarLicencias(forzar); licError = ''; }
  catch (err) { lic = null; licError = err.message || String(err); }
  for (const r of rows) {
    if (!r._found) continue;
    const usuario = norm(r.Usuario || r._input), correo = norm(r.Correo);
    r._m365 = lic ? (lic.usuarios.has(usuario) || (correo !== '' && lic.correos.has(correo))) : null;
  }
}
function avisoLicencias() {
  const bar = $('m365-progress');
  clearTimeout(avisoTimer);
  if (!lic) { bar.style.display = 'none'; return; }
  $('m365-fill').style.width = '100%';
  $('m365-label').textContent = '✓ Lista M365 cargada — ' + lic.total.toLocaleString('es-MX') + ' cuentas' + (lic.fecha ? ' · actualizada ' + lic.fecha : '');
  bar.style.display = 'block';
  avisoTimer = setTimeout(() => { bar.style.display = 'none'; }, 4000);
}
async function recargarM365() {
  const b = $('btn-m365');
  b.disabled = true; b.innerHTML = '<span class="spin"></span> Leyendo Excel…';
  await verificarLicencias(true);
  b.disabled = false; b.innerHTML = 'Recargar M365';
  renderTabla(); avisoLicencias();
}

function renderTabla() {
  const found = rows.filter(r => r._found);
  const missing = rows.filter(r => !r._found);
  const dis = found.filter(r => r.hab !== 'SI');
  const con = found.filter(r => r._m365 === true).length;
  const sin = found.filter(r => r._m365 === false).length;

  $('chips').innerHTML =
    '<span class="stbadge bprim">Total: ' + rows.length + '</span>' +
    '<span class="stbadge bok">Encontrados: ' + found.length + '</span>' +
    (missing.length ? '<span class="stbadge boff">No encontrados: ' + missing.length + '</span>' : '') +
    (dis.length ? '<span class="stbadge bwrn">Deshabilitados: ' + dis.length + '</span>' : '') +
    (lic ? '<span class="stbadge bprim">Con licencia: ' + con + '</span><span class="stbadge boff">Sin licencia: ' + sin + '</span>' : '');

  let n = '';
  if (missing.length) n += '<div class="notice n-err">⚠ No se encontraron en el AD: ' + missing.map(r => esc(r._input)).join(', ') + '</div>';
  if (expError) n += '<div class="notice n-err">⚠ Búsqueda por expediente: ' + esc(expError) + '</div>';
  if (dis.length) n += '<div class="notice n-warn">⚠ Cuentas deshabilitadas: ' + dis.map(r => esc(r.Usuario || r._input)).join(', ') + '</div>';
  if (licError) n += '<div class="notice n-err">⚠ No se pudo verificar M365: ' + esc(licError) + '</div>';
  $('notices').innerHTML = n;

  $('tbody').innerHTML = rows.map(r => {
    if (!r._found) return '<tr class="rerr"><td class="cu">' + esc(r._input) + '</td><td class="cm">' + (r._exp ? esc(r._input) : '') + '</td><td colspan="6" class="cm">' + (r._exp ? 'Expediente no encontrado en el AD' : 'No encontrado en el AD') + '</td><td><span class="badge bmut">—</span></td></tr>';
    const hab = r.hab === 'SI';
    const m = r._m365 === true ? '<span class="badge bprim">✓ Con licencia</span>'
            : r._m365 === false ? '<span class="badge boff">✗ Sin licencia</span>'
            : '<span class="badge bmut">Sin verificar</span>';
    return '<tr class="' + (hab ? 'rok' : 'rdis') + '">' +
      '<td class="cu">' + esc(r.Usuario || r._input) + (r._exp ? '<small>por expediente</small>' : '') + '</td>' +
      '<td class="cm">' + esc(r.ID) + '</td>' +
      '<td>' + esc(r.Nombre || r.DisplayName) + '</td><td>' + esc(r.Apellido) + '</td>' +
      '<td class="cm">' + esc(r.Correo) + '</td><td class="cm">' + esc(r.title) + '</td><td class="cm">' + esc(r.department) + '</td>' +
      '<td><span class="badge ' + (hab ? 'bok' : 'bwrn') + '">' + (hab ? 'Habilitada' : 'Deshabilitada') + '</span></td>' +
      '<td>' + m + '</td></tr>';
  }).join('');
}

/* ── Exportar Excel (formato original: hoja "Detalles Migración", 17 columnas) ── */
function crearXLSX(datos, nombre) {
  const HEADERS = ['ID', 'Nombre', 'Apellido', 'Usuario', 'Correo', 'DisplayName', 'description', '', 'Office',
    'telephoneNumber', 'title', 'department', 'company', 'streetAddress', 'l', 'st', 'postalCode'];
  const COLWIDTHS = [8, 18, 22, 16, 34, 30, 12, 4, 18, 14, 44, 12, 46, 24, 16, 22, 12].map(w => ({ wch: w }));
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.json_to_sheet(datos, { header: HEADERS });
  ws['!cols'] = COLWIDTHS;
  XLSX.utils.book_append_sheet(wb, ws, 'Detalles Migración');
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
  const blob = new Blob([buf], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = nombre;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}
function exportar() {
  const found = rows.filter(r => r._found);
  if (!found.length) { alert('No hay usuarios para exportar.'); return; }
  if (!window.XLSX) { alert('No se cargó la librería xlsx.full.min.js'); return; }
  const fecha = new Date().toISOString().slice(0, 10);
  const datos = found.map(r => ({
    'ID': r.ID || '', 'Nombre': r.Nombre || '', 'Apellido': r.Apellido || '',
    'Usuario': r.Usuario || r._input, 'Correo': r.Correo || '', 'DisplayName': r.DisplayName || '',
    'description': r.description || '', '': '', 'Office': r.Office || '',
    'telephoneNumber': r.telephoneNumber || '', 'title': r.title || '', 'department': r.department || '',
    'company': r.company || '', 'streetAddress': r.streetAddress || '', 'l': r.l || '', 'st': r.st || '',
    'postalCode': r.postalCode || ''
  }));
  crearXLSX(datos, 'DetalleUserCJF-OAJ_' + fecha + '.xlsx');
}

document.addEventListener('DOMContentLoaded', () => {
  applyTheme();
  $('theme-toggle').addEventListener('click', () => { dark = !dark; applyTheme(); });
  document.querySelectorAll('.dtab').forEach(t => t.addEventListener('click', () => {
    dl = t.dataset.d;
    document.querySelectorAll('.dtab').forEach(x => x.classList.toggle('on', x.dataset.d === dl));
  }));
  $('ptgl').addEventListener('click', () => { const i = $('lp'); i.type = i.type === 'password' ? 'text' : 'password'; });
  $('lbtn').addEventListener('click', doLogin);
  $('lp').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  $('lu').addEventListener('keydown', e => { if (e.key === 'Enter') $('lp').focus(); });
  $('blout').addEventListener('click', doLogout);
  $('user-list').addEventListener('input', contar);
  $('btn-generar').addEventListener('click', procesar);
  $('btn-limpiar').addEventListener('click', limpiar);
  $('btn-m365').addEventListener('click', recargarM365);
  $('btn-xls').addEventListener('click', exportar);
  checkSess();
});
})();
