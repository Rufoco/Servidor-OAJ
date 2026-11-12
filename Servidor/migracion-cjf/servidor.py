#!/usr/bin/env python3
# servidor.py
# pip install ldap3 | python servidor.py

import subprocess
import threading
import csv
import uuid
import http.server, socketserver, urllib.request, urllib.parse
import os, functools, json, configparser, datetime, subprocess, tempfile, secrets, threading, sys
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVE_DIR = os.path.dirname(SCRIPT_DIR)
INDEX_HTML = os.path.join(SCRIPT_DIR, "index.html")
PORTAL_HTML = os.path.join(SERVE_DIR, "DGTI_Zapopan", "index.html")
GESTOR_HTML = os.path.join(SERVE_DIR, "gestor-ad", "index.html")
RESET_HTML = os.path.join(SERVE_DIR, "reset-masivo", "index.html")

#Modulo Esaneos e impresoras
IMPRESORAS_HTML = os.path.join(SERVE_DIR, "escaneo-impresoras", "index.html")
RUTA_SCRIPT_PS1 = os.path.join(SERVE_DIR, "escaneo-impresoras", "Escaneo-Impresoras-VLANs.ps1")
RUTA_CSV_SALIDA = os.path.join(SERVE_DIR, "escaneo-impresoras", "Inventario_Impresoras_VLANs.csv")
RUTA_PROGRESO_JSON = os.path.join(SERVE_DIR, "escaneo-impresoras", "progreso_escaneo.json")

ESCANEOS_IMPRESORAS = {}

# --- Escaneo por lista de IPs (agregado) ---
ESCANEOS_IPS = {}
RUTA_SCRIPT_IPS_PS1 = os.path.join(SERVE_DIR, "escaneo-impresoras", "Escaneo-Impresoras-IPs.ps1")

# â”€â”€â”€ MÃ³dulo nuevo: Inventario de equipos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
INVENTARIO_DIR = os.path.join(SERVE_DIR, "inventario-equipos")
INVENTARIO_HTML = os.path.join(INVENTARIO_DIR, "index.html")
INVENTARIO_CSS = os.path.join(INVENTARIO_DIR, "css", "styles.css")
INVENTARIO_JS = os.path.join(INVENTARIO_DIR, "js", "app.js")

if INVENTARIO_DIR not in sys.path:
    sys.path.insert(0, INVENTARIO_DIR)

try:
    from inventario_backend import consultar_inventario
except Exception as _exc_inventario:
    # Si el mÃ³dulo aÃºn no existe o falla al importar, el servidor sigue
    # funcionando con el resto de herramientas; el endpoint solo reportarÃ¡ el error.
    def consultar_inventario():
        raise RuntimeError(
            f"No se pudo cargar inventario_backend.py: {_exc_inventario}"
        )

# --- Modulo Localizador IP (Dashboard de Red) ---
LOCALIZADOR_DIR = os.path.join(SERVE_DIR, "localizador-ip")
if LOCALIZADOR_DIR not in sys.path:
    sys.path.insert(0, LOCALIZADOR_DIR)
try:
    import dashboard_red
except Exception as _exc_dash:
    dashboard_red = None
    print(f"[Localizador IP] No se pudo cargar dashboard_red.py: {_exc_dash}")

# --- Suite Herramientas de Red ---
RED_DIR = os.path.join(SERVE_DIR, "gestor-puertos")
if RED_DIR not in sys.path:
    sys.path.insert(0, RED_DIR)
try:
    import red_suite
except Exception as _exc_red:
    red_suite = None
    print(f"[Herramientas de Red] No se pudo cargar red_suite.py: {_exc_red}")

PORT = 8080
SESSION_TTL = 8 * 3600

cfg = configparser.ConfigParser()
cfg.read(os.path.join(SCRIPT_DIR, "config.ini"), encoding="utf-8")

LDAP_SERVER = cfg["ldap"]["server"]
LDAP_PORT = int(cfg["ldap"]["port"])
LDAP_DOMAIN = cfg["ldap"]["domain"]
LDAP_BASE = cfg["ldap"]["search_base"]

OAJ_SERVER = cfg.get("ldap_oaj", "server", fallback="oajdc01322.oaj.gob.mx")
OAJ_PORT = int(cfg.get("ldap_oaj", "port", fallback="389"))
OAJ_DOMAIN = cfg.get("ldap_oaj", "domain", fallback="oaj")
OAJ_BASE = cfg.get("ldap_oaj", "search_base", fallback="DC=oaj,DC=gob,DC=mx")

TDJ_SERVER = cfg.get("ldap_tdj", "server", fallback="TDJDC01367.tdj.gob.mx")
TDJ_PORT = int(cfg.get("ldap_tdj", "port", fallback="389"))
TDJ_DOMAIN = cfg.get("ldap_tdj", "domain", fallback="tdj")
TDJ_BASE = cfg.get("ldap_tdj", "search_base", fallback="DC=tdj,DC=gob,DC=mx")

M365_REAL = "http://10.100.66.157/reportes-DSI/modulos/M365.php"

LDAP_ATTRS = [
    "employeeID", "givenName", "sn", "sAMAccountName", "mail", "displayName",
    "description", "physicalDeliveryOfficeName", "telephoneNumber",
    "title", "department", "company", "streetAddress", "l", "st", "postalCode",
    "userAccountControl",
]

GESTOR_ATTRS = LDAP_ATTRS + [
    "lockoutTime", "lastLogonTimestamp", "whenCreated",
    "badPwdCount", "pwdLastSet", "memberOf", "distinguishedName",
]

# â”€â”€â”€ Sesiones â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_sessions = {}
_sessions_lock = threading.Lock()


def session_create(user, domain, password):
    token = secrets.token_hex(32)
    exp = datetime.datetime.now() + datetime.timedelta(seconds=SESSION_TTL)
    with _sessions_lock:
        _sessions[token] = {
            "display": f"{domain.upper()}\\{user}",
            "primary": domain,
            "expires": exp,
            "creds": {domain: {"user": user, "password": password}},
        }
    return token


def session_get(token):
    with _sessions_lock:
        s = _sessions.get(token)
        if not s:
            return None
        if datetime.datetime.now() > s["expires"]:
            del _sessions[token]
            return None
        return s


def session_delete(token):
    with _sessions_lock:
        _sessions.pop(token, None)


def session_add_domain(token, domain, user, password):
    with _sessions_lock:
        s = _sessions.get(token)
        if not s:
            return False
        s["creds"][domain] = {"user": user, "password": password}
        return True


