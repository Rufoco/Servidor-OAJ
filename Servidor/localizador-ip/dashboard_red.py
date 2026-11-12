# -*- coding: utf-8 -*-
"""Localizador IP -> Switch/Puerto (una o varias IPs). Consume el Dashboard de Red."""
import os, re, json, time, threading, configparser
from urllib.parse import urlparse, parse_qs
import requests

DIR = os.path.dirname(os.path.abspath(__file__))
PREFIX = "/localizador-ip"
TTL = 300              # segundos de cache para resultados buenos
MAX_INTENTOS = 3       # intentos por escaneo cuando el dashboard reporta fallos de conexion
ESPERA = 6             # segundos entre intentos
MAX_IPS = 2000           # maximo de IPs por busqueda
MAC_RE = re.compile(r"(?:[0-9a-f]{2}[:\-]){5}[0-9a-f]{2}|(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}|[0-9a-f]{12}", re.I)
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

_cfg = configparser.ConfigParser()
for _p in (os.path.join(DIR, "config.ini"),
           os.path.join(os.path.dirname(DIR), "migracion-cjf", "config.ini")):
    if os.path.exists(_p):
        _cfg.read(_p, encoding="utf-8-sig")
_sec = _cfg["dashboard_red"] if _cfg.has_section("dashboard_red") else {}
BASE = (os.environ.get("DASH_BASE") or _sec.get("base", "http://10.1.150.154:5000")).rstrip("/")
USER = os.environ.get("DASH_USER") or _sec.get("usuario", "")
PWD = os.environ.get("DASH_PASS") or _sec.get("password", "")
if PWD and not os.environ.get("DASH_PASS"):
    print(" [Localizador IP] AVISO: la contrasena del Dashboard de Red esta en config.ini; usa la variable de entorno DASH_PASS.")

_s = requests.Session()
_login_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()
_key_locks = {}
_scan_gate = threading.Semaphore(1)   # un solo escaneo SSH a la vez (evita saturar las VTY del CORE)


def _login():
    r = _s.post(BASE + "/login_valida", data={"usuario": USER, "password": PWD}, timeout=20)
    if "/login" in r.url:
        raise RuntimeError("Login fallido en el Dashboard de Red (revisa config.ini)")


def _req(method, path, **kw):
    kw.setdefault("timeout", 300)
    r = _s.request(method, BASE + path, **kw)
    if "/login" in r.url or r.status_code in (401, 403):
        with _login_lock:
            _login()
        r = _s.request(method, BASE + path, **kw)
        if "/login" in r.url:
            raise RuntimeError("Sesion no valida en el Dashboard de Red")
    r.raise_for_status()
    return r


def _post_json(path, body):
    return _req("POST", path, json=body).json()


def _post_scan(path, body):
    with _scan_gate:
        return _post_json(path, body)


def _cached(key, fn, force=False):
    with _cache_lock:
        kl = _key_locks.setdefault(key, threading.Lock())
    with kl:
        t = _cache.get(key)
        if t and not force and time.time() - t[0] < TTL:
            return t[1], t[0]
        d = fn()
        _cache[key] = (time.time(), d)
        return d, _cache[key][0]


def _escaneo(key, fn, force, tiene_datos):
    """Escaneo con reintentos. Un resultado con errores y sin datos NO se deja en cache."""
    intento = 0
    while True:
        intento += 1
        d, ts = _cached(key, fn, force or intento > 1)
        if tiene_datos(d) or not (d.get("errores") or []):
            return d, ts, intento
        if intento >= MAX_INTENTOS:
            _cache.pop(key, None)
            return d, ts, intento
        time.sleep(ESPERA)


def _norm_mac(v):
    return re.sub(r"[^0-9a-f]", "", str(v).lower())


def _vals(row):
    return [str(v).strip() for v in row.values() if v is not None]


def _key(row, *cands):
    for k, v in row.items():
        if any(c in k.lower() for c in cands) and v not in (None, ""):
            return str(v)
    return ""


def _payload_sw(sw):
    return {k: sw.get(k, "") for k in ("ip", "hostname", "modelo", "serie", "fabricante")}


