#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scsm_server_portal.py — Portal Mis Reportes SCSM
# Consulta incidentes y solicitudes a través de SASI (http://10.2.171.6/sasi/sm.php)
# Autenticación de usuarios: Active Directory NTLM via ldap3
#
# pip install ldap3 requests
# python scsm_server_portal.py

import http.server
import socketserver
import os
import json
import configparser
import datetime
import secrets
import threading
import time
import traceback
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    raise SystemExit("Falta la libreria 'requests'. Ejecuta: pip install requests")

# ─── Rutas base ───────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR  = os.path.join(SCRIPT_DIR, "static")
INDEX_HTML  = os.path.join(SCRIPT_DIR, "index.html")
CSS_FILE    = os.path.join(STATIC_DIR, "css", "styles.css")
JS_FILE     = os.path.join(STATIC_DIR, "js",  "app.js")

PORT        = 8081
SESSION_TTL = 8 * 3600

# ─── Configuración ────────────────────────────────────────────────────────────
cfg = configparser.ConfigParser()
cfg.read(os.path.join(SCRIPT_DIR, "config.ini"), encoding="utf-8")

LDAP_SECTIONS = {"cjf": "ldap", "oaj": "ldap_oaj", "tdj": "ldap_tdj"}

def _ldap_cfg(domain: str) -> dict:
    section = LDAP_SECTIONS.get((domain or "").lower(), "ldap")
    if not cfg.has_section(section):
        section = "ldap"
    return {
        "server": cfg.get(section, "server", fallback="CJFDC01366.cjf.gob.mx"),
        "port":   cfg.getint(section, "port",   fallback=389),
        "domain": cfg.get(section, "domain",   fallback=domain or "cjf"),
    }

# URLs de SASI
SASI_LOGIN_URL = cfg.get("sasi", "login_url", fallback="http://10.2.171.6/sasi/app/login.php")
SASI_SM_URL    = cfg.get("sasi", "sm_url",    fallback="http://10.2.171.6/sasi/sm.php")
SASI_TIMEOUT   = cfg.getint("sasi", "timeout", fallback=60)

# Credencial de servicio para SASI (la que usaba el servidor antes)
SASI_USER   = cfg.get("sasi", "user",     fallback="")
SASI_PASS   = cfg.get("sasi", "password", fallback="")
SASI_DOMAIN = cfg.get("sasi", "domain",   fallback="cjf")

# ─── Sesión SASI compartida (una sola sesión de servicio contra SASI) ─────────
_sasi_session: requests.Session | None = None
_sasi_lock    = threading.Lock()
_sasi_last_ok: datetime.datetime | None = None
SASI_SESSION_TTL = 3600  # renovar sesión SASI cada hora

# URL real que entrega TODOS los reportes (descubierta con diagnostico_sasi.py)
SASI_DATA_URL = "http://10.2.171.6/sasi/includes/tablas/getTblarepper.php"

# Cache en memoria de los reportes de SASI (para no golpear el endpoint en cada click)
_sasi_cache: list | None = None
_sasi_cache_ts: datetime.datetime | None = None
SASI_CACHE_TTL = 120  # segundos