def sess_creds(sess, dominio):
    creds = sess["creds"].get(dominio)
    if not creds:
        raise PermissionError(f"Sin credenciales para '{dominio}'. Autenticate primero.")
    return creds["user"], creds["password"]


# â”€â”€â”€ Seguridad LDAP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def escape_ldap(value):
    from ldap3.utils.conv import escape_filter_chars
    return escape_filter_chars(str(value).strip()[:200])


# â”€â”€â”€ Helpers AD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def val(entry, attr):
    try:
        v = getattr(entry, attr).value
        return str(v) if v is not None else ""
    except Exception:
        return ""


def val_date(entry, attr):
    try:
        v = getattr(entry, attr).value
        if v is None:
            return ""
        if hasattr(v, "strftime"):
            return "" if v.year <= 1601 else v.strftime("%Y-%m-%d %H:%M")
        v = int(v)
        if v == 0:
            return ""
        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=v // 10)
        return "" if dt.year <= 1601 else dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def get_domain_cfg(dominio):
    if dominio == "oaj":
        return OAJ_SERVER, OAJ_PORT, OAJ_DOMAIN, OAJ_BASE
    if dominio == "tdj":
        return TDJ_SERVER, TDJ_PORT, TDJ_DOMAIN, TDJ_BASE
    return LDAP_SERVER, LDAP_PORT, LDAP_DOMAIN, LDAP_BASE


def _base_to_fqdn(base):
    parts = []
    for item in str(base).split(","):
        item = item.strip()
        if item.upper().startswith("DC="):
            parts.append(item[3:])
    return ".".join(parts)


# â”€â”€â”€ PowerShell â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _ps_si():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def run_ps(script):
    header = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8")
    try:
        tmp.write(header + script)
        tmp.close()
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", tmp.name],
            capture_output=True, timeout=30, startupinfo=_ps_si()
        )
        try:
            stdout = r.stdout.decode("utf-8")
            stderr = r.stderr.decode("utf-8")
        except UnicodeDecodeError:
            stdout = r.stdout.decode("cp1252", errors="replace")
            stderr = r.stderr.decode("cp1252", errors="replace")
        if stderr.strip():
            print(f" [PS] {stderr.strip()[:300]}")
        if r.returncode != 0 and "Error" in stderr:
            raise RuntimeError(stderr.strip())
        out = stdout.strip()
        if not out or out.lower() == "null":
            return []
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    finally:
        os.unlink(tmp.name)


# FIX 1: timeout 15 â†’ 30 segundos
def run_ps_raw(script):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8")
    try:
        tmp.write("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n" + script)
        tmp.close()
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", tmp.name],
            capture_output=True, timeout=30, startupinfo=_ps_si()
        )
        try:
            stdout = r.stdout.decode("utf-8")
            stderr = r.stderr.decode("utf-8")
        except UnicodeDecodeError:
            stdout = r.stdout.decode("cp1252", errors="replace")
            stderr = r.stderr.decode("cp1252", errors="replace")
        return r.returncode, stdout.strip(), stderr.strip()
    finally:
        os.unlink(tmp.name)


# â”€â”€â”€ Validar credenciales â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def validate_cjf(user, password):
    from ldap3 import Server, Connection, ALL, NTLM
    srv = Server(LDAP_SERVER, port=LDAP_PORT, get_info=ALL)
    conn = Connection(srv, user=f"{LDAP_DOMAIN}\\{user}", password=password,
                       authentication=NTLM, raise_exceptions=False)
    ok = conn.bind()
    if ok:
        conn.unbind()
    return ok


def validate_oaj(user, password):
    script = (
        f"$ctx=New-Object System.DirectoryServices.DirectoryEntry("
        f"'LDAP://{OAJ_SERVER}','{OAJ_DOMAIN}\\{user}','{password}',"
        f"[System.DirectoryServices.AuthenticationTypes]::Secure)\n"
        f"try{{$null=$ctx.distinguishedName;"
        f"if($ctx.distinguishedName){{Write-Output 'ok'}}else{{Write-Output 'fail'}}}}"
        f"catch{{Write-Output 'fail'}}"
    )
    code, out, _ = run_ps_raw(script)
    return out.strip().lower() == "ok"


def validate_tdj(user, password):
    script = (
        f"$ctx=New-Object System.DirectoryServices.DirectoryEntry("
        f"'LDAP://{TDJ_SERVER}','{TDJ_DOMAIN}\\{user}','{password}',"
        f"[System.DirectoryServices.AuthenticationTypes]::Secure)\n"
        f"try{{$null=$ctx.distinguishedName;"
        f"if($ctx.distinguishedName){{Write-Output 'ok'}}else{{Write-Output 'fail'}}}}"
        f"catch{{Write-Output 'fail'}}"
    )
    code, out, _ = run_ps_raw(script)
    return out.strip().lower() == "ok"


def validate_domain(dominio, user, password):
    if dominio == "oaj":
        return validate_oaj(user, password)
    if dominio == "tdj":
        return validate_tdj(user, password)
    return validate_cjf(user, password)


# â”€â”€â”€ consultar_ad (migracion-cjf) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def consultar_ad(usernames, sess_user, sess_pass):
    from ldap3 import Server, Connection, ALL, NTLM
    server = Server(LDAP_SERVER, port=LDAP_PORT, get_info=ALL)
    conn = Connection(server, user=f"{LDAP_DOMAIN}\\{sess_user}", password=sess_pass,
                       authentication=NTLM, auto_bind=True)
    results = {}
    for username in usernames:
        safe = escape_ldap(username)
        conn.search(LDAP_BASE, f"(sAMAccountName={safe})", attributes=LDAP_ATTRS)
        if conn.entries:
            e = conn.entries[0]
            uac = int(val(e, "userAccountControl") or 0)
            results[username] = {
                "ID": val(e, "employeeID"), "Nombre": val(e, "givenName"),
                "Apellido": val(e, "sn"), "Usuario": val(e, "sAMAccountName"),
                "Correo": val(e, "mail"), "DisplayName": val(e, "displayName"),
                "description": val(e, "description"),
                "Office": val(e, "physicalDeliveryOfficeName"),
                "telephoneNumber": val(e, "telephoneNumber"),
                "title": val(e, "title"), "department": val(e, "department"),
                "company": val(e, "company"), "streetAddress": val(e, "streetAddress"),
                "l": val(e, "l"), "st": val(e, "st"), "postalCode": val(e, "postalCode"),
                "hab": "NO" if (uac & 2) else "SI",
            }
    conn.unbind()
    return results


