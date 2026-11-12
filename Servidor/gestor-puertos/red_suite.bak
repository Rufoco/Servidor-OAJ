# -*- coding: utf-8 -*-
"""Suite Herramientas de Red - Gestor de Puertos (v4).
Reutiliza la sesion, el catalogo y la cache de dashboard_red.py (Localizador IP).
v4: integra el modulo "Puertos Libres" del dashboard (Ultimo Input y uptime del switch)."""
import os, re, sys, json, time, hashlib, threading, unicodedata
from collections import Counter
from urllib.parse import urlparse, parse_qs

DIR = os.path.dirname(os.path.abspath(__file__))
PREFIX = "/herramientas-red"
DIAS_LIBRE = 30                      # dias sin trafico/enlace para marcar "libre probable"
GENERICA_MIN = 3                     # una descripcion repetida en >= N puertos se considera etiqueta generica
HIST_FILE = os.path.join(DIR, "historial_puertos.json")
_hlock = threading.Lock()
VACIOS = {"-", "--", "\u2014", "n/a", "na", "none", "null", "s/d"}
MAC_RE = re.compile(r"(?:[0-9a-f]{2}[:\-]){5}[0-9a-f]{2}|(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}", re.I)
_T_CLAVES = ("inactiv", "desconex", "sinenlace", "sinuso", "lastinput", "ultimoinput", "lastoutput",
             "linkflap", "lastchange", "ultimocambio", "ultimaactividad", "idle", "downtime", "tiempo")
_UP = {"year": 31536000, "week": 604800, "day": 86400, "hour": 3600, "minute": 60, "second": 1}
_EP = {"ruta": None}

_LOC = os.path.join(os.path.dirname(DIR), "localizador-ip")
if _LOC not in sys.path:
    sys.path.insert(0, _LOC)
try:
    import dashboard_red as dr
    _ERR = ""
except Exception as _e:
    dr = None
    _ERR = str(_e)


def _nk(k):
    s = unicodedata.normalize("NFKD", str(k).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s)


def _vacio(v):
    return v is None or str(v).strip() == "" or str(v).strip().lower() in VACIOS


def _pick(row, *subs):
    for k, v in row.items():
        if any(s in _nk(k) for s in subs) and not _vacio(v):
            return str(v).strip()
    return ""


def _exact(row, nombre):
    for k, v in row.items():
        if _nk(k) == nombre and not _vacio(v):
            return str(v).strip()
    return ""


def _lista(v):
    return [x for x in re.split(r"[,;\s]+", str(v or "")) if x and x.lower() not in VACIOS]


def _tiempo(p):
    for k, v in p.items():
        if any(s in _nk(k) for s in _T_CLAVES) and not _vacio(v):
            return str(k), str(v).strip()
    return "", ""


