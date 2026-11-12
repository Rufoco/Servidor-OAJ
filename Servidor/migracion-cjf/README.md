# Migración de Usuarios CJF

Herramienta local para generar el archivo de migración `Detalle_User_CJF-OAJ.xlsx`
a partir de la base de datos del Active Directory de CJF.

## Estructura

```
migracion-cjf/
├── index.html          ← Abrir en Chrome o Edge
├── css/
│   └── styles.css      ← Estilos
└── js/
    ├── app.js          ← Lógica de la aplicación
    └── db.js           ← Base de datos embebida (AD → CJF)
```

## Uso

1. Abrir `index.html` en Chrome o Edge (doble clic)
2. Pegar la lista de nombres de cuenta — uno por línea
3. Clic en **Generar lista**
4. Clic en **Exportar Excel**

## Actualizar la base de datos

Cuando haya cambios en el AD, ejecutar el script de PowerShell para exportar
un nuevo CSV y solicitar la regeneración de `js/db.js`.

---
OAJ — Consejo de la Judicatura Federal