# â”€â”€â”€ Gestor: buscar CJF â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def buscar_cjf(query, sess_user, sess_pass):
    from ldap3 import Server, Connection, ALL, NTLM
    safe = escape_ldap(query)
    filtro = (f"(|(sAMAccountName=*{safe}*)(givenName=*{safe}*)"
              f"(sn=*{safe}*)(displayName=*{safe}*)(description=*{safe}*))")
    server = Server(LDAP_SERVER, port=LDAP_PORT, get_info=ALL)
    conn = Connection(server, user=f"{LDAP_DOMAIN}\\{sess_user}", password=sess_pass,
                       authentication=NTLM, auto_bind=True)
    conn.search(LDAP_BASE, filtro, attributes=GESTOR_ATTRS)
    results = []
    for e in conn.entries[:15]:
        uac = int(val(e, "userAccountControl") or 0)
        lockout = val(e, "lockoutTime")
        bloq = bool(lockout and lockout not in ("0",) and not lockout.startswith("1601"))
        try:
            mv = getattr(e, "memberOf").values
            if isinstance(mv, str):
                mv = [mv]
            grupos = [g.split(",")[0].replace("CN=", "").replace("cn=", "")
                      for g in (mv or [])]
        except Exception:
            grupos = []
        results.append({
            "dn": val(e, "distinguishedName"),
            "ID": val(e, "employeeID"), "Nombre": val(e, "givenName"),
            "Apellido": val(e, "sn"), "Usuario": val(e, "sAMAccountName"),
            "Correo": val(e, "mail"), "DisplayName": val(e, "displayName"),
            "description": val(e, "description"), "Office": val(e, "physicalDeliveryOfficeName"),
            "Telefono": val(e, "telephoneNumber"), "Cargo": val(e, "title"),
            "Departamento": val(e, "department"), "Empresa": val(e, "company"),
            "habilitado": "NO" if (uac & 2) else "SI",
            "bloqueado": "SI" if bloq else "NO",
            "pwd_nunca_expira": "SI" if (uac & 65536) else "NO",
            "pwd_expirada": "SI" if (uac & 8388608) else "NO",
            "pwd_forzar": "SI" if val(e, "pwdLastSet") == "0" else "NO",
            "intentos_fallidos": val(e, "badPwdCount"),
            "ultimo_login": val_date(e, "lastLogonTimestamp"),
            "creado": val_date(e, "whenCreated"),
            "pwd_ultimo_cambio": val_date(e, "pwdLastSet"),
            "grupos": sorted(grupos),
        })
    conn.unbind()
    return results


# â”€â”€â”€ Gestor: buscar OAJ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def buscar_oaj(query, sess_user, sess_pass):
    safe = escape_ldap(query)
    ps = f"""
$auth = [System.DirectoryServices.AuthenticationTypes]::Signing -bor `
        [System.DirectoryServices.AuthenticationTypes]::Sealing -bor `
        [System.DirectoryServices.AuthenticationTypes]::Secure

$baseDN = '{OAJ_BASE}'
try {{
    $root = New-Object System.DirectoryServices.DirectoryEntry(
        'LDAP://{OAJ_SERVER}/RootDSE', '{OAJ_DOMAIN}\\{sess_user}', '{sess_pass}', $auth)
    if ($root.defaultNamingContext) {{ $baseDN = $root.defaultNamingContext }}
}} catch {{}}

$entry = New-Object System.DirectoryServices.DirectoryEntry(
    "LDAP://{OAJ_SERVER}/$baseDN", '{OAJ_DOMAIN}\\{sess_user}', '{sess_pass}', $auth)
$search = New-Object System.DirectoryServices.DirectorySearcher($entry)
$search.Filter = '(|(sAMAccountName=*{safe}*)(givenName=*{safe}*)(sn=*{safe}*)(displayName=*{safe}*)(description=*{safe}*))'
$search.SizeLimit = 15

foreach ($a in @('employeeID','givenName','sn','sAMAccountName','mail','displayName',
    'description','physicalDeliveryOfficeName','telephoneNumber','title','department',
    'company','userAccountControl','lockoutTime','lastLogonTimestamp','whenCreated',
    'badPwdCount','pwdLastSet','memberOf','distinguishedName')) {{
    [void]$search.PropertiesToLoad.Add($a)
}}

function LdapVal($r, $k) {{
    if ($r.Properties[$k].Count -gt 0) {{ return "$($r.Properties[$k][0])" }}
    return ''
}}
function LdapDate($r, $k) {{
    if ($r.Properties[$k].Count -eq 0) {{ return '' }}
    try {{
        $raw = $r.Properties[$k][0]
        if ($raw -is [DateTime]) {{ return $raw.ToString('yyyy-MM-dd HH:mm') }}
        $v = [Int64]$raw
        if ($v -le 0) {{ return '' }}
        return [DateTime]::FromFileTime($v).ToString('yyyy-MM-dd HH:mm')
    }} catch {{ return '' }}
}}

$out = @()
foreach ($r in $search.FindAll()) {{
    try {{
        $uac = 0; try {{ $uac = [int](LdapVal $r 'userAccountControl') }} catch {{}}
        $lock = 0; try {{ $lock = [Int64]$r.Properties['lockoutTime'][0] }} catch {{}}
        $pls = 0; try {{ $pls = [Int64]$r.Properties['pwdLastSet'][0] }} catch {{}}

        $grupos = @($r.Properties['memberOf'] | ForEach-Object {{
            ($_ -split ',')[0] -replace '^CN=','' -replace '^cn=',''
        }} | Sort-Object)

        $out += [PSCustomObject]@{{
            dn = LdapVal $r 'distinguishedName'
            ID = LdapVal $r 'employeeID'
            Nombre = LdapVal $r 'givenName'
            Apellido = LdapVal $r 'sn'
            Usuario = LdapVal $r 'sAMAccountName'
            Correo = LdapVal $r 'mail'
            DisplayName = LdapVal $r 'displayName'
            description = LdapVal $r 'description'
            Office = LdapVal $r 'physicalDeliveryOfficeName'
            Telefono = LdapVal $r 'telephoneNumber'
            Cargo = LdapVal $r 'title'
            Departamento = LdapVal $r 'department'
            Empresa = LdapVal $r 'company'
            habilitado = if ($uac -band 2) {{ 'NO' }} else {{ 'SI' }}
            bloqueado = if ($lock -gt 0) {{ 'SI' }} else {{ 'NO' }}
            pwd_nunca_expira = if ($uac -band 65536) {{ 'SI' }} else {{ 'NO' }}
            pwd_expirada = if ($uac -band 8388608) {{ 'SI' }} else {{ 'NO' }}
            pwd_forzar = if ($pls -eq 0) {{ 'SI' }} else {{ 'NO' }}
            intentos_fallidos = LdapVal $r 'badPwdCount'
            ultimo_login = LdapDate $r 'lastLogonTimestamp'
            creado = LdapDate $r 'whenCreated'
            pwd_ultimo_cambio = LdapDate $r 'pwdLastSet'
            grupos = $grupos
        }}
    }} catch {{ [Console]::Error.WriteLine("Error entrada: $_") }}
}}

if ($out.Count -eq 0) {{ Write-Output '[]' }}
else {{ $out | ConvertTo-Json -Depth 3 }}
"""
    return run_ps(ps)


