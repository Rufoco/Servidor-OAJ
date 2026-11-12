// escaneo-impresoras/js/rangos.js
// Pestaña "Lista de IPs": pegar IPs, escanearlas y exportar a Excel.
(function () {
  const $ = (id) => document.getElementById(id);

  const txt       = $("txtRango");
  const contador  = $("contRango");
  const btnEsc    = $("btnEscanearRango");
  const btnLimp   = $("btnLimpiarRango");
  const btnExp    = $("btnExportarRango");
  const barraCont = $("barraContenedorRango");
  const barra     = $("barraProgresoRango");
  const estado    = $("estadoRango");
  const tabla     = $("tablaRango");
  const tbody     = tabla.querySelector("tbody");

  let datos = [];
  let intervalo = null;
  let consultando = false;

  // ── Análisis del texto pegado ───────────────────────────────
  const RE_IP = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;

  function analizar(texto) {
    const vistas = new Set();
    const validas = [];
    const invalidas = [];
    let duplicadas = 0;
    texto.split(/[\s,;]+/).forEach((tk) => {
      if (!tk) return;
      if (!RE_IP.test(tk)) { invalidas.push(tk); return; }
      if (vistas.has(tk)) { duplicadas++; return; }
      vistas.add(tk);
      validas.push(tk);
    });
    return { validas, invalidas, duplicadas };
  }

  function actualizarContador() {
    const { validas, invalidas, duplicadas } = analizar(txt.value);
    let msg = `${validas.length} IP${validas.length === 1 ? "" : "s"} válida${validas.length === 1 ? "" : "s"}`;
    if (duplicadas) msg += ` · ${duplicadas} repetida${duplicadas === 1 ? "" : "s"} (se ignora)`;
    if (invalidas.length) msg += ` · ${invalidas.length} no válida${invalidas.length === 1 ? "" : "s"} (se ignora)`;
    contador.textContent = msg;
  }
  txt.addEventListener("input", actualizarContador);

  const inicio = $("rangoInicio"), fin = $("rangoFin");
  function numeroIP(valor) {
    if (!RE_IP.test(valor)) throw new Error("Introduce dos direcciones IPv4 válidas, sin ceros iniciales.");
    return valor.split(".").reduce((n, p) => n * 256 + Number(p), 0);
  }
  function generarRango() {
    const a = numeroIP(inicio.value.trim()), b = numeroIP(fin.value.trim());
    if (b < a) throw new Error("La IP final no puede ser menor que la inicial.");
    const total = b - a + 1;
    if (total > 2000) throw new Error(`El rango tiene ${total} IPs. El máximo es 2000.`);
    const lista = [];
    for (let n = a; n <= b; n++) {
      lista.push([Math.floor(n / 16777216), Math.floor(n / 65536) % 256, Math.floor(n / 256) % 256, n % 256].join("."));
    }
    txt.value = lista.join("\n");
    contador.textContent = `${total} IPs en el rango (incluye ambos extremos).`;
  }
  function contarRango() {
    txt.value = "";
    if (!inicio.value.trim() || !fin.value.trim()) {
      contador.textContent = "Introduce IP inicial e IP final."; return;
    }
    try { generarRango(); } catch (e) { contador.textContent = e.message; }
  }
  inicio.addEventListener("input", contarRango);
  fin.addEventListener("input", contarRango);
  contarRango();

  // ── Utilidades ──────────────────────────────────────────────
  function esc(valor) {
    return String(valor ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function insigniaEstado(e) {
    const clase = e === "OK" ? "bok" : (e === "Sin datos SNMP" ? "bwrn" : "boff");
    return `<span class="badge ${clase}">${esc(e)}</span>`;
  }

  // ── Escaneo ─────────────────────────────────────────────────
  async function iniciar() {
    try { generarRango(); } catch (e) { estado.textContent = e.message; return; }
    const { validas, invalidas } = analizar(txt.value);
    if (validas.length === 0) {
      estado.textContent = "Pega al menos una IP válida.";
      return;
    }

    btnEsc.disabled = true;
    btnLimp.disabled = true;
    btnExp.disabled = true;
    tabla.style.display = "none";
    tbody.innerHTML = "";
    barraCont.style.display = "block";
    barra.style.width = "0%";
    estado.textContent = `Iniciando escaneo de ${validas.length} IPs...`;

    const community = $("communityRango").value.trim() || "public";

    try {
      const resp = await fetch("/api/impresoras/ips/escanear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ community, texto: txt.value }),
      });
      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        estado.textContent = "No se pudo iniciar el escaneo: " + (data.error || resp.statusText);
        terminarUI(false);
        return;
      }

      const aviso = invalidas.length ? ` (se ignoraron ${invalidas.length} entradas no válidas)` : "";
      estado.textContent = `Escaneando ${data.total} IPs${aviso}...`;

      intervalo = setInterval(() => consultar(data.job_id), 1500);
      await consultar(data.job_id);
    } catch (e) {
      estado.textContent = "Error de conexión al iniciar el escaneo.";
      terminarUI(false);
    }
  }

  function terminarUI(ocultarBarra) {
    clearInterval(intervalo);
    btnEsc.disabled = false;
    btnLimp.disabled = false;
    if (ocultarBarra !== false) barraCont.style.display = "none";
    else barraCont.style.display = "none";
  }

  async function consultar(jobId) {
    if (consultando) return;
    consultando = true;
    try {
      const resp = await fetch(`/api/impresoras/ips/estado?job_id=${jobId}`);
      const d = await resp.json();

      if (d.estado === "corriendo" || d.estado === "iniciando") {
        pintarProgreso(d);
        return;
      }

      terminarUI();

      if (d.estado === "error") {
        estado.textContent = "Error durante el escaneo: " + d.error;
        return;
      }
      if (d.estado === "listo") {
        barra.style.width = "100%";
        await cargarResultado(jobId);
        return;
      }
      estado.textContent = "El escaneo ya no existe en el servidor (¿se reinició el servicio?). Vuelve a intentarlo.";
    } catch (e) {
      // un fallo puntual no cancela el sondeo
    } finally {
      consultando = false;
    }
  }

  function pintarProgreso(d) {
    const de = d.de || 0;
    const hecho = d.hecho || 0;
    let pct = 0;
    let detalle = "Preparando escaneo...";

    if (d.fase === "ping") {
      pct = de ? Math.round((hecho / de) * 60) : 0;
      detalle = `Fase 1: buscando equipos activos (${hecho}/${de})`;
    } else if (d.fase === "snmp") {
      pct = de ? 60 + Math.round((hecho / de) * 40) : 60;
      detalle = `Fase 2: consultando SNMP en ${d.ip_actual || "..."} (${hecho}/${de}) — ${d.impresoras_encontradas || 0} impresoras con datos`;
    }
    barra.style.width = Math.min(100, pct) + "%";
    estado.textContent = `${detalle} — ${Math.min(100, pct)}%`;
  }

  async function cargarResultado(jobId) {
    const resp = await fetch(`/api/impresoras/ips/resultado?job_id=${jobId}`);
    const r = await resp.json();
    datos = r.datos || [];

    const ok = datos.filter((f) => f.Estado === "OK").length;
    const sinSnmp = datos.filter((f) => f.Estado === "Sin datos SNMP").length;
    const sinPing = datos.filter((f) => f.Estado === "Sin respuesta (ping)").length;

    estado.textContent =
      `Escaneo terminado. ${datos.length} IPs: ${ok} con datos de impresora, ` +
      `${sinSnmp} responden pero sin datos SNMP, ${sinPing} sin respuesta.`;

    tbody.innerHTML = "";
    datos.forEach((f) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(f.VLAN)}</td>
        <td>${esc(f.IP)}</td>
        <td>${esc(f.Nombre_Red)}</td>
        <td>${esc(f.Modelo_Marca)}</td>
        <td>${esc(f.NumeroSerie)}</td>
        <td>${insigniaEstado(f.Estado)}</td>
        <td>${esc(f.FechaEscaneo)}</td>`;
      tbody.appendChild(tr);
    });
    tabla.style.display = datos.length ? "table" : "none";
    btnExp.disabled = datos.length === 0;
  }

  // ── Exportar ────────────────────────────────────────────────
  function exportar() {
    if (datos.length === 0) return;
    const hoja = XLSX.utils.json_to_sheet(datos);
    const libro = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(libro, hoja, "Impresoras");
    const fecha = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(libro, `InventarioImpresoras_Rango_${fecha}.xlsx`);
  }

  function limpiar() {
    txt.value = "";
    inicio.value = ""; fin.value = ""; contarRango();
    tabla.style.display = "none";
    tbody.innerHTML = "";
    estado.textContent = "";
    datos = [];
    btnExp.disabled = true;
  }

  btnEsc.addEventListener("click", iniciar);
  btnLimp.addEventListener("click", limpiar);
  btnExp.addEventListener("click", exportar);
})();
