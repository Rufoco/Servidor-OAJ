"""Servidor/inventario-equipos/inventario_backend.py
Inventario CJF/OAJ usando las credenciales de la sesión autenticada.
No guarda usuarios ni contraseñas en config.ini.

CORREGIDO: consultar_cjf ahora usa paginación LDAP (paged_search) para
evitar que Active Directory trunque los resultados en OUs grandes
(el límite administrativo por defecto suele ser ~1000 objetos por
búsqueda simple sin paginación).
"""
import configparser
import json
import os
import subprocess
import tempfile

SEDES_JALISCO = {
    "jalisco": {
        "nombre": "Todo Jalisco",
        "cjf_base": "OU=Jalisco,OU=FORANEOS,DC=cjf,DC=gob,DC=mx",
        "oaj_base": "OU=Jalisco,OU=Foraneos,DC=oaj,DC=gob,DC=mx",
    },
    "366": {
        "nombre": "366 Ciudad Judicial Periférico Poniente",
        "cjf_base": (
            "OU=366 Ciudad Judicial Periferico Pnoniente SN,"
            "OU=Jalisco,OU=FORANEOS,DC=cjf,DC=gob,DC=mx"
        ),
        "oaj_base": (
            "OU=366 Ciudad Judicial Periferico Pnoniente SN,"
            "OU=Jalisco,OU=Foraneos,DC=oaj,DC=gob,DC=mx"
        ),
    },
    "367": {
        "nombre": "367 Ciudad Judicial Periférico Poniente",
        "cjf_base": (
            "OU=367 Ciudad Judicial Periferico Pnoniente SN,"
            "OU=Jalisco,OU=FORANEOS,DC=cjf,DC=gob,DC=mx"
        ),
        "oaj_base": (
            "OU=367 Ciudad Judicial Periferico Pnoniente SN,"
            "OU=Jalisco,OU=Foraneos,DC=oaj,DC=gob,DC=mx"
        ),
    },
    "guadalajara": {
        "nombre": "Guadalajara",
        "cjf_base": (
            "OU=Guadalajara,OU=Jalisco,OU=FORANEOS,DC=cjf,DC=gob,DC=mx"
        ),
        "oaj_base": (
            "OU=Guadalajara,OU=Jalisco,OU=Foraneos,DC=oaj,DC=gob,DC=mx"
        ),
    },
    "puente-grande": {
        "nombre": "Puente Grande",
        "cjf_base": (
            "OU=Puente Grande,OU=Jalisco,OU=FORANEOS,DC=cjf,DC=gob,DC=mx"
        ),
        "oaj_base": (
            "OU=Puente Grande,OU=Jalisco,OU=Foraneos,DC=oaj,DC=gob,DC=mx"
        ),
    },
}

MODULO_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(MODULO_DIR, "config.ini")


def _config():
    cfg = configparser.ConfigParser()
    if not cfg.read(CONFIG_PATH, encoding="utf-8"):
        raise RuntimeError(f"No se encontró el archivo de configuración: {CONFIG_PATH}")
    return cfg


def _domain_data(cfg, section):
    try:
        return {
            "server": cfg[section]["server"].strip(),
            "port": int(cfg[section].get("port", "389")),
            "domain": cfg[section]["domain"].strip(),
            "searchbase": cfg[section]["searchbase"].strip(),
            "use_ssl": cfg[section].getboolean("use_ssl", fallback=False),
        }
    except KeyError as exc:
        raise RuntimeError(f"Falta la clave {exc} en la sección [{section}] de config.ini") from exc


def _counts(equipos):
    equipos = sorted(equipos, key=lambda item: item["nombre"].lower())
    total = len(equipos)
    win10 = sum("windows 10" in item["sistema"].lower() for item in equipos)
    win11 = sum("windows 11" in item["sistema"].lower() for item in equipos)
    return {
        "total": total,
        "win10": win10,
        "win11": win11,
        "otros": total - win10 - win11,
        "equipos": equipos,
    }


def consultar_cjf(datos, user, password):
    try:
        from ldap3 import ALL, NTLM, SUBTREE, Connection, Server
    except ImportError as exc:
        raise RuntimeError("Falta ldap3. Instálalo con: pip install ldap3") from exc

    server = Server(datos["server"], port=datos["port"], get_info=ALL,
                    use_ssl=datos.get("use_ssl", False))
    conn = Connection(
        server,
        user=f'{datos["domain"]}\\{user}',
        password=password,
        authentication=NTLM,
        auto_bind=True,
    )
    try:
        equipos = []
        # Paginación manual: sin esto, AD trunca resultados grandes
        # (límite administrativo típico de 1000 objetos por búsqueda simple).
        entry_generator = conn.extend.standard.paged_search(
            search_base=datos["searchbase"],
            search_filter="(objectCategory=computer)",
            search_scope=SUBTREE,
            attributes=["name", "operatingSystem"],
            paged_size=500,
            generator=True,
        )
        for entry in entry_generator:
            if entry.get("type") != "searchResEntry":
                continue
            attrs = entry.get("attributes", {})
            nombre = str(attrs.get("name") or "")
            sistema_raw = attrs.get("operatingSystem")
            if isinstance(sistema_raw, list):
                sistema_raw = sistema_raw[0] if sistema_raw else ""
            sistema = str(sistema_raw or "")
            equipos.append({"nombre": nombre, "sistema": sistema})
        return _counts(equipos)
    finally:
        conn.unbind()