# â”€â”€â”€ Gestor: buscar TDJ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def buscar_tdj(query, sess_user, sess_pass):
    safe = escape_ldap(query)
    ps = f"""
$auth = [System.DirectoryServices.AuthenticationTypes]::Signing -bor `
        [System.DirectoryServices.AuthenticationTypes]::Sealing -bor `
        [System.DirectoryServices.AuthenticationTypes]::Secure

$baseDN = '{TDJ_BASE}'
try {{
    $root = New-Object System.DirectoryServices.DirectoryEntry(
        'LDAP://{TDJ_SERVER}/RootDSE', '{TDJ_DOMAIN}\\{sess_user}', '{sess_pass}', $auth)
    if ($root.defaultNamingContext) {{ $baseDN = $root.defaultNamingContext }}
}} catch {{}}

$entry = New-Object System.DirectoryServices.DirectoryEntry(
    "LDAP://{TDJ_SERVER}/$baseDN", '{TDJ_DOMAIN}\\{sess_user}', '{sess_pass}', $auth)
$search = New-Object System.DirectoryServices.DirectorySearcher($entry)
$search.Filter = '(|(sAMAccountName=*{safe}*)(givenName=*{safe}*)(sn=*{safe}*)(displayName=*{safe}*)(description=*{safe}*))'
$search.SizeLimit = 15

foreach ($a in @('employeeID','givenName','sn','sAMAccountName','mail','displayName',
    'description','physicalDeliveryOfficeName','telephoneNumber','title','department',
    'company','userAccountControl','lockoutTime','lastLogonTimestamp','whenCreated',
    'badPwdCount','pwdLastSet','memberOf','distinguishedName')) {{
    [void]$search.PropertiesToLoad.Add($a)
}}

function LdapVal($r, $k) {{
    if ($r.Properties[$k].Count -gt 0) {{ return "$($r.Properties[$k][0])" }}
    return ''
}}
function LdapDate($r, $k) {{
    if ($r.Properties[$k].Count -eq 0) {{ return '' }}
    try {{
        $raw = $r.Properties[$k][0]
        if ($raw -is [DateTime]) {{ return $raw.ToString('yyyy-MM-dd HH:mm') }}
        $v = [Int64]$raw
        if ($v -le 0) {{ return '' }}
        return [DateTime]::FromFileTime($v).ToString('yyyy-MM-dd HH:mm')
    }} catch {{ return '' }}
}}

$out = @()
foreach ($r in $search.FindAll()) {{
    try {{
        $uac = 0; try {{ $uac = [int](LdapVal $r 'userAccountControl') }} catch {{}}
        $lock = 0; try {{ $lock = [Int64]$r.Properties['lockoutTime'][0] }} catch {{}}
        $pls = 0; try {{ $pls = [Int64]$r.Properties['pwdLastSet'][0] }} catch {{}}

        $grupos = @($r.Properties['memberOf'] | ForEach-Object {{
            ($_ -split ',')[0] -replace '^CN=','' -replace '^cn=',''
        }} | Sort-Object)

        $out += [PSCustomObject]@{{
            dn = LdapVal $r 'distinguishedName'
            ID = LdapVal $r 'employeeID'
            Nombre = LdapVal $r 'givenName'
            Apellido = LdapVal $r 'sn'
            Usuario = LdapVal $r 'sAMAccountName'
            Correo = LdapVal $r 'mail'
            DisplayName = LdapVal $r 'displayName'
            description = LdapVal $r 'description'
            Office = LdapVal $r 'physicalDeliveryOfficeName'
            Telefono = LdapVal $r 'telephoneNumber'
            Cargo = LdapVal $r 'title'
            Departamento = LdapVal $r 'department'
            Empresa = LdapVal $r 'company'
            habilitado = if ($uac -band 2) {{ 'NO' }} else {{ 'SI' }}
            bloqueado = if ($lock -gt 0) {{ 'SI' }} else {{ 'NO' }}
            pwd_nunca_expira = if ($uac -band 65536) {{ 'SI' }} else {{ 'NO' }}
            pwd_expirada = if ($uac -band 8388608) {{ 'SI' }} else {{ 'NO' }}
            pwd_forzar = if ($pls -eq 0) {{ 'SI' }} else {{ 'NO' }}
            intentos_fallidos = LdapVal $r 'badPwdCount'
            ultimo_login = LdapDate $r 'lastLogonTimestamp'
            creado = LdapDate $r 'whenCreated'
            pwd_ultimo_cambio = LdapDate $r 'pwdLastSet'
            grupos = $grupos
        }}
    }} catch {{ [Console]::Error.WriteLine("Error entrada: $_") }}
}}

if ($out.Count -eq 0) {{ Write-Output '[]' }}
else {{ $out | ConvertTo-Json -Depth 3 }}
"""
    return run_ps(ps)


def buscar_usuario_gestor(query, dominio, sess):
    u, p = sess_creds(sess, dominio)
    if dominio == "oaj":
        return buscar_oaj(query, u, p)
    if dominio == "tdj":
        return buscar_tdj(query, u, p)
    return buscar_cjf(query, u, p)