def _dump(name, data):
    if os.environ.get("DASH_DEBUG") != "1":
        return
    try:
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))
        os.makedirs(os.path.join(DIR, "raw"), exist_ok=True)
        with open(os.path.join(DIR, "raw", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


_refrescos = {}
_refrescos_lock = threading.Lock()
REFRESCO_MIN = 60   # segundos minimos entre refrescos forzados de la misma consulta


def refresco_permitido(clave, segundos=REFRESCO_MIN):
    ahora = time.time()
    with _refrescos_lock:
        if ahora - _refrescos.get(clave, 0) < segundos:
            return False
        _refrescos[clave] = ahora
        return True


def sitios():
    def load():
        html = _req("GET", "/tabla_arp").text
        m = re.search(r"listaSitiosBD\s*=\s*(\[.*?\])\s*;", html, re.S)
        return json.loads(m.group(1)) if m else []
    return _cached("sitios", load)[0]


def parsear_ips(texto):
    """Devuelve (ips_validas_sin_duplicar, invalidas)."""
    validas, invalidas, vistas = [], [], set()
    for tok in re.split(r"[\s,;]+", texto or ""):
        tok = tok.strip()
        if not tok:
            continue
        if IP_RE.match(tok) and all(0 <= int(o) <= 255 for o in tok.split(".")):
            if tok not in vistas:
                vistas.add(tok)
                validas.append(tok)
        else:
            invalidas.append(tok)
    return validas, invalidas


def buscar_varias(ips_texto, sitio_in, force=False):
    if len(ips_texto or "") > 100000:
        return {"ok": False, "msg": "Texto demasiado largo"}
    ips, invalidas = parsear_ips(ips_texto)
    if not ips:
        return {"ok": False, "msg": "No se encontro ninguna IP valida en lo que escribiste", "invalidas": invalidas}
    if len(ips) > MAX_IPS:
        return {"ok": False, "msg": "Maximo %d IPs por busqueda (escribiste %d)" % (MAX_IPS, len(ips))}
    v = str(sitio_in).strip().lower()
    sitio = next((x for x in sitios()
                  if str(x.get("id")).strip().lower() == v or str(x.get("prisma_id")).strip().lower() == v), None)
    if not sitio:
        return {"ok": False, "msg": "Sitio '%s' no encontrado en el catalogo" % sitio_in}
    sid = sitio["id"]
    avisos = []

    sws, _ = _cached("sw_%s" % sid, lambda: _post_json("/obtener_switches_vlan", {"ids_sitios": [sid]}), force)
    _dump("switches_%s" % sid, sws)
    if not sws:
        return {"ok": False, "msg": "El sitio no tiene switches en el catalogo", "sitio": sitio}
    cores = [x for x in sws if "CORE" in str(x.get("hostname", "")).upper()]
    acceso = [x for x in sws if x not in cores] or sws

    errores, edad_arp, intentos_arp, arp_rows = [], None, 0, []
    if cores:
        arp, edad_arp, intentos_arp = _escaneo(
            "arp_%s" % sid,
            lambda: _post_scan("/escanear_tabla_arp_ajax",
                               {"switches": [_payload_sw(c) for c in cores], "id_sitio": sid}),
            force, lambda d: bool(d.get("arp")))
        _dump("arp_%s" % sid, arp)
        errores += arp.get("errores", []) or []
        arp_rows = arp.get("arp", []) or []
        if not arp_rows and errores:
            avisos.append("El CORE no respondio tras %d intento(s); no se pudo leer su ARP." % intentos_arp)
    else:
        avisos.append("El sitio no tiene CORE en el catalogo; se busco solo por IP en la tabla de puertos.")

    pd, edad_pt, intentos_pt = _escaneo(
        "puertos_%s" % sid,
        lambda: _post_scan("/escanear_estatus_puertos_ajax",
                           {"switches": [_payload_sw(x) for x in acceso], "id_sitio": sid}),
        force, lambda d: bool(d.get("puertos")))
    _dump("puertos_%s" % sid, pd)
    errores += pd.get("errores", []) or []
    puertos = pd.get("puertos", []) or []

    if not arp_rows and not puertos and errores:
        return {"ok": False, "sitio": sitio, "errores": errores,
                "msg": "No se pudo consultar los switches del sitio (se reintento automaticamente). "
                       "Vuelve a intentar en un minuto o revisa los errores de abajo."}

    arp_por_ip, port_por_ip, port_por_mac, cuenta = {}, {}, {}, {}
    for r in arp_rows:
        for x in _vals(r):
            if IP_RE.match(x):
                arp_por_ip.setdefault(x, []).append(r)
    for p in puertos:
        k = (_key(p, "host"), _key(p, "puerto", "interfaz", "port"))
        cuenta[k] = cuenta.get(k, 0) + 1
        for x in _vals(p):
            if IP_RE.match(x):
                port_por_ip.setdefault(x, []).append(p)
            elif MAC_RE.fullmatch(x):
                port_por_mac.setdefault(_norm_mac(x), []).append(p)

    resultados = []
    for ip in ips:
        filas = arp_por_ip.get(ip, [])
        macs = {_norm_mac(x) for r in filas for x in _vals(r) if MAC_RE.fullmatch(x)}
        vistos, hits = set(), []
        candidatos = [(p, True) for p in port_por_ip.get(ip, [])]
        for m in macs:
            candidatos += [(p, False) for p in port_por_mac.get(m, [])]
        for p, por_ip in candidatos:
            if id(p) in vistos:
                continue
            vistos.add(id(p))
            vs = _vals(p)
            ip_ok = ip in vs
            mac_ok = any(MAC_RE.fullmatch(x) and _norm_mac(x) in macs for x in vs)
            k = (_key(p, "host"), _key(p, "puerto", "interfaz", "port"))
            hits.append({"puerto": p, "macs_en_puerto": cuenta.get(k, 1),
                         "coincide": "IP+MAC" if ip_ok and mac_ok else "IP" if ip_ok else "MAC"})
        hits.sort(key=lambda h: h["macs_en_puerto"])
        av = []
        if filas and not hits:
            av.append("Esta en el ARP pero su MAC no aparece en los puertos del sitio.")
        elif not filas and hits:
            av.append("No esta en el ARP del CORE; se ubico solo por IP en la tabla de puertos.")
        resultados.append({"ip": ip, "encontrada": bool(filas or hits), "macs": sorted(macs),
                           "arp": filas, "ubicaciones": hits, "avisos": av})

    return {"ok": True, "sitio": sitio, "resultados": resultados, "invalidas": invalidas,
            "avisos": avisos, "errores": errores,
            "total_switches": len(sws), "total_puertos": len(puertos), "total_arp": len(arp_rows),
            "intentos": {"arp": intentos_arp, "puertos": intentos_pt},
            "edad_arp": edad_arp, "edad_puertos": edad_pt, "ahora": time.time()}


def _json(h, code, obj):
    b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(b)))
    h.end_headers()
    h.wfile.write(b)