def _dur(t):
    """Duracion estilo Cisco ('3d04h', '1w2d', '00:05:12', 'never') -> segundos, 'never' o None."""
    s = str(t).strip().lower()
    if s in ("never", "nunca"):
        return "never"
    m = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    if re.fullmatch(r"(?:\d+\s*[ywdhms]\s*)+", s):
        mult = {"y": 31536000, "w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
        return sum(int(n) * mult[u] for n, u in re.findall(r"(\d+)\s*([ywdhms])", s))
    return None


def _uptime_seg(t):
    """'9 weeks, 3 days, 22 hours, 23 minutes' / '56 days 20 hours 50 minutes and 54 seconds,' -> segundos."""
    xs = re.findall(r"(\d+)\s*(year|week|day|hour|minute|second)", str(t).lower())
    return sum(int(n) * _UP[u] for n, u in xs) if xs else None


def _fmt(seg):
    seg = int(seg)
    d, r = divmod(seg, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return "%d d %d h" % (d, h)
    if h:
        return "%d h %d min" % (h, m)
    return "%d min" % m


def _marca_inf(modelo):
    m = str(modelo or "").upper().replace(" ", "")
    if re.match(r"^(WS-?C|C9\d|N\d{1,2}K|CBS)", m):
        return "Cisco"
    if re.match(r"^OS\d", m) or "ALCATEL" in m:
        return "Alcatel-Lucent"
    return ""


def _pkey(p):
    s = re.sub(r"\(.*", "", str(p).lower())
    for a, b in (("tengigabitethernet", "te"), ("gigabitethernet", "gi"), ("fastethernet", "fa"), ("port", "")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9/]", "", s)


def _estado(txt):
    s = re.sub(r"[^a-z]", "", str(txt).lower())
    if not s:
        return "otro"
    if "err" in s:
        return "error"
    if "disab" in s or "admin" in s or "shut" in s:
        return "deshabilitado"
    if "notconn" in s or s in ("down", "nolink"):
        return "sin_enlace"
    if "connect" in s or s in ("up", "linkup"):
        return "activo"
    return "otro"


def _fila(p):
    tk, tv = _tiempo(p)
    return {
        "switch": _pick(p, "hostname") or _pick(p, "equipo"),
        "ip_sw": _pick(p, "ipdelsw", "ipsw", "ipswitch") or _exact(p, "ip"),
        "puerto": _pick(p, "puerto", "interfaz", "port"),
        "modo": _pick(p, "modo"),
        "descripcion": _pick(p, "descrip"),
        "estatus": _pick(p, "estatus", "estado", "status"),
        "vlan": _pick(p, "vlan"),
        "duplex": _pick(p, "duplex"),
        "speed": _pick(p, "speed", "velocidad"),
        "tipo": _pick(p, "tipo"),
        "mac": " ".join(str(v) for k, v in p.items() if "mac" in _nk(k) or _nk(k) == "traffic"),
        "ip_host": _pick(p, "ipdelhost", "hostconectado", "iphost"),
        "serie_row": _pick(p, "serie"),
        "modelo_row": _pick(p, "modelo"),
        "marca_row": _pick(p, "fabricante", "marca"),
        "t_key": tk, "t_val": tv,
    }


def _tiempo_campos(g):
    d = _dur(g["t_val"]) if g["t_val"] else None
    g["t_nunca"] = d == "never"
    g["t_seg"] = d if isinstance(d, int) else None


def consolidar(rows):
    """Una fila por (switch, puerto); MAC/IP de host adicionales se acumulan."""
    por, orden = {}, []
    for i, p in enumerate(rows or []):
        if not isinstance(p, dict):
            continue
        f = _fila(p)
        k = (f["switch"], f["puerto"] or "#%d" % i)
        if k not in por:
            f["macs"], f["ips_host"] = [], []
            f["crudo"] = {str(a): ("" if b is None else str(b)) for a, b in p.items()}
            por[k] = f
            orden.append(k)
        g = por[k]
        for m in MAC_RE.findall(f["mac"]):
            m = m.lower()
            if m not in g["macs"]:
                g["macs"].append(m)
        for ip in _lista(f["ip_host"]):
            if ip not in g["ips_host"]:
                g["ips_host"].append(ip)
        for c in ("ip_sw", "modo", "descripcion", "estatus", "vlan", "duplex", "speed", "tipo",
                  "serie_row", "modelo_row", "marca_row", "t_key", "t_val"):
            if not g[c] and f[c]:
                g[c] = f[c]
    out = []
    for k in orden:
        g = por[k]
        g["n_macs"] = len(g["macs"])
        g["mac"] = g["macs"][0] if g["macs"] else ""
        g["estado"] = _estado(g["estatus"])
        g["troncal"] = ("trunk" in g["modo"].lower() or "uplink" in g["tipo"].lower()
                        or g["n_macs"] > 3 or len(g["ips_host"]) > 3)
        _tiempo_campos(g)
        g["t_uptime_seg"], g["uptime"] = None, ""
        g["l_ok"], g["l_en_lista"] = False, False
        out.append(g)
    return out


def _hist_actualizar(sid, ts, filas):
    """Guarda la primera vez que esta herramienta vio cada puerto en su estado actual."""
    out = {}
    try:
        with _hlock:
            try:
                with open(HIST_FILE, encoding="utf-8") as fh:
                    h = json.load(fh)
            except Exception:
                h = {}
            s = h.setdefault(str(sid), {})
            cambio = False
            for f in filas:
                k = f["switch"] + "|" + f["puerto"]
                e = s.get(k)
                if e is None:
                    e = {"estado": f["estado"], "desde": ts, "n": 1, "primera": True,
                         "activo": ts if f["estado"] == "activo" else None, "vts": ts}
                    s[k] = e
                    cambio = True
                elif ts > e.get("vts", 0):
                    if e.get("estado") != f["estado"]:
                        e.update({"estado": f["estado"], "desde": ts, "n": 1, "primera": False})
                    else:
                        e["n"] = e.get("n", 1) + 1
                    if f["estado"] == "activo":
                        e["activo"] = ts
                    e["vts"] = ts
                    cambio = True
                out[k] = dict(e)
            if cambio:
                tmp = HIST_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(h, fh, ensure_ascii=False)
                os.replace(tmp, HIST_FILE)
    except Exception:
        pass
    return out


def _disp(f,h,ahora):
    if f.get('l_en_lista'):
        return 'libre_probable','Reportado por el dashboard en Puertos Libres. Descripcion y antiguedad no intervienen.'
    if f['estado']=='activo': return 'ocupado','Enlace activo segun Estatus de Puertos.'
    if f['estado']=='deshabilitado': return 'deshabilitado','Estado disabled; no implica autorizacion para habilitarlo.'
    if f['estado']=='error': return 'error','El puerto reporta un error.'
    return 'por_confirmar',('No listado por el dashboard; las consultas son capturas distintas.' if f.get('l_ok') else 'Consulta de Puertos Libres no disponible o no solicitada.')


def _sitio(valor):
    v = str(valor).strip().lower()
    return next((x for x in dr.sitios()
                 if str(x.get("id")).strip().lower() == v or str(x.get("prisma_id")).strip().lower() == v), None)


def _switches(sid, force=False):
    sws, ts = dr._cached("sw_%s" % sid,
                         lambda: dr._post_json("/obtener_switches_vlan", {"ids_sitios": [sid]}), force)
    return sws or [], ts


def _es_core(sw):
    return "CORE" in str(sw.get("hostname", "")).upper()


def _s(x, k):
    v = x.get(k, "")
    return "" if _vacio(v) else str(v).strip()


def _marca(x):
    m = _s(x, "fabricante")
    return (m, False) if m else (_marca_inf(_s(x, "modelo")), True)


# ---------- Puertos Libres (Ultimo Input / uptime) ----------
def _libres_ruta():
    if _EP["ruta"]:
        return _EP["ruta"]
    ruta, ok = "/escanear_puertos_libres_ajax", False
    try:
        html = dr._req("GET", "/puertos_libres").text
        js = " ".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I))
        ok = True
        for m in re.finditer(r"""['"`](/[A-Za-z0-9_\-/]*(?:ajax|escanear)[A-Za-z0-9_\-/]*)['"`]""", js):
            if "libres" in m.group(1).lower():
                ruta = m.group(1)
                break
    except Exception:
        pass
    if ok:
        _EP["ruta"] = ruta
    return ruta