# â”€â”€â”€ Acciones AD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _accion_ldap3(dn, dominio, accion, sess, **kw):
    from ldap3 import Server, Connection, ALL, NTLM, MODIFY_REPLACE
    srv, port, domain, base = get_domain_cfg(dominio)
    u, p = sess_creds(sess, dominio)
    server = Server(srv, port=port, get_info=ALL)
    conn = Connection(server, user=f"{domain}\\{u}", password=p,
                       authentication=NTLM, auto_bind=True)
    if accion == "desbloquear":
        ok = conn.modify(dn, {"lockoutTime": [(MODIFY_REPLACE, [0])]})
    elif accion == "forzar":
        ok = conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])]})
    else:
        ok = False
    err = str(conn.result) if not ok else ""
    conn.unbind()
    return ok, err


def _accion_ps(dn, dominio, accion, sess, **kw):
    srv, port, domain, base = get_domain_cfg(dominio)
    u, p = sess_creds(sess, dominio)
    dn_s = dn.replace("'", "\\'")
    p_s = p.replace("'", "\\'")
    auth = (
        "$auth=[System.DirectoryServices.AuthenticationTypes]::Signing -bor "
        "[System.DirectoryServices.AuthenticationTypes]::Sealing -bor "
        "[System.DirectoryServices.AuthenticationTypes]::Secure"
    )
    entry = f"$e=New-Object System.DirectoryServices.DirectoryEntry('LDAP://{srv}/{dn_s}','{domain}\\{u}','{p_s}',$auth)"
    if accion == "reset":
        np = kw["nueva_pass"].replace("'", "\\'")
        ps = f"{auth}\n{entry}\n$e.psbase.Invoke('SetPassword','{np}')\n$e.CommitChanges()\nWrite-Output 'ok'"
    elif accion == "desbloquear":
        ps = f"{auth}\n{entry}\n$e.psbase.InvokeSet('IsAccountLocked',$false)\n$e.CommitChanges()\nWrite-Output 'ok'"
    elif accion == "forzar":
        ps = f"{auth}\n{entry}\n$e.psbase.InvokeSet('PasswordExpired',1)\n$e.CommitChanges()\nWrite-Output 'ok'"
    else:
        return False, "Accion desconocida"

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8")
    try:
        tmp.write("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n")
        tmp.write(ps)
        tmp.close()
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", tmp.name],
            capture_output=True, timeout=20, startupinfo=_ps_si()
        )
        try:
            stdout = r.stdout.decode("utf-8")
            stderr = r.stderr.decode("utf-8")
        except UnicodeDecodeError:
            stdout = r.stdout.decode("cp1252", errors="replace")
            stderr = r.stderr.decode("cp1252", errors="replace")
        if r.returncode != 0 or "Exception" in stderr:
            return False, stderr.strip()
        return True, ""
    finally:
        os.unlink(tmp.name)


# FIX 2: reset_password_ad â€” URL sin base_s, auth Signing+Sealing+Secure
def reset_password_ad(dn, nueva_pass, dominio, sess, sam=""):
    srv, port, domain, base = get_domain_cfg(dominio)
    u, p = sess_creds(sess, dominio)

    p_s = p.replace("'", "''")
    np_s = nueva_pass.replace("'", "''")
    u_s = (domain + "\\" + u).replace("'", "''")
    sam_s = sam.strip().replace("'", "''") if sam.strip() else ""
    srv_s = srv.replace("'", "''")

    if sam_s:
        filtro = "(sAMAccountName=" + sam_s + ")"
    else:
        dn_esc = dn.replace("\\", "\\\\").replace("'", "''")
        filtro = "(distinguishedName=" + dn_esc + ")"

    lines = [
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "$auth = [System.DirectoryServices.AuthenticationTypes]::Signing -bor "
        "[System.DirectoryServices.AuthenticationTypes]::Sealing -bor "
        "[System.DirectoryServices.AuthenticationTypes]::Secure",
        "$root = New-Object System.DirectoryServices.DirectoryEntry(",
        "    'LDAP://" + srv_s + "',",
        "    '" + u_s + "',",
        "    '" + p_s + "',",
        "    $auth",
        ")",
        "$search = New-Object System.DirectoryServices.DirectorySearcher($root)",
        "$search.Filter = '" + filtro + "'",
        "$result = $search.FindOne()",
        "if (-not $result) { throw 'Usuario no encontrado: " + (sam_s or dn) + "' }",
        "$entry = $result.GetDirectoryEntry()",
        "$entry.psbase.Invoke('SetPassword', '" + np_s + "')",
        "$entry.CommitChanges()",
        "Write-Output 'ok'",
    ]
    ps = "\n".join(lines)

    code, out, err = run_ps_raw(ps)
    if code != 0:
        return False, (err or out or "Error al cambiar contrasena").strip()
    if "ok" not in (out or "").lower():
        return False, (err or out or "No se pudo cambiar la contrasena").strip()
    return True, ""


def desbloquear_ad(dn, dominio, sess):
    if dominio in ("oaj", "tdj"):
        return _accion_ps(dn, dominio, "desbloquear", sess)
    return _accion_ldap3(dn, dominio, "desbloquear", sess)


def forzar_cambio_ad(dn, dominio, sess):
    if dominio in ("oaj", "tdj"):
        return _accion_ps(dn, dominio, "forzar", sess)
    return _accion_ldap3(dn, dominio, "forzar", sess)


