(() => {
  const $ = (selector) => document.querySelector(selector);

  const root = document.documentElement;
  const button = $('#actualizar');
  const status = $('#estado');
  const sedeSelect = $('#sedeInventario');
  const themeButton = $('[data-theme-toggle]');

  let token = null;
  let theme = window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';

  function themeIcon() {
    themeButton.innerHTML = theme === 'dark'
      ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`
      : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
    root.dataset.theme = theme;
  }

  function setDomain(domain, data) {
    const safe = data || {};
    $(`#${domain}-total`).textContent = safe.total ?? 0;
    $(`#${domain}-win10`).textContent = safe.win10 ?? 0;
    $(`#${domain}-win11`).textContent = safe.win11 ?? 0;
    $(`#${domain}-otros`).textContent = safe.otros ?? 0;
    $(`#${domain}-error`).textContent = safe.error || '';
  }

  function total(data, field) {
    return Number(data.cjf?.[field] || 0) + Number(data.oaj?.[field] || 0);
  }

  function closeLogin() {
    $('#login-modal').hidden = true;
    $('#login-user').value = '';
    $('#login-password').value = '';
  }

  function showLogin(domain, message = '') {
    $('#login-domain').value = domain;
    $('#login-title').textContent = token
      ? `Autenticar ${domain.toUpperCase()}`
      : 'Iniciar sesión';
    $('#login-message').textContent = message || (
      token
        ? `Ingresa tus credenciales de ${domain.toUpperCase()} para consultar sus equipos.`
        : 'Usa tus credenciales de Active Directory para consultar el inventario.'
    );
    $('#login-error').textContent = '';
    $('#login-modal').hidden = false;
    $('#login-user').focus();
  }

  async function readJson(response) {
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();
    if (!contentType.includes('application/json')) {
      throw new Error(
        `El servidor devolvió una respuesta inválida (${response.status}). ` +
        'Verifica que servidor.py tenga la ruta /api/inventario-equipos.'
      );
    }
    try {
      return JSON.parse(raw);
    } catch {
      throw new Error('El servidor devolvió JSON inválido.');
    }
  }

  async function submitLogin(event) {
    event.preventDefault();
    const domain = $('#login-domain').value;
    const user = $('#login-user').value.trim();
    const password = $('#login-password').value;
    const error = $('#login-error');
    const submit = $('#login-submit');

    if (!user || !password) {
      error.textContent = 'Escribe tu usuario y contraseña.';
      return;
    }

    submit.disabled = true;
    error.textContent = '';

    try {
      const endpoint = token ? '/api/login-domain' : '/api/login';
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;

      const response = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify({ dominio: domain, user, password })
      });

      const data = await readJson(response);
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'No se pudo iniciar sesión.');
      }
      if (!token) token = data.token;

      closeLogin();
      cargarInventario();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      submit.disabled = false;
    }
  }

  async function cargarInventario() {
    if (!token) {
      showLogin('cjf');
      return;
    }

    button.disabled = true;
    const sede = sedeSelect ? sedeSelect.value : 'jalisco';
    const sedeTexto = sedeSelect ? sedeSelect.options[sedeSelect.selectedIndex].text : 'Todo Jalisco';
    status.textContent = `Consultando equipos en Active Directory (${sedeTexto})…`;

    try {
      const response = await fetch('/apiinventario-equipos', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ sede })
      });

      const data = await readJson(response);

      if (response.status === 401) {
        token = null;
        showLogin('cjf', 'Tu sesión expiró. Vuelve a iniciar sesión.');
        return;
      }

      if (!response.ok) {
        throw new Error(data.error || 'No fue posible consultar el inventario.');
      }

      setDomain('cjf', data.cjf);
      setDomain('oaj', data.oaj);

      $('#global-total').textContent = total(data, 'total');
      $('#global-win10').textContent = total(data, 'win10');
      $('#global-win11').textContent = total(data, 'win11');

      status.textContent = `Consulta terminada: ${new Date().toLocaleString('es-MX')}`;

      if (data.oaj?.need_auth) {
        showLogin('oaj', data.oaj.error);
      } else if (data.cjf?.need_auth) {
        showLogin('cjf', data.cjf.error);
      }
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    } finally {
      button.disabled = false;
    }
  }

  themeButton.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    themeIcon();
  });

  button.addEventListener('click', cargarInventario);
  if (sedeSelect) {
    sedeSelect.addEventListener('change', () => {
      if (token) cargarInventario();
    });
  }
  $('#login-form').addEventListener('submit', submitLogin);
  $('#login-cancel').addEventListener('click', () => {
    if (token) closeLogin();
  });

  themeIcon();
  showLogin('cjf');
})();