def _norm_resp(d):
    return {"filas": d, "errores": []} if isinstance(d, list) else d


def _filas_libres(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    if isinstance(d, dict):
        for k in ("puertos", "libres", "resultados", "datos", "data", "rows", "filas"):
            v = d.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in d.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def _libres_info(sid, sel, force):
    nombres=sorted(str(x.get('hostname','')).strip() for x in sel)
    if not all(nombres):
        return {'ok':False,'msg':'Falta hostname en el catalogo.'}
    key='libres_reales_'+str(sid)+'_'+hashlib.sha256(json.dumps(nombres).encode()).hexdigest()[:16]
    try:
        def cargar():
            d=dr._post_scan('/escanear_puertos_procesa',{'dispositivos':nombres,'id_sitio':sid})
            if not isinstance(d,list):
                raise ValueError('Puertos Libres no devolvio la lista esperada; no se clasificaron ausencias.')
            if any(not isinstance(r,dict) or not r.get('puerto') or not (r.get('hostname') or r.get('ip')) for r in d):
                raise ValueError('Respuesta de Puertos Libres con formato inesperado.')
            return {'filas':d}
        data,ts=dr._cached(key,cargar,force)
    except Exception as exc:
        return {'ok':False,'msg':'No se pudo consultar Puertos Libres: '+str(exc)}
    hh,ii,uh,ui={},{},{},{}
    for j,r in enumerate(data['filas']):
        host=str(r.get('hostname') or r.get('equipo') or '').strip().lower()
        ip=str(r.get('ip') or '').strip(); pk=_pkey(r['puerto'])
        e={'id':j,'ultimo':r.get('ultimo_input'),'output':r.get('ultimo_output'),
           'uptime':r.get('uptime') or '', 'serie':r.get('serie') or '', 'crudo':dict(r)}
        hh[(host,pk)]=e
        if ip: ii[(ip,pk)]=e
        if e['uptime']:
            uh[host]=e['uptime']
            if ip: ui[ip]=e['uptime']
    return {'ok':True,'h':hh,'i':ii,'up_h':uh,'up_i':ui,'n':len(data['filas']),'n_ent':len(data['filas'])}


def api_switches(sitio_in, force=False):
    sitio = _sitio(sitio_in)
    if not sitio:
        return {"ok": False, "msg": "Sitio '%s' no encontrado en el catalogo" % sitio_in}
    sws, _ = _switches(sitio["id"], force)
    lista = []
    for x in sws:
        m, inf = _marca(x)
        lista.append({"hostname": _s(x, "hostname"), "ip": _s(x, "ip"), "modelo": _s(x, "modelo"),
                      "marca": m + (" (inferida)" if m and inf else ""), "serie": _s(x, "serie"),
                      "core": _es_core(x)})
    return {"ok": True, "sitio": sitio, "switches": lista}


def _nuevo_resumen(hostname, ip, core, marca="", modelo="", serie=""):
    return {"hostname": hostname, "ip": ip, "core": core, "marca": marca, "modelo": modelo, "serie": serie,
            "uptime": "", "total": 0, "activo": 0, "sin_enlace": 0, "deshabilitado": 0, "error": 0, "otro": 0,
            "libres": 0, "confirmar": 0, "asignados": 0}


def _t_textos(f):
    # Solo datos originales. Sin historial ni deducciones desde uptime.
    v=f.get('ultimo_input_original')
    return (str(v) if v is not None and str(v).strip() else 'No informado por el dashboard','Valor original de ultimo_input; no es la fecha de consulta ni una medicion exacta de caida de enlace.')


def api_puertos(sitio_in, ips_sel, force=False, libres=False):
    sitio = _sitio(sitio_in)
    if not sitio:
        return {"ok": False, "msg": "Sitio '%s' no encontrado en el catalogo" % sitio_in}
    sid = sitio["id"]
    sws, _ = _switches(sid, force)
    if not sws:
        return {"ok": False, "sitio": sitio, "msg": "El sitio no tiene switches en el catalogo"}
    acceso = [x for x in sws if not _es_core(x)] or sws
    sel = [x for x in sws if str(x.get("ip", "")) in ips_sel] if ips_sel else acceso
    if not sel:
        return {"ok": False, "sitio": sitio, "msg": "Ninguno de los switches elegidos pertenece al sitio"}
    ips_s = sorted(str(x.get("ip", "")) for x in sel)
    if ips_s == sorted(str(x.get("ip", "")) for x in acceso):
        key = "puertos_%s" % sid  # misma cache que usa el Localizador IP
    else:
        key = "puertos_%s_%s" % (sid, hashlib.md5(",".join(ips_s).encode()).hexdigest()[:10])
    pd, ts, intentos = dr._escaneo(
        key,
        lambda: dr._post_scan("/escanear_estatus_puertos_ajax",
                              {"switches": [dr._payload_sw(x) for x in sel], "id_sitio": sid}),
        force, lambda d: bool(d.get("puertos")))
    errores = pd.get("errores", []) or []
    filas = consolidar(pd.get("puertos", []) or [])
    if not filas:
        return {"ok": False, "sitio": sitio, "errores": errores,
                "msg": "El dashboard no devolvio puertos para los switches elegidos "
                       "(se reintento %d vez/veces). Revisa los errores o intenta en un minuto." % intentos}
    resumen = {}
    for x in sel:
        m, inf = _marca(x)
        resumen[_s(x, "hostname").lower()] = _nuevo_resumen(
            _s(x, "hostname"), _s(x, "ip"), _es_core(x), m + (" (inferida)" if m and inf else ""),
            _s(x, "modelo"), _s(x, "serie"))
    por_ip = {r["ip"]: r for r in resumen.values() if r["ip"]}
    extra = 0
    for f in filas:
        r = resumen.get(f["switch"].lower()) or por_ip.get(f["ip_sw"])
        if r is None:
            extra += 1
            r = resumen.setdefault(f["switch"].lower(), _nuevo_resumen(f["switch"], f["ip_sw"], False))
        f["switch"] = r["hostname"] or f["switch"]
        r["marca"] = r["marca"] or f["marca_row"] or ((_marca_inf(r["modelo"] or f["modelo_row"]) + " (inferida)")
                                                      if _marca_inf(r["modelo"] or f["modelo_row"]) else "")
        r["modelo"] = r["modelo"] or f["modelo_row"]
        r["serie"] = r["serie"] or f["serie_row"]
        f["marca"], f["modelo"], f["serie"] = r["marca"], r["modelo"], r["serie"]
        f["switch_ip"] = r["ip"] or f.get("ip_sw", "")
    avisos = []
    libres_ok = False
    if libres:
        li = _libres_info(sid, sel, force)
        libres_ok = bool(li["ok"])
        if not libres_ok:
            avisos.append(li["msg"])
        else:
            usados = set()
            for f in filas:
                pk = _pkey(f["puerto"])
                kh, ki = (f["switch"].lower(), pk), (f["switch_ip"], pk)
                e = li["h"].get(kh) or li["i"].get(ki)
                f["l_ok"] = True
                if e:
                    f["l_en_lista"] = True
                    usados.add(e["id"])
                    if e["ultimo"]:
                        f["t_key"], f["t_val"] = "\u00daltimo Input", e["ultimo"]
                        _tiempo_campos(f)
                up = (e or {}).get("uptime") or li["up_h"].get(f["switch"].lower()) or li["up_i"].get(f["switch_ip"], "")
                f["uptime"] = up
                f["t_uptime_seg"] = _uptime_seg(up) if up else None
                r = resumen.get(f["switch"].lower())
                if r is not None and up and not r["uptime"]:
                    r["uptime"] = up
            sin_rel = li["n_ent"] - len(usados)
            if sin_rel:
                avisos.append("%d fila(s) de Puertos Libres no se pudieron relacionar con Estatus de Puertos "
                              "(nombres de puerto distintos)." % sin_rel)

    # PARCHE_DATOS_DASHBOARD_1
    # Conservar serie por interfaz, especialmente miembros distintos del stack.
    for f in filas:
        f['serie']=f.get('serie_row') or f.get('serie','')
        f['ultimo_input_original']=None
        f['ultimo_output_original']=None
        f['crudo_libres']={}
        f['reporte_libres']='Sin informacion'
        if libres_ok:
            e=li['h'].get((f['switch'].lower(),_pkey(f['puerto']))) or li['i'].get((f['switch_ip'],_pkey(f['puerto'])))
            f['reporte_libres']='Reportado por dashboard' if e else 'No listado'
            if e:
                f['ultimo_input_original']=e['ultimo']
                f['ultimo_output_original']=e['output']
                f['crudo_libres']=e['crudo']
                f['serie']=e.get('serie') or f['serie']
    for r in resumen.values():
        series=sorted({f['serie'] for f in filas if f['switch']==r['hostname'] and f.get('serie')})
        if series: r['serie']=' / '.join(series)

    cuenta = Counter(f["descripcion"].strip().lower() for f in filas if f["descripcion"])
    ahora = time.time()
    hist = _hist_actualizar(sid, ts, filas)
    for f in filas:
        r = resumen.get(f["switch"].lower())
        h = hist.get(f["switch"] + "|" + f["puerto"])
        f["hist"] = ({"desde": h.get("desde"), "n": h.get("n", 1), "primera": h.get("primera", False),
                      "activo": h.get("activo")} if h else None)
        dn = cuenta.get(f["descripcion"].strip().lower(), 0) if f["descripcion"] else 0
        f["desc_n"], f["desc_generica"] = dn, dn >= GENERICA_MIN
        f["disp"], f["motivo"] = _disp(f, h, ahora)
        f["t_txt"], f["t_det"] = _t_textos(f)
        if f["l_ok"] and f["estado"] == "sin_enlace" and not f["l_en_lista"]:
            f["t_det"] = (f["t_det"] + " " if f["t_det"] else "") + "El dashboard no lista este puerto en Puertos Libres."
        if r is not None:
            r["total"] += 1
            r[f["estado"]] += 1
            r["libres"] += f["disp"] == "libre_probable"
            r["confirmar"] += f["disp"] == "por_confirmar"
            r["asignados"] += f["disp"] == "asignado"
        for c in ("ip_sw", "serie_row", "modelo_row", "marca_row", "t_val"):
            f.pop(c, None)
    sin_datos = [r["hostname"] for r in resumen.values() if r["total"] == 0]
    if sin_datos:
        avisos.append("Sin datos de: " + ", ".join(sin_datos) + ". No se muestran como si no tuvieran puertos.")
    if extra:
        avisos.append("%d puerto(s) llegaron con un switch distinto al del catalogo." % extra)
    return {"ok": True, "sitio": sitio, "switches": list(resumen.values()), "puertos": filas,
            "avisos": avisos, "errores": errores, "intentos": intentos, "edad": ts, "ahora": ahora,
            "dias_libre": DIAS_LIBRE, "generica_min": GENERICA_MIN, "libres_ok": libres_ok}


def _json(h, code, obj):
    b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(b)))
    h.end_headers()
    h.wfile.write(b)