# FIX 3: reset_masivo_ad â€” escape correcto + auth flags completos para OAJ/TDJ
def reset_masivo_ad(usuario, nueva_pass, dominio, sess, forzar=False, desbloquear=False):
    from ldap3 import Server, Connection, ALL, NTLM
    srv, port, domain, base = get_domain_cfg(dominio)
    u, p = sess_creds(sess, dominio)

    p_s = p.replace("'", "''")
    u_s = u.replace("'", "''")

    dn = ""
    try:
        if dominio in ("oaj", "tdj"):
            safe = escape_ldap(usuario)
            ps_find = (
                "$auth=[System.DirectoryServices.AuthenticationTypes]::Signing -bor "
                "[System.DirectoryServices.AuthenticationTypes]::Sealing -bor "
                "[System.DirectoryServices.AuthenticationTypes]::Secure\n"
                f"$entry=New-Object System.DirectoryServices.DirectoryEntry("
                f"'LDAP://{srv}/{base}','{domain}\\{u_s}','{p_s}',$auth)\n"
                f"$search=New-Object System.DirectoryServices.DirectorySearcher($entry)\n"
                f"$search.Filter='(sAMAccountName={safe})'\n"
                "[void]$search.PropertiesToLoad.Add('distinguishedName')\n"
                "$r=$search.FindOne()\n"
                "if($r){Write-Output $r.Properties['distinguishedName'][0]}else{Write-Output ''}"
            )
            code, out, err = run_ps_raw(ps_find)
            dn = out.strip()
            if not dn:
                return {"ok": False, "dn": "", "error": f"Usuario no encontrado en {dominio.upper()}"}
        else:
            server = Server(srv, port=port, get_info=ALL)
            conn = Connection(server, user=f"{domain}\\{u}", password=p,
                               authentication=NTLM, auto_bind=True)
            safe = escape_ldap(usuario)
            conn.search(base, f"(sAMAccountName={safe})", attributes=["distinguishedName"])
            if not conn.entries:
                conn.unbind()
                return {"ok": False, "dn": "", "error": "Usuario no encontrado en CJF"}
            dn = val(conn.entries[0], "distinguishedName")
            conn.unbind()

        ok, err_msg = reset_password_ad(dn, nueva_pass, dominio, sess)
        if not ok:
            return {"ok": False, "dn": dn, "error": err_msg or "Error al cambiar contrasena"}
        if forzar:
            forzar_cambio_ad(dn, dominio, sess)
        if desbloquear:
            desbloquear_ad(dn, dominio, sess)
        return {"ok": True, "dn": dn, "error": ""}
    except PermissionError as exc:
        return {"ok": False, "dn": dn, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "dn": dn, "error": str(exc)}

#Nueva seccion de IMPRESORAS -----------------------------------------

# --- Escaneo por lista de IPs (agregado) ---
def _parsear_ips(texto):
    import ipaddress
    import re as _re
    validas, invalidas, vistas = [], [], set()
    for token in _re.split(r"[\s,;]+", texto or ""):
        token = token.strip()
        if not token:
            continue
        try:
            ip = str(ipaddress.IPv4Address(token))
        except ValueError:
            invalidas.append(token)
            continue
        if ip in vistas:
            continue
        vistas.add(ip)
        validas.append(ip)
    return validas, invalidas


def _ejecutar_escaneo_ips(job_id, community, ips):
    import csv
    job = ESCANEOS_IPS[job_id]
    carpeta = os.path.join(SERVE_DIR, "escaneo-impresoras")
    f_ips = os.path.join(carpeta, "ips_" + job_id + ".txt")
    f_csv = os.path.join(carpeta, "Inventario_IPs_" + job_id + ".csv")
    f_prog = os.path.join(carpeta, "progreso_ips_" + job_id + ".json")
    job["archivo_progreso"] = f_prog
    try:
        job["estado"] = "corriendo"
        with open(f_ips, "w", encoding="ascii") as f:
            f.write("\n".join(ips))
        args = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", RUTA_SCRIPT_IPS_PS1,
            "-Community", community,
            "-ArchivoIps", f_ips,
            "-Salida", f_csv,
            "-ArchivoProgreso", f_prog,
        ]
        resultado = subprocess.run(args, capture_output=True, text=True, timeout=1800)
        if not os.path.exists(f_csv):
            job["estado"] = "error"
            job["error"] = (resultado.stderr or resultado.stdout or "El script no genero resultados")[:500]
            return
        with open(f_csv, encoding="utf-8-sig", newline="") as f:
            job["datos"] = list(csv.DictReader(f))
        job["estado"] = "listo"
    except Exception as exc:
        job["estado"] = "error"
        job["error"] = str(exc)
    finally:
        for ruta in (f_ips, f_csv, f_prog):
            try:
                os.remove(ruta)
            except OSError:
                pass


def _ejecutar_escaneo_impresoras(job_id, community, vlans):
    try:
        ESCANEOS_IMPRESORAS[job_id]["estado"] = "corriendo"

        args = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", RUTA_SCRIPT_PS1,
            "-Community", community,
            "-Salida", RUTA_CSV_SALIDA,
            "-ArchivoProgreso", RUTA_PROGRESO_JSON,
            "-VlansCsv", ",".join(vlans),
        ]

        resultado = subprocess.run(args, capture_output=True, text=True, timeout=1800)

        if resultado.returncode != 0 and not os.path.exists(RUTA_CSV_SALIDA):
            ESCANEOS_IMPRESORAS[job_id]["estado"] = "error"
            ESCANEOS_IMPRESORAS[job_id]["error"] = resultado.stderr[:500]
            return

        datos = []
        if os.path.exists(RUTA_CSV_SALIDA):
            with open(RUTA_CSV_SALIDA, encoding="utf-8-sig", newline="") as f:
                datos = list(csv.DictReader(f))

        ESCANEOS_IMPRESORAS[job_id]["estado"] = "listo"
        ESCANEOS_IMPRESORAS[job_id]["datos"] = datos

    except subprocess.TimeoutExpired:
        ESCANEOS_IMPRESORAS[job_id]["estado"] = "error"
        ESCANEOS_IMPRESORAS[job_id]["error"] = "El escaneo excediÃ³ 30 minutos."
    except Exception as e:
        ESCANEOS_IMPRESORAS[job_id]["estado"] = "error"
        ESCANEOS_IMPRESORAS[job_id]["error"] = str(e)