def manejar(h):
    """Devuelve True si la ruta fue atendida por este modulo (solo GET)."""
    u = urlparse(h.path)
    path = u.path
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return False
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if path == PREFIX:
        h.send_response(301)
        h.send_header("Location", PREFIX + "/")
        h.end_headers()
        return True
    try:
        if path == PREFIX + "/":
            with open(os.path.join(DIR, "index.html"), "rb") as fh:
                b = fh.read()
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(b)))
            h.end_headers()
            h.wfile.write(b)
        elif path == PREFIX + "/api/sitios":
            _json(h, 200, sitios())
        elif path == PREFIX + "/api/buscar":
            ips = (q.get("ips") or q.get("ip") or "").strip()
            sitio = q.get("sitio", "").strip()
            if not ips or not sitio:
                _json(h, 400, {"ok": False, "msg": "Falta la IP o el sitio"})
            else:
                _json(h, 200, buscar_varias(ips, sitio, force=(q.get("refrescar") == "1" and refresco_permitido("buscar:" + sitio))))
        else:
            _json(h, 404, {"ok": False, "msg": "Ruta no encontrada"})
    except Exception as e:
        print(" [Localizador IP] Error: %r" % (e,))
        _json(h, 500, {"ok": False, "msg": "No se pudo completar la consulta. Revisa el log del servidor."})
    return True