def manejar(h):
    """True si la ruta es de esta suite (solo GET)."""
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
            b = open(os.path.join(DIR, "index.html"), "rb").read()
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(b)))
            h.end_headers()
            h.wfile.write(b)
        elif dr is None:
            _json(h, 503, {"ok": False, "msg": "No se pudo cargar dashboard_red.py: %s" % _ERR})
        elif path == PREFIX + "/api/sitios":
            _json(h, 200, dr.sitios())
        elif path == PREFIX + "/api/switches":
            if not q.get("sitio", "").strip():
                _json(h, 400, {"ok": False, "msg": "Falta el sitio"})
            else:
                _json(h, 200, api_switches(q["sitio"], q.get("refrescar") == "1"))
        elif path == PREFIX + "/api/puertos":
            if not q.get("sitio", "").strip():
                _json(h, 400, {"ok": False, "msg": "Falta el sitio"})
            else:
                sel = {x.strip() for x in q.get("switches", "").split(",") if x.strip()}
                _json(h, 200, api_puertos(q["sitio"], sel, q.get("refrescar") == "1", q.get("libres") == "1"))
        else:
            _json(h, 404, {"ok": False, "msg": "Ruta no encontrada"})
    except Exception as e:
        _json(h, 500, {"ok": False, "msg": "Error: %s" % e})
    return True
