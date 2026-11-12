#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# diagnostico_sasi.py  -  Descubre como SASI sirve los datos de reportes
#
#   Ejecutalo en el MISMO servidor del portal, con Python 3.11:
#
#       python diagnostico_sasi.py TU_USUARIO TU_PASSWORD
#
#   Ej:  python diagnostico_sasi.py acorreab "Frank*1202*"
#
#   No modifica nada de SASI: solo lee. Pega TODA la salida en el chat.
# ============================================================================

import sys
import re
import json
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    raise SystemExit("Falta 'requests'. Ejecuta: pip install requests")

BASE       = "http://10.2.171.6/sasi/"
LOGIN_URL  = BASE + "app/login.php"
SM_URL     = BASE + "sm.php"

# Posibles nombres de campo del formulario de login (probamos varios)
LOGIN_FIELD_SETS = [
    {"usuario": "{u}", "password": "{p}"},
    {"usuario": "{u}", "pass": "{p}"},
    {"user": "{u}",    "password": "{p}"},
    {"txt_usuario": "{u}", "txt_password": "{p}"},
    {"usuario": "{u}", "contrasena": "{p}"},
]


def sep(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main():
    if len(sys.argv) < 3:
        print("Uso: python diagnostico_sasi.py USUARIO PASSWORD")
        sys.exit(1)
    user = sys.argv[1]
    pwd  = sys.argv[2]

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })

    # ----------------------------------------------------------------- 1) LOGIN
    sep("1) DESCUBRIENDO EL FORMULARIO DE LOGIN")
    try:
        rg = s.get(LOGIN_URL, timeout=30)
        print(f"GET {LOGIN_URL} -> HTTP {rg.status_code}")
        # extraer los name= de los inputs del formulario
        inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*>', rg.text, re.I)
        forms  = re.findall(r'<form[^>]*action=["\']([^"\']*)["\']', rg.text, re.I)
        print(f"Inputs detectados en el form de login: {inputs}")
        print(f"Action(s) del form: {forms}")
    except Exception as e:
        print(f"No se pudo leer el form de login: {e}")

    sep("2) PROBANDO INICIAR SESION")
    logged = False
    for fields in LOGIN_FIELD_SETS:
        data = {k: v.format(u=user, p=pwd) for k, v in fields.items()}
        try:
            r = s.post(LOGIN_URL, data=data, timeout=30, allow_redirects=True)
            final = r.url
            ok = "login.php" not in final.lower()
            print(f"  campos={list(fields.keys())} -> HTTP {r.status_code} | URL final: {final} | "
                  f"{'OK SESION' if ok else 'rebotado a login'}")
            cookies = s.cookies.get_dict()
            if cookies:
                print(f"    cookies: {list(cookies.keys())}")
            if ok and cookies:
                logged = True
                print(f"  >>> LOGIN EXITOSO con campos: {list(fields.keys())}")
                break
        except Exception as e:
            print(f"  campos={list(fields.keys())} -> ERROR {e}")

    if not logged:
        print("\n>>> No se logro iniciar sesion automaticamente. "
              "Revisa los 'Inputs detectados' arriba y dime cuales son.")
        # seguimos de todos modos por si la cookie ya basta

    # ----------------------------------------------------------- 3) LEER sm.php
    sep("3) DESCARGANDO sm.php Y BUSCANDO LOS JS QUE CARGA")
    try:
        r = s.get(SM_URL, timeout=30)
        print(f"GET {SM_URL} -> HTTP {r.status_code} | bytes={len(r.text)}")
        if "login.php" in r.url.lower():
            print(">>> sm.php redirigio a login: la sesion NO quedo activa.")
        scripts = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', r.text, re.I)
        # nos interesan los .js locales (no CDNs)
        locales = [sc for sc in scripts if not sc.startswith("http") and sc.lower().endswith(".js")]
        print(f"Scripts JS locales referenciados: {locales}")
        sm_html = r.text
    except Exception as e:
        print(f"Error leyendo sm.php: {e}")
        locales, sm_html = [], ""

    # --------------------------------------------- 4) BUSCAR EL AJAX EN LOS JS
    sep("4) BUSCANDO LA PETICION AJAX QUE LLENA LA TABLA (DataTables)")
    candidatos_url = set()
    for js in locales:
        full = urljoin(SM_URL, js)
        try:
            rj = s.get(full, timeout=30)
            if rj.status_code != 200:
                print(f"  {js} -> HTTP {rj.status_code} (omitido)")
                continue
            txt = rj.text
            print(f"\n  --- {js} ({len(txt)} bytes) ---")
            # patrones comunes de DataTables / jQuery ajax
            for pat in [
                r'ajax\s*:\s*["\']([^"\']+)["\']',
                r'ajax\s*:\s*\{[^}]*url\s*:\s*["\']([^"\']+)["\']',
                r'url\s*:\s*["\']([^"\']+\.php[^"\']*)["\']',
                r'\$\.(?:get|post|getJSON)\s*\(\s*["\']([^"\']+)["\']',
                r'load\s*\(\s*["\']([^"\']+\.php[^"\']*)["\']',
            ]:
                for m in re.findall(pat, txt, re.I):
                    candidatos_url.add(m)
                    print(f"    AJAX/URL encontrada: {m}")
            # mostrar tambien como define columnas (pistas de nombres)
            cols = re.findall(r'(?:data|mData)\s*:\s*["\']([^"\']+)["\']', txt)
            if cols:
                print(f"    columnas (data:) -> {cols[:20]}")
        except Exception as e:
            print(f"  {js} -> ERROR {e}")

    if not candidatos_url:
        print("\n  No se hallaron URLs ajax en los JS. Buscando en el HTML de sm.php...")
        for m in re.findall(r'["\']([^"\']+\.php[^"\']*)["\']', sm_html):
            candidatos_url.add(m)
        print(f"  Posibles .php en sm.php: {sorted(candidatos_url)[:30]}")

    # ----------------------------------------- 5) LLAMAR A CADA URL CANDIDATA
    sep("5) PROBANDO CADA URL CANDIDATA (que devuelve cada una)")
    for u in sorted(candidatos_url):
        full = urljoin(SM_URL, u)
        # solo probamos GET simple; mostramos el inicio de la respuesta
        try:
            rr = s.get(full, timeout=30)
            ct = rr.headers.get("Content-Type", "")
            body = rr.text.strip()
            head = body[:400].replace("\n", " ")
            print(f"\n  GET {full}")
            print(f"    HTTP {rr.status_code} | Content-Type: {ct} | bytes={len(body)}")
            print(f"    inicio: {head}")
            # si parece JSON, intentar parsear y mostrar estructura
            if body[:1] in "[{":
                try:
                    j = rr.json()
                    fila = None
                    if isinstance(j, dict):
                        print(f"    JSON dict keys: {list(j.keys())}")
                        if "data" in j and isinstance(j["data"], list) and j["data"]:
                            fila = j["data"][0]
                    elif isinstance(j, list) and j:
                        print(f"    JSON list, {len(j)} items.")
                        fila = j[0]
                    if isinstance(fila, dict):
                        print("    >>> TODAS las claves del primer registro (mapa columna -> valor):")
                        for k, v in fila.items():
                            vs = str(v)
                            if len(vs) > 90:
                                vs = vs[:90] + "..."
                            print(f"        {k!r:>22} = {vs}")
                except Exception as e:
                    print(f"    (no se pudo parsear JSON: {e})")
        except Exception as e:
            print(f"  GET {full} -> ERROR {e}")

    sep("FIN DEL DIAGNOSTICO  -  pega TODA esta salida en el chat")


if __name__ == "__main__":
    main()