# â”€â”€â”€ HTTP Handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Handler(http.server.SimpleHTTPRequestHandler):

    def _get_token(self):
        auth = self.headers.get("Authorization", "")
        return auth[7:] if auth.startswith("Bearer ") else None

    def _get_session(self):
        t = self._get_token()
        return session_get(t) if t else None

    def _require_session(self):
        sess = self._get_session()
        if not sess:
            self._json(401, {"error": "No autenticado"})
        return sess

    def do_GET(self):
        # RUTA_PUBLICA_GESTOR_PUERTOS_V1
        _gp_path, _gp_sep, _gp_query = self.path.partition("?")
        if _gp_path in ("/herramientas-red", "/herramientas-red/"):
            self.send_response(302)
            self.send_header("Location", "/gestor-puertos/" + (_gp_sep + _gp_query if _gp_sep else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if _gp_path == "/gestor-puertos":
            self.send_response(307)
            self.send_header("Location", "/gestor-puertos/" + (_gp_sep + _gp_query if _gp_sep else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if _gp_path.startswith("/gestor-puertos/"):
            self.path = "/herramientas-red" + _gp_path[len("/gestor-puertos"):] + (_gp_sep + _gp_query if _gp_sep else "")
        parsed = urlparse(self.path)
        path = parsed.path
        # --- Login obligatorio: impresoras y localizador ---
        if path.startswith("/api/impresoras") or path.startswith("/localizador-ip/api") or path.startswith("/herramientas-red/api"):
            if not self._require_session():
                return
        # --- Localizador IP ---
        if dashboard_red and dashboard_red.manejar(self):
            return
        if red_suite and red_suite.manejar(self):
            return

        if path == "/DGTI_Zapopan": self._redirect("/DGTI_Zapopan/"); return
        if path == "/DGTI_Zapopan/": self._html(PORTAL_HTML); return
        if path == "/migracion-cjf": self._redirect("/migracion-cjf/"); return
        if path == "/migracion-cjf/": self._html(INDEX_HTML); return
        if path == "/gestor-ad": self._redirect("/gestor-ad/"); return
        if path == "/gestor-ad/": self._html(GESTOR_HTML); return
        if path == "/reset-masivo": self._redirect("/reset-masivo/"); return
        if path == "/reset-masivo/": self._html(RESET_HTML); return

        # â”€â”€â”€ Rutas nuevas: Inventario de equipos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if path == "/inventario-equipos":
            self._redirect("/inventario-equipos/")
            return

        if path == "/inventario-equipos/":
            self._html(INVENTARIO_HTML)
            return

        if path == "/inventario-equipos/css/styles.css":
            with open(INVENTARIO_CSS, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/inventario-equipos/js/app.js":
            with open(INVENTARIO_JS, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        if path == "/api/m365":
            params = parse_qs(parsed.query)
            user_red = params.get("userRed", [""])[0]
            try:
                url = f"{M365_REAL}?userRed={urllib.parse.quote(user_red)}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self._json(502, {"error": str(exc)})
            return
        if path == "/api/session":
            sess = self._get_session()
            if sess:
                self._json(200, {
                    "ok": True,
                    "display": sess["display"],
                    "domain": sess["primary"],
                    "authed_domains": list(sess["creds"].keys()),
                })
            else:
                self._json(401, {"ok": False})
            return

        if path == "/escaneo-impresoras":   self._redirect("/escaneo-impresoras/"); return
        if path == "/escaneo-impresoras/":  self._html(IMPRESORAS_HTML); return
        # --- Escaneo por lista de IPs (agregado) ---
        if path == "/api/impresoras/ips/estado":
            params = parse_qs(parsed.query)
            job_id = params.get("job_id", [""])[0]
            job = ESCANEOS_IPS.get(job_id, {"estado": "no_existe"})
            progreso = {}
            ruta = job.get("archivo_progreso")
            if job.get("estado") == "corriendo" and ruta and os.path.exists(ruta):
                try:
                    with open(ruta, encoding="utf-8-sig") as f:
                        progreso = json.load(f)
                except Exception:
                    progreso = {}
            self._json(200, {
                "estado": job.get("estado", "no_existe"),
                "error": job.get("error", ""),
                "fase": progreso.get("fase", ""),
                "hecho": progreso.get("hecho", 0),
                "de": progreso.get("de", 0),
                "ip_actual": progreso.get("ip_actual", ""),
                "impresoras_encontradas": progreso.get("impresoras_encontradas", 0),
            })
            return

        if path == "/api/impresoras/ips/resultado":
            params = parse_qs(parsed.query)
            job_id = params.get("job_id", [""])[0]
            job = ESCANEOS_IPS.get(job_id, {"datos": []})
            self._json(200, {"datos": job.get("datos", [])})
            return

        if path == "/api/impresoras/estado":
            params = parse_qs(parsed.query)
            job_id = params.get("job_id", [""])[0]
            job = ESCANEOS_IMPRESORAS.get(job_id, {"estado": "no_existe"})

            progreso = {}
            if job.get("estado") == "corriendo" and os.path.exists(RUTA_PROGRESO_JSON):
                try:
                    with open(RUTA_PROGRESO_JSON, encoding="utf-8-sig") as f:
                        progreso = json.load(f)
                except Exception:
                    progreso = {}

            self._json(200, {
                "estado": job.get("estado", "no_existe"),
                "error": job.get("error", ""),
                "vlan_actual": progreso.get("vlan_actual", ""),
                "ip_actual": progreso.get("ip_actual", ""),
                "ips_revisadas": progreso.get("ips_revisadas", 0),
                "ips_totales": progreso.get("ips_totales", 0),
                "impresoras_encontradas": progreso.get("impresoras_encontradas", 0),
        })
            return

        if path == "/api/impresoras/resultado":
            params = parse_qs(parsed.query)
            job_id = params.get("job_id", [""])[0]
            job = ESCANEOS_IMPRESORAS.get(job_id, {"datos": []})
            self._json(200, {"datos": job.get("datos", [])})
            return
    
        super().do_GET()

    def do_POST(self):
        # RUTA_PUBLICA_GESTOR_PUERTOS_V1
        _gp_path, _gp_sep, _gp_query = self.path.partition("?")
        if _gp_path == "/gestor-puertos":
            self.send_response(307)
            self.send_header("Location", "/gestor-puertos/" + (_gp_sep + _gp_query if _gp_sep else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if _gp_path.startswith("/gestor-puertos/"):
            self.path = "/herramientas-red" + _gp_path[len("/gestor-puertos"):] + (_gp_sep + _gp_query if _gp_sep else "")
        path = self.path
        # --- Login obligatorio: impresoras y localizador ---
        if path.startswith("/api/impresoras") or path.startswith("/localizador-ip/api") or path.startswith("/herramientas-red/api"):
            if not self._require_session():
                return

        if path == "/api/login":
            body = self._read_json()
            user = body.get("user", "").strip()
            password = body.get("password", "")
            dominio = body.get("dominio", "cjf").strip().lower()
            if not user or not password:
                self._json(400, {"error": "Usuario y contrasena requeridos"}); return
            try:
                ok = validate_domain(dominio, user, password)
                if ok:
                    token = session_create(user, dominio, password)
                    self._json(200, {"ok": True, "token": token,
                                      "display": f"{dominio.upper()}\\{user}",
                                      "authed_domains": [dominio]})
                else:
                    self._json(401, {"ok": False, "error": "Credenciales incorrectas"})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/login-domain":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            dominio = body.get("dominio", "").strip().lower()
            user = body.get("user", "").strip()
            password = body.get("password", "")
            if not dominio or not user or not password:
                self._json(400, {"error": "dominio, user y password requeridos"}); return
            try:
                ok = validate_domain(dominio, user, password)
                if ok:
                    token = self._get_token()
                    session_add_domain(token, dominio, user, password)
                    s2 = session_get(token)
                    self._json(200, {"ok": True,
                                      "authed_domains": list(s2["creds"].keys())})
                else:
                    self._json(401, {"ok": False, "error": "Credenciales incorrectas"})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/logout":
            t = self._get_token()
            if t: session_delete(t)
            self._json(200, {"ok": True}); return

        if path == "/api/usuarios":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            users = [u.strip().lower() for u in body.get("users", []) if u.strip()]
            if not users:
                self._json(400, {"error": "Lista vacia"}); return
            try:
                u, p = sess_creds(sess, sess["primary"])
                self._json(200, consultar_ad(users, u, p))
            except PermissionError as exc:
                self._json(403, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/ad/buscar":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            query = body.get("query", "").strip()
            dominio = body.get("dominio", "cjf").strip().lower()
            if not query:
                self._json(400, {"error": "query requerido"}); return
            try:
                self._json(200, buscar_usuario_gestor(query, dominio, sess))
            except PermissionError as exc:
                self._json(403, {"error": str(exc), "need_auth": dominio})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/ad/reset-password":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            dn = body.get("dn", "")
            nueva = body.get("nueva_pass", "")
            dominio = body.get("dominio", "cjf")
            sam = body.get("sam", "").strip()
            if not dn or not nueva:
                self._json(400, {"error": "dn y nueva_pass requeridos"}); return
            try:
                ok, err = reset_password_ad(dn, nueva, dominio, sess, sam=sam)
                self._json(200, {"ok": ok, "error": err})
            except PermissionError as exc:
                self._json(403, {"error": str(exc), "need_auth": dominio})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/ad/desbloquear":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            dn = body.get("dn", "")
            dominio = body.get("dominio", "cjf")
            if not dn:
                self._json(400, {"error": "dn requerido"}); return
            try:
                ok, err = desbloquear_ad(dn, dominio, sess)
                self._json(200, {"ok": ok, "error": err})
            except PermissionError as exc:
                self._json(403, {"error": str(exc), "need_auth": dominio})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/ad/forzar-cambio":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            dn = body.get("dn", "")
            dominio = body.get("dominio", "cjf")
            if not dn:
                self._json(400, {"error": "dn requerido"}); return
            try:
                ok, err = forzar_cambio_ad(dn, dominio, sess)
                self._json(200, {"ok": ok, "error": err})
            except PermissionError as exc:
                self._json(403, {"error": str(exc), "need_auth": dominio})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/ad/reset-masivo":
            sess = self._require_session()
            if not sess: return
            body = self._read_json()
            usuario = body.get("usuario", "").strip().lower()
            nueva_pass = body.get("nueva_pass", "")
            dominio = body.get("dominio", "cjf").strip().lower()
            forzar = bool(body.get("forzar", False))
            desbloquear = bool(body.get("desbloquear", False))
            if not usuario or not nueva_pass:
                self._json(400, {"error": "usuario y nueva_pass requeridos"}); return
            try:
                result = reset_masivo_ad(usuario, nueva_pass, dominio, sess, forzar, desbloquear)
                self._json(200, result)
            except PermissionError as exc:
                self._json(403, {"ok": False, "error": str(exc), "need_auth": dominio})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        # â”€â”€â”€ Endpoint nuevo: Inventario de equipos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if path == "/apiinventario-equipos":
            sess = self._require_session()
            if not sess:
                return

            body = self._read_json()
            sede = str(body.get("sede", "jalisco")).strip().lower()

            try:
                self._json(200, consultar_inventario(sess["creds"], sede))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


        # --- Escaneo por lista de IPs (agregado) ---
        if path == "/api/impresoras/ips/escanear":
            body = self._read_json()
            community = (body.get("community") or "public").strip() or "public"
            ips, invalidas = _parsear_ips(body.get("texto", ""))
            if not ips:
                self._json(400, {"error": "No se encontraron IPs validas en el texto pegado"}); return
            if len(ips) > 2000:
                self._json(400, {"error": "Maximo 2000 IPs por escaneo"}); return
            job_id = str(uuid.uuid4())
            ESCANEOS_IPS[job_id] = {"estado": "iniciando", "datos": [], "error": ""}
            hilo = threading.Thread(
                target=_ejecutar_escaneo_ips, args=(job_id, community, ips), daemon=True
            )
            hilo.start()
            self._json(200, {"job_id": job_id, "total": len(ips), "invalidas": invalidas})
            return

        if path == "/api/impresoras/escanear":
            body      = self._read_json()
            community = body.get("community", "public").strip() or "public"
            vlans     = body.get("vlans", ["100", "101", "102"])
            if not vlans:
                self._json(400, {"error": "Selecciona al menos una VLAN"}); return

            job_id = str(uuid.uuid4())
            ESCANEOS_IMPRESORAS[job_id] = {"estado": "iniciando", "datos": [], "error": ""}

            hilo = threading.Thread(
            target=_ejecutar_escaneo_impresoras, args=(job_id, community, vlans), daemon=True
        )
            hilo.start()

            self._json(200, {"job_id": job_id})
            return
        #_______________________________________________________________________

        self.send_error(404)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, filepath):
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _redirect(self, loc):
        self.send_response(301)
        self.send_header("Location", loc)
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f" {fmt % args}")


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True

    class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        pass

    HandlerConDir = functools.partial(Handler, directory=SERVE_DIR)
    with ThreadingServer(("", PORT), HandlerConDir) as httpd:
        print(f"\n Portal       -> http://localhost:{PORT}/DGTI_Zapopan/")
        print(f" Migracion    -> http://localhost:{PORT}/migracion-cjf/")
        print(f" GestorAD     -> http://localhost:{PORT}/gestor-ad/")
        print(f" ResetMasivo  -> http://localhost:{PORT}/reset-masivo/")
        print(f" Inventario   -> http://localhost:{PORT}/inventario-equipos/")
        print(f" Localizador -> http://localhost:{PORT}/localizador-ip/")
        print(f" HerrRed     -> http://localhost:{PORT}/herramientas-red/")
        print(f" AD CJF : {LDAP_SERVER}:{LDAP_PORT}")
        print(f" AD OAJ : {OAJ_SERVER}:{OAJ_PORT}")
        print(f" AD TDJ : {TDJ_SERVER}:{TDJ_PORT}")
        print(" Ctrl+C para detener\n")
        httpd.serve_forever()

