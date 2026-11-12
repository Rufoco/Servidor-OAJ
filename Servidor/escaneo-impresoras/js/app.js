// escaneo-impresoras/js/app.js

const btnEscanear = document.getElementById("btnEscanear");
const btnExportar = document.getElementById("btnExportar");
const divEstado   = document.getElementById("estado");
const tabla       = document.getElementById("tablaResultados");
const tbody       = tabla.querySelector("tbody");
const barraCont   = document.getElementById("barraContenedor");
const barra       = document.getElementById("barraProgreso");
const checksVlan  = document.querySelectorAll(".chk-vlan input[type=checkbox]");

let datosActuales    = [];
let intervaloPolling = null;

btnEscanear.addEventListener("click", iniciarEscaneo);
btnExportar.addEventListener("click", exportarExcel);

// ── Tema oscuro/claro (mismo patrón que gestor-ad: icono SVG sol/luna) ─────
let temaOscuro = (localStorage.getItem("tema") || "dark") === "dark";

function tTheme() {
  temaOscuro = !temaOscuro;
  document.documentElement.setAttribute("data-theme", temaOscuro ? "dark" : "light");
  localStorage.setItem("tema", temaOscuro ? "dark" : "light");
  actualizarIconoTema();
}

function actualizarIconoTema() {
  const icono = document.getElementById("tico");
  if (!icono) return;
  icono.innerHTML = temaOscuro
    ? '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'
    : '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>';
}

// Sincroniza el ícono con el tema ya aplicado al cargar la página
actualizarIconoTema();

// Se llama desde el atributo onclick del botón en index.html
window.tTheme = tTheme;

// ── VLANs seleccionadas ───────────────────────────────────────────────────
function vlansSeleccionadas() {
  return Array.from(checksVlan).filter(c => c.checked).map(c => c.value);
}

// ── Escaneo ───────────────────────────────────────────────────────────────
async function iniciarEscaneo() {
  const community = document.getElementById("community").value.trim() || "public";
  const vlans = vlansSeleccionadas();

  if (vlans.length === 0) {
    divEstado.textContent = "Selecciona al menos una VLAN.";
    return;
  }

  btnEscanear.disabled = true;
  btnExportar.disabled = true;
  tabla.style.display = "none";
  tbody.innerHTML = "";
  barraCont.style.display = "block";
  barra.style.width = "0%";
  divEstado.textContent = "Iniciando escaneo...";

  try {
    const resp = await fetch("/api/impresoras/escanear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ community, vlans }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      divEstado.textContent = "No se pudo iniciar el escaneo: " + (err.error || resp.statusText);
      barraCont.style.display = "none";
      btnEscanear.disabled = false;
      return;
    }

    const { job_id } = await resp.json();

    // Chequeo inmediato para no esperar los 2s del primer intervalo
    await consultarEstado(job_id);
    intervaloPolling = setInterval(() => consultarEstado(job_id), 2000);
  } catch (e) {
    divEstado.textContent = "Error de conexión al iniciar el escaneo.";
    barraCont.style.display = "none";
    btnEscanear.disabled = false;
  }
}

async function consultarEstado(jobId) {
  try {
    const resp = await fetch(`/api/impresoras/estado?job_id=${jobId}`);
    const data = await resp.json();

    if (data.estado === "corriendo" || data.estado === "iniciando") {
      actualizarBarra(data);
      return;
    }

    clearInterval(intervaloPolling);
    btnEscanear.disabled = false;

    if (data.estado === "error") {
      divEstado.textContent = "Error durante el escaneo: " + data.error;
      barraCont.style.display = "none";
      return;
    }

    if (data.estado === "listo") {
      barra.style.width = "100%";
      await cargarResultado(jobId);
    }
  } catch (e) {
    // Si falla un poll puntual, no tumbamos el intervalo — se reintenta en el siguiente ciclo.
  }
}

function actualizarBarra(data) {
  const total     = data.ips_totales || 0;
  const revisadas = data.ips_revisadas || 0;
  const pct = total > 0 ? Math.min(100, Math.round((revisadas / total) * 100)) : 0;

  barra.style.width = pct + "%";
  divEstado.textContent =
    `Escaneando VLAN ${data.vlan_actual || "..."} (IP ${data.ip_actual || "..."}) — ` +
    `${revisadas}/${total} IPs revisadas (${pct}%) — ${data.impresoras_encontradas || 0} impresoras encontradas hasta ahora.`;
}

async function cargarResultado(jobId) {
  const resp = await fetch(`/api/impresoras/resultado?job_id=${jobId}`);
  const data = await resp.json();
  datosActuales = data.datos || [];
  barraCont.style.display = "none";

  if (datosActuales.length === 0) {
    divEstado.textContent = "Escaneo terminado. No se encontraron impresoras con SNMP activo.";
    return;
  }

  divEstado.textContent = `Escaneo terminado. ${datosActuales.length} impresoras encontradas.`;
  renderizarTabla(datosActuales);
  btnExportar.disabled = false;
}

function renderizarTabla(filas) {
  tbody.innerHTML = "";
  filas.forEach((f) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${f.VLAN ?? ""}</td>
      <td>${f.IP ?? ""}</td>
      <td>${f.Nombre_Red ?? f.NombreRed ?? ""}</td>
      <td>${f.Modelo_Marca ?? f.ModeloMarca ?? ""}</td>
      <td>${f.NumeroSerie ?? ""}</td>
      <td>${f.FechaEscaneo ?? ""}</td>
    `;
    tbody.appendChild(tr);
  });
  tabla.style.display = "table";
}

function exportarExcel() {
  if (datosActuales.length === 0) return;
  const hoja  = XLSX.utils.json_to_sheet(datosActuales);
  const libro = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(libro, hoja, "Impresoras");
  const fecha = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(libro, `InventarioImpresoras_${fecha}.xlsx`);
}
