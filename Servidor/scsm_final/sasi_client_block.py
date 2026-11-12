
# ── Cliente HTTP para SASI (manejo de sesión PHP) ─────────────────────────────

import urllib.request, urllib.parse, urllib.error, urllib.response
import http.cookiejar, ssl, re

# URL base del sistema SASI
SASI_BASE    = cfg.get("sasi", "url",       fallback="http://10.2.171.6/sasi/sm.php").rstrip("/")
SASI_ROOT    = cfg.get("sasi", "root",      fallback="http://10.2.171.6/sasi")
SASI_LOGIN   = cfg.get("sasi", "login_url", fallback="http://10.2.171.6/sasi/index.php")

# Campos del formulario de login de index.php (ajustar si son distintos)
SASI_FIELD_USER = cfg.get("sasi", "field_user", fallback="user")
SASI_FIELD_PASS = cfg.get("sasi", "field_pass", fallback="password")
SASI_FIELD_DOM  = cfg.get("sasi", "field_dom",  fallback="domain")

def _make_opener():
    """Crea un urllib opener con cookie jar y sin verificar SSL."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    jar     = http.cookiejar.CookieJar()
    cookie_handler = urllib.request.HTTPCookieProcessor(jar)
    https_handler  = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(cookie_handler, https_handler)
    opener.addheaders = [
        ("User-Agent",      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 SCSM-Portal/1.0"),
        ("Accept",          "text/html,application/json,*/*"),
        ("Accept-Language", "es-MX,es;q=0.9"),
        ("Connection",      "keep-alive"),
    ]
    return opener, jar

def _sasi_login(user: str, password: str, domain: str,
                timeout: int = 15) -> tuple:
    """
    Hace login en index.php y devuelve (opener, jar) con la sesión activa.
    Lanza PermissionError si el login falla.
    """
    opener, jar = _make_opener()

    # 1) GET index.php para obtener cookies iniciales y descubrir el form
    try:
        resp = opener.open(SASI_LOGIN, timeout=timeout)
        html = resp.read().decode("utf-8", errors="replace")
        print(f"[SASI] index.php cargado ({len(html)} bytes)")
    except Exception as e:
        raise ConnectionError(f"No se pudo cargar {SASI_LOGIN}: {e}")

    # 2) Intentar detectar los nombres reales de los campos del form
    field_user = SASI_FIELD_USER
    field_pass = SASI_FIELD_PASS
    field_dom  = SASI_FIELD_DOM
    action_url = SASI_LOGIN  # default: el mismo index.php

    # Buscar <form action="...">
    m_action = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.I)
    if m_action:
        action_raw = m_action.group(1)
        if action_raw.startswith("http"):
            action_url = action_raw
        else:
            action_url = SASI_ROOT.rstrip("/") + "/" + action_raw.lstrip("/")

    # Buscar campos de tipo password → ese es el campo de contraseña
    m_pass  = re.search(r'<input[^>]+type=["\']password["\'][^>]*name=["\']([^"\']+)["\']', html, re.I)
    if not m_pass:
        m_pass = re.search(r'<input[^>]+name=["\']([^"\']+)["\'][^>]*type=["\']password["\']', html, re.I)
    if m_pass:
        field_pass = m_pass.group(1)

    # Buscar campo de usuario (generalmente el input text antes del password)
    m_user  = re.search(r'<input[^>]+type=["\']text["\'][^>]*name=["\']([^"\']+)["\']', html, re.I)
    if not m_user:
        m_user = re.search(r'<input[^>]+name=["\']([^"\']+)["\'][^>]*type=["\']text["\']', html, re.I)
    if m_user:
        field_user = m_user.group(1)

    # Buscar campo de dominio (select o input con "domain"/"dominio" en nombre/id)
    m_dom = re.search(r'<(?:input|select)[^>]+name=["\']([^"\']*(?:domain|dominio)[^"\']*)["\']',
                      html, re.I)
    if m_dom:
        field_dom = m_dom.group(1)

    # Recopilar todos los hidden inputs (tokens CSRF, etc.)
    hidden_fields = {}
    for m in re.finditer(
            r'<input[^>]+type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
            html, re.I):
        hidden_fields[m.group(1)] = m.group(2)
    for m in re.finditer(
            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*type=["\']hidden["\'][^>]*value=["\']([^"\']*)["\']',
            html, re.I):
        hidden_fields[m.group(1)] = m.group(2)

    print(f"[SASI] Form → action={action_url}  "
          f"user={field_user}  pass={field_pass}  dom={field_dom}")
    print(f"[SASI] Hidden fields: {list(hidden_fields.keys())}")

    # 3) POST de login
    post_data = {**hidden_fields,
                 field_user: user,
                 field_pass: password}
    # Solo incluir el campo de dominio si existe en el formulario
    if m_dom:
        post_data[field_dom] = domain

    encoded = urllib.parse.urlencode(post_data).encode("utf-8")
    req = urllib.request.Request(
        action_url, data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Referer": SASI_LOGIN}
    )
    try:
        resp2 = opener.open(req, timeout=timeout)
        body2 = resp2.read().decode("utf-8", errors="replace")
        print(f"[SASI] POST login → HTTP {resp2.status}  ({len(body2)} bytes): "
              f"{body2[:200]!r}")
    except urllib.error.HTTPError as e:
        body2 = e.read().decode("utf-8", errors="replace")
        print(f"[SASI] POST login → HTTP {e.code}: {body2[:200]!r}")

    # 4) Verificar que el login fue exitoso
    if ("No se encuentra autorizado" in body2 or
            "window.location='index.php'" in body2 or
            "login" in resp2.geturl().lower() and "session" not in body2.lower()):
        raise PermissionError(
            "sm.php rechazó las credenciales. "
            "Verifica usuario/contraseña y que el campo del formulario sea correcto."
        )

    # Mostrar cookies obtenidas (sin valores sensibles)
    cookie_names = [c.name for c in jar]
    print(f"[SASI] Cookies tras login: {cookie_names}")

    return opener, jar


def _sasi_get_reports(opener, user: str, domain: str,
                      tipo: str = "all", timeout: int = 30) -> str:
    """
    Llama a sm.php con la sesión activa.
    Prueba varios métodos de llamada en orden hasta obtener datos válidos.
    """
    url = SASI_BASE

    # Intentos en orden: cada uno con distintos parámetros
    attempts = [
        # 1) GET simple — sm.php sin parámetros
        {"method": "GET",  "params": {}},
        # 2) GET con action=list
        {"method": "GET",  "params": {"action": "list"}},
        # 3) POST con action=list
        {"method": "POST", "params": {"action": "list"}},
        # 4) POST con tipo explícito
        {"method": "POST", "params": {"action": "list", "tipo": tipo}},
        # 5) GET con usuario en query string
        {"method": "GET",  "params": {"user": user, "domain": domain}},
    ]

    for attempt in attempts:
        try:
            if attempt["method"] == "GET" and attempt["params"]:
                full_url = url + "?" + urllib.parse.urlencode(attempt["params"])
                req = urllib.request.Request(full_url)
            elif attempt["method"] == "POST":
                encoded = urllib.parse.urlencode(attempt["params"]).encode("utf-8")
                req = urllib.request.Request(
                    url, data=encoded,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
            else:
                req = urllib.request.Request(url)

            resp = opener.open(req, timeout=timeout)
            raw  = resp.read().decode("utf-8", errors="replace")

            print(f"[SASI] sm.php ({attempt['method']} {attempt['params']}) "
                  f"→ {len(raw)} bytes: {raw[:150]!r}")

            # Si sigue dando el error de autorización, probar siguiente
            if "No se encuentra autorizado" in raw or "window.location='index.php'" in raw:
                continue

            # Si obtuvo algo útil, retornar
            if raw.strip():
                return raw

        except Exception as e:
            print(f"[SASI] Intento fallido {attempt}: {e}")
            continue

    # Si todos fallaron, retornar cadena vacía
    print("[SASI] Todos los intentos fallaron. sm.php sigue redirigiendo a index.php.")
    return ""


def get_reports(user: str, password: str, domain: str,
                tipo: str = "all") -> list:
    """
    Obtiene reportes del usuario desde SASI/sm.php.
    1. Hace login en index.php (obtiene cookie de sesión PHP)
    2. Llama a sm.php con esa sesión
    3. Parsea y filtra la respuesta
    """
    opener, jar = _sasi_login(user, password, domain)
    raw   = _sasi_get_reports(opener, user, domain, tipo=tipo)
    items = _parse_sasi_response(raw)

    if tipo != "all":
        items = [i for i in items if i.get("Tipo", "").lower() == tipo.lower()]

    # Excluir cerrados
    items = [i for i in items
             if not any(kw in i.get("Estado", "").lower()
                        for kw in ("cerr", "closed", "cancel"))]
    return items


def get_report_detail(user: str, password: str, domain: str,
                      report_id: str) -> dict:
    opener, jar = _sasi_login(user, password, domain)
    # Intentar obtener detalle con el ID
    for params in [{"action": "detail", "id": report_id},
                   {"id": report_id},
                   {"reporte": report_id}]:
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            SASI_BASE, data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            resp = opener.open(req, timeout=30)
            raw  = resp.read().decode("utf-8", errors="replace")
            if "No se encuentra autorizado" not in raw and raw.strip():
                items = _parse_sasi_response(raw)
                if items:
                    item = items[0]
                    if not item.get("Actividades"):
                        item["Actividades"] = []
                    return item
        except Exception as e:
            print(f"[SASI] detail error: {e}")
    return {}


def add_comment(user: str, password: str, domain: str,
                report_id: str, texto: str) -> bool:
    opener, jar = _sasi_login(user, password, domain)
    params = {"action": "comment", "id": report_id, "comment": texto}
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        SASI_BASE, data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    resp = opener.open(req, timeout=30)
    raw  = resp.read().decode("utf-8", errors="replace")
    print(f"[SASI] comentar → {raw[:150]!r}")
    return True


def set_action(user: str, password: str, domain: str,
               report_id: str, accion: str, texto: str = "") -> str:
    accion = (accion or "").strip().lower()
    if accion not in ("resolve", "close"):
        raise ValueError("Accion no valida")
    opener, jar = _sasi_login(user, password, domain)
    params = {"action": accion, "id": report_id, "comment": texto or ""}
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        SASI_BASE, data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    resp = opener.open(req, timeout=30)
    raw  = resp.read().decode("utf-8", errors="replace")
    print(f"[SASI] accion {accion} → {raw[:150]!r}")
    return "Resuelto" if accion == "resolve" else "Cerrado"
