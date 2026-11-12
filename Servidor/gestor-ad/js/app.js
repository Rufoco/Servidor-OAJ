/* ── Token de sesión (compartido con gestor-ad via sessionStorage) ── */
function getToken() {
  return sessionStorage.getItem('gad_token') || null;
}

function authHeaders() {
  const t = getToken();
  const h = { 'Content-Type': 'application/json' };
  if (t) h['Authorization'] = 'Bearer ' + t;
  return h;
}

/* ── Verificar sesión al cargar ──────────────────────────────────── */
async function verificarSesion() {
  const t = getToken();
  if (!t) {
    mostrarLoginOverlay();
    return false;
  }
  const r = await fetch('/api/session', {
    headers: { 'Authorization': 'Bearer ' + t }
  }).catch(() => null);
  if (!r || r.status !== 200) {
    sessionStorage.removeItem('gad_token');
    mostrarLoginOverlay();
    return false;
  }
  const data = await r.json();
  if (!data.ok) {
    sessionStorage.removeItem('gad_token');
    mostrarLoginOverlay();
    return false;
  }
  mostrarUsuarioActivo(data.display);
  return true;
}

function mostrarUsuarioActivo(display) {
  const el = document.getElementById('session-user');
  if (el) el.textContent = display;
  const bar = document.getElementById('session-bar');
  if (bar) bar.style.display = 'flex';
}

function mostrarLoginOverlay() {
  const overlay = document.getElementById('login-overlay-mc');
  if (overlay) {
    overlay.style.display = 'flex';
  } else {
    // Fallback: redirigir al gestor-ad para login
    alert('Sesión expirada. Inicia sesión en el Gestor AD primero.');
    window.location.href = '/gestor-ad/';
  }
}

/* ── Consulta usuarios con token ─────────────────────────────────── */
async function consultarUsuarios(usernames) {
  const r = await fetch('/api/usuarios', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ users: usernames })
  });
  if (r.status === 401) {
    sessionStorage.removeItem('gad_token');
    mostrarLoginOverlay();
    throw new Error('No autenticado');
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.error || 'Error en la consulta');
  }
  return r.json();
}

/* ── Login inline (para migracion-cjf) ──────────────────────────── */
async function loginMC(user, password, dominio) {
  const r = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user, password, dominio: dominio || 'cjf' })
  });
  const data = await r.json().catch(() => ({}));
  if (r.ok && data.ok) {
    sessionStorage.setItem('gad_token', data.token);
    mostrarUsuarioActivo(data.display);
    return true;
  }
  return false;
}

async function logoutMC() {
  const t = getToken();
  if (t) {
    await fetch('/api/logout', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + t }
    }).catch(() => {});
  }
  sessionStorage.removeItem('gad_token');
  mostrarLoginOverlay();
}