def _run_powershell_json(script, env):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8")
    try:
        tmp.write("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n")
        tmp.write("$OutputEncoding = [System.Text.Encoding]::UTF8\n")
        tmp.write(script)
        tmp.close()
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", tmp.name],
            capture_output=True,
            timeout=120,
            env=env,
        )
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode != 0:
            raise RuntimeError(stderr or stdout or "Falló la consulta PowerShell de OAJ")
        if not stdout:
            raise RuntimeError(stderr or "OAJ no devolvió información")
        return json.loads(stdout)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def consultar_oaj(datos, user, password):
    script = r'''
$auth = [System.DirectoryServices.AuthenticationTypes]::Signing -bor `
        [System.DirectoryServices.AuthenticationTypes]::Sealing -bor `
        [System.DirectoryServices.AuthenticationTypes]::Secure
$credencial = $env:INV_DOMAIN + '\' + $env:INV_USERNAME
$baseDN = $env:INV_BASE

$entry = New-Object System.DirectoryServices.DirectoryEntry(
    "LDAP://$($env:INV_SERVER)/$baseDN", $credencial, $env:INV_PASSWORD, $auth
)

$search = New-Object System.DirectoryServices.DirectorySearcher($entry)
$search.Filter = '(objectCategory=computer)'
$search.PageSize = 500
$search.SizeLimit = 0
$null = $search.PropertiesToLoad.Add('name')
$null = $search.PropertiesToLoad.Add('operatingSystem')

$equipos = foreach ($result in $search.FindAll()) {
    $nombre = if ($result.Properties['name'].Count -gt 0) { [string]$result.Properties['name'][0] } else { '' }
    $sistema = if ($result.Properties['operatingSystem'].Count -gt 0) { [string]$result.Properties['operatingSystem'][0] } else { '' }
    [pscustomobject]@{ nombre = $nombre; sistema = $sistema }
}

if ($null -eq $equipos) {
    @() | ConvertTo-Json -Compress
} else {
    @($equipos) | ConvertTo-Json -Depth 3 -Compress
}
'''
    env = os.environ.copy()
    env.update({
        "INV_SERVER": datos["server"],
        "INV_DOMAIN": datos["domain"],
        "INV_USERNAME": user,
        "INV_PASSWORD": password,
        "INV_BASE": datos["searchbase"],
    })
    equipos = _run_powershell_json(script, env)
    if isinstance(equipos, dict):
        equipos = [equipos]
    normalizados = [
        {"nombre": str(equipo.get("nombre", "")), "sistema": str(equipo.get("sistema", ""))}
        for equipo in equipos
    ]
    return _counts(normalizados)


def consultar_inventario(creds, sede="jalisco"):
    """creds = {'cjf': {'user': '...', 'password': ...}, 'oaj': {...}}"""

    sede = str(sede).strip().lower()

    if sede not in SEDES_JALISCO:
        raise ValueError("Sede no válida")

    config_sede = SEDES_JALISCO[sede]
    cjf_base = config_sede["cjf_base"]
    oaj_base = config_sede["oaj_base"]

    cfg = _config()
    salida = {}

    for dominio, seccion, funcion in (
        ("cjf", "ldap", consultar_cjf),
        ("oaj", "ldap_oaj", consultar_oaj),
    ):
        credenciales = creds.get(dominio)
        if not credenciales:
            salida[dominio] = {
                "total": 0, "win10": 0, "win11": 0, "otros": 0, "equipos": [],
                "need_auth": dominio,
                "error": f"Inicia sesión también en {dominio.upper()} para consultar este dominio.",
            }
            continue
        try:
            base_ldap = cjf_base if dominio == "cjf" else oaj_base
            datos_dominio = _domain_data(cfg, seccion)
            datos_dominio["searchbase"] = base_ldap
            salida[dominio] = funcion(
                datos_dominio,
                credenciales["user"],
                credenciales["password"],
            )
        except Exception as exc:
            salida[dominio] = {
                "total": 0, "win10": 0, "win11": 0, "otros": 0, "equipos": [],
                "error": str(exc),
            }

    return salida