def _sasi_login() -> requests.Session:
    """Inicia sesión en SASI usando el formulario correcto (campo 'usuario')."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    SASI_LOGIN_URL,
    })

    # El formulario de SASI usa: name="usuario" y name="password" (sin dominio)
    login_data = {
        "usuario":  SASI_USER or "",
        "password": SASI_PASS or "",
    }

    try:
        r = s.post(SASI_LOGIN_URL, data=login_data, timeout=SASI_TIMEOUT, allow_redirects=True)
        print(f"  [SASI] Login POST -> HTTP {r.status_code} | URL final: {r.url}")

        if "login.php" in r.url.lower():
            raise RuntimeError(
                f"SASI rechazó las credenciales (volvió a login.php). "
                f"Verifica usuario/password en config.ini sección [sasi]."
            )

        cookies = s.cookies.get_dict()
        print(f"  [SASI] Cookies obtenidas: {list(cookies.keys())}")

        if not cookies:
            print("  [SASI] ADVERTENCIA: No se recibieron cookies — revisa usuario/password.")

    except requests.RequestException as e:
        print(f"  [SASI] Error de red en login: {e}")
        raise RuntimeError(f"No se pudo conectar con SASI: {e}")

    return s


def _get_sasi_session() -> requests.Session:
    """Devuelve la sesión SASI activa, renovándola si es necesario."""
    global _sasi_session, _sasi_last_ok
    with _sasi_lock:
        ahora = datetime.datetime.now()
        if (_sasi_session is None or _sasi_last_ok is None or
                (ahora - _sasi_last_ok).total_seconds() > SASI_SESSION_TTL):
            print("  [SASI] Iniciando/renovando sesión de servicio...")
            _sasi_session = _sasi_login()
            _sasi_last_ok = ahora
        return _sasi_session


# Timeout de red para la descarga de reportes (la respuesta pesa ~2 MB, la red es lenta)
SASI_DATA_TIMEOUT = 45   # segundos por intento (bajado de 120 para no bloquear la cola)
SASI_MAX_RETRIES  = 2    # numero total de intentos antes de rendirse (bajado de 4)
SASI_RETRY_WAIT   = 2    # segundos de espera entre reintentos

# Candado exclusivo para la descarga completa de reportes. Evita que dos
# peticiones concurrentes (p. ej. /incidentes y /solicitudes disparadas en
# paralelo por el frontend) descarguen los ~2 MB de SASI al mismo tiempo,
# lo cual duplicaba la carga de red y provocaba timeouts intermitentes.
_sasi_fetch_lock = threading.Lock()


def _fetch_all_reports(force: bool = False) -> list:
    """
    Descarga TODOS los reportes desde el endpoint real de SASI
    (includes/tablas/getTblarepper.php) y los cachea en memoria.

    Si todos los reintentos fallan (timeouts de red, etc.) y ya existe
    una caché previa (aunque haya expirado), se devuelve esa caché en
    lugar de una lista vacia, para no mostrar "0 reportes" por un simple
    problema de red pasajero.
    """
    global _sasi_cache, _sasi_cache_ts, _sasi_last_ok

    ahora = datetime.datetime.now()
    if (not force and _sasi_cache is not None and _sasi_cache_ts is not None and
            (ahora - _sasi_cache_ts).total_seconds() < SASI_CACHE_TTL):
        return _sasi_cache

    with _sasi_fetch_lock:
        # Re-chequeo dentro del candado: si otra peticion concurrente ya
        # refresco la cache mientras esperabamos, usamos ese resultado y
        # evitamos una segunda descarga de ~2 MB innecesaria.
        ahora = datetime.datetime.now()
        if (not force and _sasi_cache is not None and _sasi_cache_ts is not None and
                (ahora - _sasi_cache_ts).total_seconds() < SASI_CACHE_TTL):
            return _sasi_cache

        return _fetch_all_reports_locked(ahora)


def _fetch_all_reports_locked(ahora: datetime.datetime) -> list:
    """Descarga real de los reportes. Debe llamarse solo bajo _sasi_fetch_lock."""
    global _sasi_cache, _sasi_cache_ts, _sasi_last_ok

    ultimo_error = None

    for intento in range(SASI_MAX_RETRIES):
        sess = _get_sasi_session()
        try:
            r = sess.get(SASI_DATA_URL, timeout=SASI_DATA_TIMEOUT)
            print(f"  [SASI] GET getTblarepper.php -> HTTP {r.status_code} bytes={len(r.content)} (intento {intento + 1}/{SASI_MAX_RETRIES})")

            if r.status_code != 200 or "login.php" in r.url.lower():
                print("  [SASI] Sesion rechazada, renovando...")
                with _sasi_lock:
                    _sasi_last_ok = None
                ultimo_error = RuntimeError("SASI rechazo la sesion al pedir los reportes")
                time.sleep(SASI_RETRY_WAIT)
                continue

            text = r.text.strip()
            data = json.loads(text) if text else []

            if not isinstance(data, list):
                raise RuntimeError("SASI no devolvio una lista JSON de reportes")

            _sasi_cache = data
            _sasi_cache_ts = ahora
            print(f"  [SASI] Reportes obtenidos: {len(data)}")
            return data

        except json.JSONDecodeError as e:
            print(f"  [SASI] JSON invalido ({e}), renovando sesion...")
            with _sasi_lock:
                _sasi_last_ok = None
            ultimo_error = RuntimeError(f"SASI devolvio contenido no-JSON: {e}")
            time.sleep(SASI_RETRY_WAIT)
            continue
        except requests.exceptions.ReadTimeout as e:
            print(f"  [SASI] Timeout de lectura ({e}), reintentando en {SASI_RETRY_WAIT}s...")
            ultimo_error = RuntimeError(f"Timeout esperando respuesta de SASI: {e}")
            time.sleep(SASI_RETRY_WAIT)
            continue
        except requests.RequestException as e:
            print(f"  [SASI] Error de red ({e}), reintentando en {SASI_RETRY_WAIT}s...")
            ultimo_error = RuntimeError(f"Error de red conectando con SASI: {e}")
            time.sleep(SASI_RETRY_WAIT)
            continue

    # Todos los reintentos fallaron: si hay una cache previa (aunque expirada), usarla.
    if _sasi_cache is not None:
        print(f"  [SASI] ADVERTENCIA: no se pudo refrescar tras {SASI_MAX_RETRIES} intentos "
              f"({ultimo_error}). Sirviendo la ultima cache valida "
              f"({len(_sasi_cache)} reportes, obtenida a las {_sasi_cache_ts}).")
        return _sasi_cache

    if ultimo_error:
        raise ultimo_error
    return []


def _normalize_report(item: dict, tipo: str) -> dict:
    """Normaliza un reporte de SASI (formato getTblarepper.php) al formato del portal."""
    def _get(*keys):
        for k in keys:
            v = item.get(k)
            if v is not None and str(v).strip() and str(v).strip().lower() != "none":
                return str(v).strip()
        return ""

    return {
        "Tipo":          tipo,
        "Id":            _get("ReporteCJF"),
        "Titulo":        _get("Reporte_Proveedor", "Descripcion"),
        "Estado":        _get("Estatus"),
        "Prioridad":     "",
        "Clasificacion": _get("Adscripcion"),
        "FechaCreacion": _get("Fecha_registro"),
        "FechaModif":    _get("Fecha_solucion"),
        "Descripcion":   _get("Descripcion"),
        "Asignado":      _get("TurnadoA"),
        "UsuarioAfectado": _get("UsuarioAfectado"),
        "Proveedor":     _get("Proveedor"),
        "Expediente":    _get("Expediente"),
    }


def _norm_nombre(n: str) -> str:
    """Normaliza nombres para comparar sin acentos/mayúsculas (Arnulfo Correa Banuelos)."""
    import unicodedata
    n = (n or "").strip().lower()
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode("ascii")
    return " ".join(n.split())


# Mapa manual usuario AD (sAMAccountName) -> nombre completo como aparece en SASI.
# Si tu usuario no aparece aquí, añade la línea correspondiente.
SASI_NOMBRE_POR_USUARIO = {
    "acorreab": "arnulfo correa banuelos",
}


def get_reports(username: str) -> tuple[list, list]:
    """
    Consulta todos los reportes del usuario en SASI, filtrando por
    TurnadoA (asignado a) o UsuarioAfectado, usando el endpoint real
    descubierto: includes/tablas/getTblarepper.php.
    Devuelve (incidentes, solicitudes).
    """
    nombre_buscado = SASI_NOMBRE_POR_USUARIO.get(
        (username or "").strip().lower(),
        (username or "").strip().lower(),
    )
    nombre_buscado = _norm_nombre(nombre_buscado)

    try:
        data = _fetch_all_reports()
    except Exception as e:
        print(f"  [SASI] Error obteniendo reportes: {e}")
        return [], []

    incidentes = []
    solicitudes = []

    for item in data:
        if not isinstance(item, dict):
            continue
        turnado_a = _norm_nombre(item.get("TurnadoA") or "")
        afectado  = _norm_nombre(item.get("UsuarioAfectado") or "")

        if nombre_buscado and nombre_buscado not in (turnado_a, afectado):
            continue

        rep_id = str(item.get("ReporteCJF") or "")
        tipo = "Incidente" if rep_id.upper().startswith("INC") else "Solicitud"
        norm = _normalize_report(item, tipo)

        if tipo == "Incidente":
            incidentes.append(norm)
        else:
            solicitudes.append(norm)

    print(f"  [SASI] Incidentes={len(incidentes)} Solicitudes={len(solicitudes)} "
          f"(filtrado por '{nombre_buscado}')")
    return incidentes, solicitudes


def get_report_detail(report_id: str) -> dict | None:
    """Consulta el detalle de un reporte específico dentro de la lista completa cacheada."""
    try:
        data = _fetch_all_reports()
    except Exception as e:
        print(f"  [SASI] Error get_detail {report_id}: {e}")
        return None

    rid_norm = (report_id or "").strip().upper()
    for item in data:
        if not isinstance(item, dict):
            continue
        if str(item.get("ReporteCJF") or "").strip().upper() == rid_norm:
            tipo = "Incidente" if rid_norm.startswith("INC") else "Solicitud"
            norm = _normalize_report(item, tipo)
            norm["Actividades"] = []  # SASI no expone histórico de actividades en este endpoint
            return norm
    return None


def add_comment(report_id: str, texto: str, author: str) -> bool:
    """
    SASI (vía este endpoint) no expone una API de escritura de comentarios.
    Se deja como no-op informativo hasta tener el endpoint de escritura.
    """
    print(f"  [SASI] add_comment NO SOPORTADO por el endpoint actual "
          f"(id={report_id}, autor={author})")
    return False


def set_action(report_id: str, accion: str, author: str = "", texto: str = "") -> str:
    """
    SASI (vía este endpoint) no expone una API de escritura de estado.
    Se deja como no-op informativo hasta tener el endpoint de escritura.
    """
    print(f"  [SASI] set_action NO SOPORTADO por el endpoint actual "
          f"(accion={accion}, id={report_id}, autor={author})")
    estado = "Resuelto" if accion == "resolve" else "Cerrado"
    return estado


# ─── Sesiones del portal ───────────────────────────────────────────────────────
_sessions: dict = {}
_lock = threading.Lock()

def session_create(user: str, domain: str) -> str:
    token = secrets.token_hex(32)
    exp   = datetime.datetime.now() + datetime.timedelta(seconds=SESSION_TTL)
    with _lock:
        _sessions[token] = {
            "display":   f"{domain.upper()}\\{user}",
            "domain":    domain,
            "user":      user,
            "expires":   exp,
            "owned_ids": set(),
        }
    return token

def session_register_owned(token: str, ids):
    with _lock:
        s = _sessions.get(token)
        if s:
            for i in ids:
                ni = str(i or "").strip().upper()
                if ni:
                    s["owned_ids"].add(ni)

def session_owns(token: str, report_id: str) -> bool:
    with _lock:
        s = _sessions.get(token)
        return bool(s and str(report_id or "").strip().upper() in s["owned_ids"])

def session_get(token: str):
    if not token:
        return None
    with _lock:
        s = _sessions.get(token)
        if not s:
            return None
        if datetime.datetime.now() > s["expires"]:
            del _sessions[token]
            return None
        return s

def session_delete(token: str):
    with _lock:
        _sessions.pop(token, None)

# ─── Validación AD ────────────────────────────────────────────────────────────
def validate_user(user: str, password: str, domain: str) -> bool:
    from ldap3 import Server, Connection, ALL, NTLM
    lc  = _ldap_cfg(domain)
    srv = Server(lc["server"], port=lc["port"], get_info=ALL)
    conn = Connection(srv, user=f"{lc['domain']}\\{user}",
                      password=password, authentication=NTLM,
                      raise_exceptions=False)
    ok = conn.bind()
    if ok:
        conn.unbind()
    return bool(ok)

# ─── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    _MIME = {
        ".css":   "text/css; charset=utf-8",
        ".js":    "application/javascript; charset=utf-8",
        ".html":  "text/html; charset=utf-8",
        ".ico":   "image/x-icon",
        ".png":   "image/png",
        ".jpg":   "image/jpeg",
        ".svg":   "image/svg+xml",
        ".woff":  "font/woff",
        ".woff2": "font/woff2",
    }

    def _token(self):
        auth = self.headers.get("Authorization", "")
        return auth[7:] if auth.startswith("Bearer ") else None

    def _sess(self):
        return session_get(self._token())

    def _need_sess(self):
        s = self._sess()
        if not s:
            self._json(401, {"ok": False, "error": "No autenticado"})
        return s

    def _authorize(self, report_id: str) -> bool:
        token = self._token()
        if session_owns(token, report_id):
            return True
        sess = self._sess()
        if not sess:
            self._json(401, {"ok": False, "error": "No autenticado"})
            return False
        # Recarga los reportes para verificar propiedad
        try:
            inc, sol = get_reports(sess["user"])
            session_register_owned(token, (r["Id"] for r in inc))
            session_register_owned(token, (r["Id"] for r in sol))
        except Exception:
            pass
        if session_owns(token, report_id):
            return True
        self._json(403, {"ok": False, "error": "No autorizado"})
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/scsm", "/scsm/"):
            return self._send_file(INDEX_HTML, "text/html; charset=utf-8")
        if path == "/static/css/styles.css":
            return self._send_file(CSS_FILE, self._MIME[".css"])
        if path == "/static/js/app.js":
            return self._send_file(JS_FILE, self._MIME[".js"])
        for prefix in ("/scsm/static/", "/static/"):
            if path.startswith(prefix):
                rel  = path[len(prefix):]
                full = os.path.normpath(os.path.join(STATIC_DIR, rel))
                if not full.startswith(os.path.normpath(STATIC_DIR)):
                    return self.send_error(403)
                if not os.path.isfile(full):
                    return self.send_error(404)
                ext = os.path.splitext(full)[1].lower()
                return self._send_file(full, self._MIME.get(ext, "application/octet-stream"))
        if path == "/api/session":
            s = self._sess()
            if s:
                return self._json(200, {"ok": True, "display": s["display"], "user": s["user"]})
            return self._json(401, {"ok": False})
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        # ── Login ──────────────────────────────────────────────────────────────
        if path == "/api/login":
            body     = self._rjson()
            user     = (body.get("user") or "").strip()
            password = body.get("password") or ""
            if "\\" in user:
                dominio, user = user.split("\\", 1)
            else:
                dominio = (body.get("dominio") or "cjf").strip()
            dominio = dominio.lower()
            user    = user.strip()
            if not user or not password:
                return self._json(400, {"ok": False, "error": "Usuario y contraseña requeridos"})
            try:
                if validate_user(user, password, dominio):
                    token = session_create(user, dominio)
                    return self._json(200, {
                        "ok": True, "token": token,
                        "display": f"{dominio.upper()}\\{user}", "user": user,
                    })
                return self._json(401, {"ok": False, "error": "Credenciales incorrectas"})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        # ── Logout ─────────────────────────────────────────────────────────────
        if path == "/api/logout":
            t = self._token()
            if t:
                session_delete(t)
            return self._json(200, {"ok": True})

        # ── Incidentes ─────────────────────────────────────────────────────────
        if path == "/api/scsm/incidentes":
            sess = self._need_sess()
            if not sess:
                return
            try:
                inc, _ = get_reports(sess["user"])
                session_register_owned(self._token(), (r["Id"] for r in inc))
                return self._json(200, {"ok": True, "incidentes": inc})
            except Exception as e:
                print(f"  [ERROR] {traceback.format_exc()}")
                return self._json(500, {"ok": False, "error": str(e)})

        # ── Solicitudes ────────────────────────────────────────────────────────
        if path == "/api/scsm/solicitudes":
            sess = self._need_sess()
            if not sess:
                return
            try:
                _, sol = get_reports(sess["user"])
                session_register_owned(self._token(), (r["Id"] for r in sol))
                return self._json(200, {"ok": True, "solicitudes": sol})
            except Exception as e:
                print(f"  [ERROR] {traceback.format_exc()}")
                return self._json(500, {"ok": False, "error": str(e)})

        # ── Detalle ────────────────────────────────────────────────────────────
        if path == "/api/scsm/reporte":
            sess = self._need_sess()
            if not sess:
                return
            rid = (self._rjson().get("id") or "").strip()
            if not rid:
                return self._json(400, {"ok": False, "error": "id requerido"})
            if not self._authorize(rid):
                return
            try:
                rep = get_report_detail(rid)
                if not rep:
                    return self._json(404, {"ok": False, "error": "Reporte no encontrado"})
                return self._json(200, {"ok": True, "reporte": rep})
            except Exception as e:
                print(f"  [ERROR] {traceback.format_exc()}")
                return self._json(500, {"ok": False, "error": str(e)})

        # ── Comentar ───────────────────────────────────────────────────────────
        if path == "/api/scsm/comentar":
            sess = self._need_sess()
            if not sess:
                return
            body  = self._rjson()
            rid   = (body.get("id")    or "").strip()
            texto = (body.get("texto") or "").strip()
            if not rid or not texto:
                return self._json(400, {"ok": False, "error": "id y texto requeridos"})
            if not self._authorize(rid):
                return
            try:
                add_comment(rid, texto, sess["display"])
                return self._json(200, {"ok": True})
            except Exception as e:
                print(f"  [ERROR] {traceback.format_exc()}")
                return self._json(500, {"ok": False, "error": str(e)})

        # ── Acción individual ──────────────────────────────────────────────────
        if path == "/api/scsm/accion":
            sess = self._need_sess()
            if not sess:
                return
            body   = self._rjson()
            rid    = (body.get("id")     or "").strip()
            accion = (body.get("accion") or "").strip()
            texto  = (body.get("texto")  or "").strip()
            if not rid or not accion:
                return self._json(400, {"ok": False, "error": "id y accion requeridos"})
            if not self._authorize(rid):
                return
            try:
                estado = set_action(rid, accion, sess["display"], texto)
                return self._json(200, {"ok": True, "estado": estado})
            except Exception as e:
                print(f"  [ERROR] {traceback.format_exc()}")
                return self._json(500, {"ok": False, "error": str(e)})

        # ── Acción masiva ──────────────────────────────────────────────────────
        if path == "/api/scsm/accion-masiva":
            sess = self._need_sess()
            if not sess:
                return
            body   = self._rjson()
            ids    = body.get("ids")    or []
            accion = (body.get("accion") or "").strip()
            texto  = (body.get("texto")  or "").strip()
            if not ids or not accion:
                return self._json(400, {"ok": False, "error": "ids y accion requeridos"})
            token      = self._token()
            resultados = []
            for rid in ids:
                if not session_owns(token, rid):
                    resultados.append({"id": rid, "ok": False, "error": "No autorizado"})
                    continue
                try:
                    if accion.lower() == "comentar":
                        if texto:
                            add_comment(rid, texto, sess["display"])
                    else:
                        set_action(rid, accion, sess["display"], texto)
                    resultados.append({"id": rid, "ok": True})
                except Exception as e:
                    resultados.append({"id": rid, "ok": False, "error": str(e)})
            procesados = sum(1 for r in resultados if r["ok"])
            return self._json(200, {"ok": True, "procesados": procesados, "resultados": resultados})

        self.send_error(404)

    def _rjson(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type",   "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # El navegador ya cerro la conexion (recarga, timeout del cliente, etc.)
            # No es un error real del servidor, solo lo registramos sin traceback.
            print("  [HTTP] Conexion cerrada por el cliente antes de recibir la respuesta.")

    def _send_file(self, full_path, mime):
        if not os.path.isfile(full_path):
            return self.send_error(404, "Archivo no encontrado")
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type",   mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"  [HTTP] {fmt % args}")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads      = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Silenciar tracebacks ruidosos cuando el navegador cierra la conexion
        # (recargas, timeouts del cliente) en vez de imprimir un stack completo.
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            print(f"  [HTTP] Conexion cerrada por el cliente {client_address}.")
        else:
            super().handle_error(request, client_address)


def main():
    dominios = ", ".join(
        f"{d} -> {cfg.get(s, 'server')}:{cfg.getint(s, 'port', fallback=389)}"
        for d, s in LDAP_SECTIONS.items()
        if cfg.has_section(s)
    ) or "(ninguno configurado)"

    with ThreadingHTTPServer(("", PORT), Handler) as httpd:
        print(f"\n  Portal SCSM  ->  http://localhost:{PORT}/")
        print(f"  SASI Login   :   {SASI_LOGIN_URL}")
        print(f"  SASI sm.php  :   {SASI_SM_URL}")
        print(f"  SASI Usuario :   {SASI_USER or '(no configurado)'}")
        print(f"  Dominios AD  :   {dominios}")
        print("  Ctrl+C para detener\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Servidor detenido.")


if __name__ == "__main__":
    main()
