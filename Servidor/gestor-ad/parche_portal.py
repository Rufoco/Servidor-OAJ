# -*- coding: utf-8 -*-
"""Parche: agrega el boton "Portal DGTI" al header del Gestor AD.
Uso: python parche_portal.py [ruta\index.html]   (por defecto ./index.html)
Crea una copia index.html.bak antes de modificar.
"""
import sys, shutil, os

ruta = sys.argv[1] if len(sys.argv) > 1 else "index.html"
if not os.path.exists(ruta):
    sys.exit("No se encontro: " + ruta)

with open(ruta, encoding="utf-8") as f:
    html = f.read()

if "bportal" in html:
    sys.exit("El parche ya estaba aplicado. No se hizo ningun cambio.")

CSS = (
    ".bportal{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;"
    "background:var(--surface2);border:1px solid var(--border);border-radius:var(--r);"
    "color:var(--muted);font-size:12px;font-weight:600;text-decoration:none;white-space:nowrap;"
    "transition:background var(--t),color var(--t),border-color var(--t)}\n"
    ".bportal:hover{color:var(--text);border-color:var(--primary)}\n"
    "@media(max-width:768px){.bportal .bptxt{display:none}.bportal{padding:6px 9px}}\n"
)
LINK = ('<a class="bportal" href="/DGTI_Zapopan/" title="Volver al portal DGTI">'
        '&larr; <span class="bptxt">Portal DGTI</span></a>\n')

if "</style>" not in html:
    sys.exit("No se encontro </style>. Revisa el archivo.")
if '<div class="husr">' not in html:
    sys.exit('No se encontro <div class="husr"> en el header. Revisa el archivo.')

shutil.copy(ruta, ruta + ".bak")
html = html.replace("</style>", CSS + "</style>", 1)
html = html.replace('<div class="husr">', LINK + '<div class="husr">', 1)

with open(ruta, "w", encoding="utf-8") as f:
    f.write(html)
print("Listo. Boton agregado. Respaldo en " + ruta + ".bak")
