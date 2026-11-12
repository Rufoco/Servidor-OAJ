/* compartido/auth.js
 * Login propio para cada herramienta, con el mismo estilo del Gestor AD y solo dominio OAJ.
 * Usa el mismo token que el Gestor AD (gad_token en sessionStorage): si ya iniciaste sesion en otra
 * herramienta de esta pestana, no vuelve a pedirla. Si no hay sesion (o expiro), muestra la ventana.
 * Incluir en <head>:  <script src="/compartido/auth.js"></script>
 */
(function () {
  var KEY = 'gad_token';
  var DOMINIO = 'oaj';
  var nativo = window.fetch.bind(window);

  var CSS =
    '#gad-login{position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483647;background:rgba(0,0,0,.5);' +
    'display:flex;align-items:center;justify-content:center;padding:1rem;box-sizing:border-box;' +
    'font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.95rem;line-height:1.4;' +
    '--surface:#ffffff;--surface2:#f8f9fb;--border:#dde1e8;--divider:#e8ebf0;--text:#1a1f2e;--muted:#5a6170;' +
    '--primary:#1a4480;--primary-h:#143568;--primary-hl:#dce6f4;--inverse:#ffffff;' +
    '--error:#b01c2e;--error-hl:#fce8ea;--oaj:#2d7a3a}' +
    '#gad-login.gl-dark{--surface:#161b27;--surface2:#1c2130;--border:#2a3140;--divider:#222838;--text:#e2e5ec;' +
    '--muted:#7a8496;--primary:#5b8dd4;--primary-h:#3a6fbe;--primary-hl:#1c2a40;--inverse:#0f1117;' +
    '--error:#e05a68;--error-hl:#301520;--oaj:#4caf63}' +
    '#gad-login *{box-sizing:border-box}' +
    '#gad-login .gl-modal{background:var(--surface);color:var(--text);border:1px solid var(--border);' +
    'border-radius:1rem;box-shadow:0 8px 24px rgba(0,0,0,.14);width:100%;max-width:420px;overflow:hidden}' +
    '#gad-login .gl-head{padding:1rem 1.25rem;border-bottom:1px solid var(--divider);background:var(--surface2);' +
    'display:flex;align-items:center;gap:.5rem;font-weight:700}' +
    '#gad-login .gl-pill{margin-left:auto;display:inline-flex;align-items:center;gap:.4rem;font-size:.75rem;' +
    'font-weight:600;color:var(--oaj);font-family:"JetBrains Mono",ui-monospace,Consolas,monospace}' +
    '#gad-login .gl-dot{width:7px;height:7px;border-radius:50%;background:var(--oaj)}' +
    '#gad-login .gl-body{padding:1.25rem;display:flex;flex-direction:column;gap:1rem}' +
    '#gad-login .gl-sub{font-size:.8rem;color:var(--muted);margin:0}' +
    '#gad-login .gl-label{display:block;font-size:.75rem;font-weight:700;color:var(--muted);' +
    'text-transform:uppercase;letter-spacing:.06em;margin-bottom:.5rem}' +
    '#gad-login .gl-input{width:100%;padding:.75rem;border:2px solid var(--border);border-radius:.75rem;' +
    'background:var(--surface2);color:var(--text);font:inherit;outline:none;' +
    'transition:border-color .18s,box-shadow .18s,background .18s}' +
    '#gad-login .gl-input:focus{border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-hl);background:var(--surface)}' +
    '#gad-login .gl-btn{padding:.6rem 1.25rem;border:0;border-radius:.5rem;background:var(--primary);' +
    'color:var(--inverse);font:inherit;font-weight:500;cursor:pointer;transition:background .18s}' +
    '#gad-login .gl-btn:hover{background:var(--primary-h)}' +
    '#gad-login .gl-btn:disabled{opacity:.4;pointer-events:none}' +
    '#gad-login .gl-msg{display:none;padding:.75rem 1rem;border-radius:.5rem;font-size:.8rem;' +
    'background:var(--error-hl);color:var(--error);border:1px solid var(--error)}';

  function esOscuro() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t) return t === 'dark';
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  function mostrarLogin(aviso) {
    var msgEl = document.getElementById('gad-msg');
    if (document.getElementById('gad-login')) {
      if (aviso && msgEl) { msgEl.textContent = aviso; msgEl.style.display = 'block'; }
      return;
    }
    var estilo = document.createElement('style');
    estilo.textContent = CSS;
    document.head.appendChild(estilo);

    var fondo = document.createElement('div');
    fondo.id = 'gad-login';
    if (esOscuro()) fondo.className = 'gl-dark';
    fondo.innerHTML =
      '<form class="gl-modal" autocomplete="on">' +
      '<div class="gl-head"><span>Iniciar sesión</span>' +
      '<span class="gl-pill"><span class="gl-dot"></span>OAJ</span></div>' +
      '<div class="gl-body">' +
      '<p class="gl-sub">Acceso institucional. Usa tu usuario de red.</p>' +
      '<div><label class="gl-label" for="gad-user">Usuario de red</label>' +
      '<input class="gl-input" id="gad-user" type="text" autocomplete="username" ' +
      'autocapitalize="off" spellcheck="false" required></div>' +
      '<div><label class="gl-label" for="gad-pass">Contraseña</label>' +
      '<input class="gl-input" id="gad-pass" type="password" autocomplete="current-password" required></div>' +
      '<div class="gl-msg" id="gad-msg"></div>' +
      '<button class="gl-btn" id="gad-btn" type="submit">Iniciar sesión</button>' +
      '</div></form>';
    document.body.appendChild(fondo);

    var f = fondo.querySelector('form');
    var us = document.getElementById('gad-user');
    var pw = document.getElementById('gad-pass');
    var msg = document.getElementById('gad-msg');
    var btn = document.getElementById('gad-btn');
    if (aviso) { msg.textContent = aviso; msg.style.display = 'block'; }
    us.focus();

    function error(t) { msg.textContent = t; msg.style.display = 'block'; btn.disabled = false; }

    f.onsubmit = function (e) {
      e.preventDefault();
      btn.disabled = true; msg.style.display = 'none';
      nativo('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: us.value.trim(), password: pw.value, dominio: DOMINIO })
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return { r: r, d: d }; });
      }).then(function (x) {
        if (x.r.ok && x.d.ok) {
          sessionStorage.setItem(KEY, x.d.token);
          location.reload();
        } else {
          error((x.d && x.d.error) || 'Credenciales incorrectas');
        }
      }).catch(function () { error('No se pudo contactar al servidor'); });
    };
  }

  function cuandoListo(fn) {
    if (document.body) fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  function pedirLogin(aviso) {
    sessionStorage.removeItem(KEY);
    cuandoListo(function () { mostrarLogin(aviso); });
  }

  if (!sessionStorage.getItem(KEY)) pedirLogin('');

  window.fetch = function (input, init) {
    init = init || {};
    var url = typeof input === 'string' ? input : ((input && input.url) || '');
    var esApi = url.indexOf('/api/') !== -1;
    var esLogin = url.indexOf('/api/login') !== -1 || url.indexOf('/api/session') !== -1;
    if (esApi && !esLogin) {
      var t = sessionStorage.getItem(KEY);
      if (t) {
        var h = new Headers(init.headers || (typeof input !== 'string' && input.headers) || {});
        if (!h.has('Authorization')) h.set('Authorization', 'Bearer ' + t);
        init.headers = h;
      }
    }
    return nativo(input, init).then(function (r) {
      if (esApi && !esLogin && r.status === 401) pedirLogin('Tu sesión expiró. Inicia sesión de nuevo.');
      return r;
    });
  };
})();
