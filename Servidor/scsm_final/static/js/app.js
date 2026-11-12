/* ===========================================================================
   Mis Reportes — SCSM · app.js  v6
   Filtros de estado: Todos | Abierto | Pendiente | En Progreso |
                      Resuelto | Cerrado | Cancelado
   =========================================================================== */
"use strict";

/* ─── Estado en memoria ─── */
const state = {
  token:   null,
  user:    "",
  display: "",
  all:     [],
  tab:     "all",       // all | Incidente | Solicitud
  status:  "all",       // all | abierto | pendiente | enprogreso | resuelto | cerrado | cancelado
  query:   "",
  selected: new Set(),
  detail:  null,
};

/* ─── DOM helpers ─── */
const $ = (id) => document.getElementById(id);
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])
  );

/* ─── API client ─── */
async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch(path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { ok: false, error: text }; }
  if (!res.ok) throw new Error(data.error || "HTTP " + res.status);
  return data;
}

/* ─── Tema ─── */
(function () {
  const html = document.documentElement;
  const btn  = document.querySelector("[data-theme-toggle]");
  let theme  = matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light";
  html.setAttribute("data-theme", theme);
  function updateIcon() {
    if (!btn) return;
    btn.innerHTML = theme === "dark"
      ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`
      : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  }
  updateIcon();
  if (btn) btn.addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    html.setAttribute("data-theme", theme);
    btn.setAttribute("aria-label", "Cambiar a modo " + (theme === "dark" ? "claro" : "oscuro"));
    updateIcon();
  });
})();

/* ─── Clasificación de estado ─── */
const STATUS_MAP = [
  { key: "abierto",    label: "Abierto",     re: /\babierto\b/i,                            cls: "badge warn"    },
  { key: "pendiente",  label: "Pendiente",   re: /\bpendiente\b/i,                          cls: "badge orange"  },
  { key: "enprogreso", label: "En Progreso", re: /(en\s*progreso|progress|asignado|trabaj|activo)/i, cls: "badge blue"  },
  { key: "resuelto",   label: "Resuelto",    re: /(resuel|completado|resolved|completed)/i, cls: "badge ok"      },
  { key: "cerrado",    label: "Cerrado",     re: /\bcerrado\b/i,                            cls: "badge gray"    },
  { key: "cancelado",  label: "Cancelado",   re: /\bcancelado\b/i,                          cls: "badge canceled"},
];

function getStatusKey(estado = "") {
  for (const s of STATUS_MAP) { if (s.re.test(estado)) return s.key; }
  return "abierto"; // default
}
function badgeClass(estado = "") {
  for (const s of STATUS_MAP) { if (s.re.test(estado)) return s.cls; }
  return "badge warn";
}

/* ─── Flash ─── */
function flash(msg, type = "ok") {
  const el = $("flash");
  if (!msg) { el.className = "flash"; el.textContent = ""; return; }
  el.className = "flash show " + type;
  el.textContent = msg;
  if (type === "ok") setTimeout(() => flash(""), 4000);
}
function loginErr(msg) {
  const el = $("loginErr");
  if (!msg) { el.className = "login-err"; el.textContent = ""; return; }
  el.className = "login-err show"; el.textContent = msg;
}

/* ─── Login / Logout ─── */
async function doLogin() {
  loginErr("");
  const dominio  = $("inDom").value;
  const user     = $("inUser").value.trim();
  const password = $("inPass").value;
  if (!user || !password) { loginErr("Usuario y contraseña requeridos."); return; }
  const btn = $("btnLogin");
  btn.disabled = true; btn.textContent = "Entrando…";
  try {
    const r = await api("/api/login", { method: "POST", body: { dominio, user, password } });
    if (!r.ok) throw new Error(r.error || "Credenciales incorrectas.");
    state.token   = r.token;
    state.user    = r.user    || user;
    state.display = r.display || `${dominio.toUpperCase()}\\${user}`;
    $("inPass").value = "";
    showApp();
    await loadData();
  } catch (e) { loginErr(e.message); }
  finally { btn.disabled = false; btn.textContent = "Entrar"; }
}

async function doLogout() {
  try { await api("/api/logout", { method: "POST", body: {} }); } catch {}
  Object.assign(state, { token: null, user: "", display: "", all: [], tab: "all", status: "all", query: "" });
  state.selected.clear(); state.detail = null;
  closeDrawer();
  $("app").classList.add("hidden");
  $("loginWrap").classList.remove("hidden");
}

function showApp() {
  $("loginWrap").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("userBadge").textContent = state.display;
}

/* ─── Carga ─── */
async function loadData() {
  flash(""); toggleLoading(true);
  try {
    const [inc, sol] = await Promise.all([
      api("/api/scsm/incidentes",  { method: "POST", body: { username: state.user } }),
      api("/api/scsm/solicitudes", { method: "POST", body: { username: state.user } }),
    ]);
    const incidentes  = (inc.incidentes  || []).map(r => ({ ...r, Tipo: r.Tipo || "Incidente" }));
    const solicitudes = (sol.solicitudes || []).map(r => ({ ...r, Tipo: r.Tipo || "Solicitud" }));
    state.all = [...incidentes, ...solicitudes];
    state.selected.clear();
    renderKPIs(); renderStatusTabs(); renderTable();
  } catch (e) {
    flash("⚠ " + e.message, "err");
    state.all = []; renderKPIs(); renderStatusTabs(); renderTable();
  } finally { toggleLoading(false); }
}

function toggleLoading(on) {
  $("tableLoading").classList.toggle("hidden", !on);
  if (on) { $("tableEmpty").classList.add("hidden"); $("tableBody").innerHTML = ""; }
}

/* ─── KPIs ─── */
function renderKPIs() {
  const all  = state.all;
  const byStatus = (key) => all.filter(r => getStatusKey(r.Estado) === key).length;
  $("kpiTotal").textContent     = all.length;
  $("kpiAbierto").textContent   = byStatus("abierto");
  $("kpiPendiente").textContent = byStatus("pendiente");
  $("kpiEnProg").textContent    = byStatus("enprogreso");
  $("kpiResuelto").textContent  = byStatus("resuelto");
  $("kpiCerrado").textContent   = byStatus("cerrado") + byStatus("cancelado");
  $("kpiInc").textContent       = all.filter(r => r.Tipo === "Incidente").length;
  $("kpiSol").textContent       = all.filter(r => r.Tipo === "Solicitud").length;
}

/* ─── Status tabs dinámicos ─── */
function renderStatusTabs() {
  const counts = {};
  for (const s of STATUS_MAP) counts[s.key] = 0;
  counts["all"] = state.all.length;
  for (const r of state.all) { const k = getStatusKey(r.Estado); if (k in counts) counts[k]++; }

  const container = $("statusTabs");
  const tabs = [
    { key: "all",        label: "Todos"       },
    { key: "abierto",    label: "Abierto"     },
    { key: "pendiente",  label: "Pendiente"   },
    { key: "enprogreso", label: "En Progreso" },
    { key: "resuelto",   label: "Resuelto"    },
    { key: "cerrado",    label: "Cerrado"     },
    { key: "cancelado",  label: "Cancelado"   },
  ];
  container.innerHTML = tabs.map(t => {
    const active = state.status === t.key ? " active" : "";
    const n = counts[t.key] ?? 0;
    return `<button class="stab${active}" onclick="setStatus('${t.key}', this)">
      ${t.label} <span class="stab-count">${n}</span>
    </button>`;
  }).join("");
}

/* ─── Filtro combinado ─── */
function filteredRows() {
  const q = state.query.toLowerCase().trim();
  return state.all.filter(r => {
    const matchType   = state.tab === "all" ? true : r.Tipo === state.tab;
    const matchStatus = state.status === "all" ? true : getStatusKey(r.Estado) === state.status;
    const matchQ      = !q || [r.Id, r.Titulo, r.Descripcion, r.Estado, r.Asignado, r.UsuarioAfectado]
                               .join(" ").toLowerCase().includes(q);
    return matchType && matchStatus && matchQ;
  });
}

/* ─── Render tabla ─── */
function renderTable() {
  const rows  = filteredRows();
  const tbody = $("tableBody");
  $("tableEmpty").classList.toggle("hidden", rows.length > 0);
  tbody.innerHTML = rows.map(r => {
    const checked  = state.selected.has(r.Id) ? "checked" : "";
    const typePill = r.Tipo === "Incidente"
      ? `<span class="type-pill type-inc">INC</span>`
      : `<span class="type-pill type-sol">SOL</span>`;
    return `<tr>
      <td class="col-check"><input type="checkbox" ${checked} data-id="${esc(r.Id)}" onchange="toggleRow(this)"></td>
      <td><div class="cell-id">${esc(r.Id)}</div></td>
      <td>
        <div class="cell-title">${esc(r.Titulo || r.Descripcion)}</div>
        <div class="cell-meta">${esc(r.UsuarioAfectado || r.Asignado || "")}</div>
      </td>
      <td><span class="${badgeClass(r.Estado)}">${esc(r.Estado || "–")}</span></td>
      <td>${typePill}</td>
      <td class="col-date">${esc(r.FechaModif || r.FechaCreacion || "")}</td>
      <td class="col-actions"><button class="link-btn" onclick="openDetail('${esc(r.Id)}')">Ver →</button></td>
    </tr>`;
  }).join("");

  const total = rows.length;
  const selInView = rows.filter(r => state.selected.has(r.Id)).length;
  const ca = $("checkAll");
  ca.checked       = total > 0 && selInView === total;
  ca.indeterminate = selInView > 0 && selInView < total;
}

/* ─── Selección ─── */
function toggleRow(cb) {
  const id = cb.dataset.id;
  if (cb.checked) state.selected.add(id); else state.selected.delete(id);
  updateBulkBar(); renderTable();
}
function toggleAll(cb) {
  filteredRows().forEach(r => { if (cb.checked) state.selected.add(r.Id); else state.selected.delete(r.Id); });
  updateBulkBar(); renderTable();
}
function clearSelection() { state.selected.clear(); updateBulkBar(); renderTable(); }
function updateBulkBar() {
  const n   = state.selected.size;
  const bar = $("bulkBar");
  if (n === 0) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  $("bulkCount").textContent = n + (n === 1 ? " seleccionado" : " seleccionados");
}

$("bulkAction") && $("bulkAction").addEventListener("change", function () {
  const show = this.value === "comentar";
  $("bulkComment").classList.toggle("hidden", !show);
});

/* ─── Acción masiva ─── */
async function doBulkAction() {
  const accion  = $("bulkAction").value;
  const texto   = $("bulkComment").value.trim();
  const ids     = [...state.selected];
  if (!accion)    { flash("Selecciona una acción.", "err"); return; }
  if (!ids.length){ flash("Selecciona al menos un reporte.", "err"); return; }
  if (accion === "comentar" && !texto) { flash("Escribe un comentario.", "err"); return; }
  const conf = accion === "close"
    ? confirm(`¿Cerrar ${ids.length} reporte(s)?`)
    : true;
  if (!conf) return;
  flash("Procesando…");
  try {
    const r = await api("/api/scsm/accion-masiva", { method: "POST", body: { ids, accion, texto } });
    if (!r.ok) throw new Error(r.error || "Error en acción masiva");
    flash(`✓ ${r.procesados} reporte(s) procesados.`);
    clearSelection(); await loadData();
  } catch (e) { flash("⚠ " + e.message, "err"); }
}

/* ─── Tabs tipo / estado ─── */
function setTab(tab, el) {
  state.tab = tab;
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  if (el) el.classList.add("active");
  renderTable();
}
function setStatus(key, el) {
  state.status = key;
  document.querySelectorAll(".stab").forEach(t => t.classList.remove("active"));
  if (el) el.classList.add("active");
  renderTable();
}
function setQuery(q) { state.query = q; renderTable(); }

/* KPI clickeable → activa filtro */
function kpiClick(statusKey) {
  state.status = statusKey;
  state.tab    = "all";
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  $("tabAll") && $("tabAll").classList.add("active");
  renderStatusTabs(); renderTable();
}

/* ─── Detalle (drawer) ─── */
async function openDetail(id) {
  state.detail = id;
  $("drawerLoading").classList.remove("hidden");
  $("drawerContent").classList.add("hidden");
  $("overlay").classList.add("show");
  $("drawer").classList.add("show");
  document.body.style.overflow = "hidden";
  try {
    const r = await api("/api/scsm/reporte", { method: "POST", body: { id } });
    if (!r.ok || !r.reporte) throw new Error(r.error || "No encontrado");
    renderDetail(r.reporte);
  } catch (e) {
    $("drawerLoading").innerHTML = `<span style="color:var(--danger)">${esc(e.message)}</span>`;
  }
}

function renderDetail(rep) {
  $("dId").textContent     = rep.Id || "";
  $("dTitle").textContent  = rep.Titulo || "Sin título";
  $("dEstado").innerHTML   = `<span class="${badgeClass(rep.Estado)}">${esc(rep.Estado)}</span>`;
  $("dTipo").textContent   = rep.Tipo || "";
  $("dPrio").textContent   = rep.Prioridad || "–";
  $("dClase").textContent  = rep.Clasificacion || "–";
  $("dCreado").textContent = rep.FechaCreacion || "–";
  $("dAsig").textContent   = rep.Asignado || "–";
  $("dAfectado") && ($("dAfectado").textContent = rep.UsuarioAfectado || "–");
  $("dDesc").textContent   = rep.Descripcion || "Sin descripción.";
  $("dComment").value      = "";

  // ¿Ya está cerrado/resuelto? Ocultar acciones
  const sk = getStatusKey(rep.Estado);
  const cerradoYa = (sk === "cerrado" || sk === "cancelado" || sk === "resuelto");
  $("drawerActions") && ($("drawerActions").style.display = cerradoYa ? "none" : "");

  const acts = Array.isArray(rep.Actividades) ? rep.Actividades : [];
  $("dActividades").innerHTML = acts.length === 0
    ? `<p class="timeline-empty">Sin actividades registradas.</p>`
    : acts.map(a => `
        <div class="event">
          <div class="date">${esc(a.Fecha || "")}</div>
          <div>
            <div class="kind"><span class="badge ${a.Tipo?.includes("analista") ? "blue" : ""}">${esc(a.Tipo || "")}</span></div>
            <div class="who">${esc(a.Autor || "")}</div>
            <div class="what">${esc(a.Texto || "")}</div>
          </div>
        </div>`).join("");

  $("drawerLoading").classList.add("hidden");
  $("drawerContent").classList.remove("hidden");
}

function closeDrawer() {
  $("overlay").classList.remove("show");
  $("drawer").classList.remove("show");
  document.body.style.overflow = "";
  state.detail = null;
}
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

/* ─── Comentar ─── */
async function doComment() {
  const id    = state.detail;
  const texto = $("dComment").value.trim();
  if (!id || !texto) { flash("Escribe un comentario.", "err"); return; }
  try {
    flash("Enviando…");
    await api("/api/scsm/comentar", { method: "POST", body: { id, texto } });
    flash("✓ Comentario enviado.");
    $("dComment").value = "";
    const r = await api("/api/scsm/reporte", { method: "POST", body: { id } });
    if (r.ok && r.reporte) renderDetail(r.reporte);
  } catch (e) { flash("⚠ " + e.message, "err"); }
}

/* ─── Acción individual ─── */
async function doAction(accion) {
  const id = state.detail;
  if (!id) return;
  const label = accion === "resolve" ? "marcar como resuelto" : "cerrar";
  if (!confirm(`¿Deseas ${label} el reporte ${id}?`)) return;
  try {
    flash("Procesando…");
    const r = await api("/api/scsm/accion", { method: "POST", body: { id, accion } });
    if (!r.ok) throw new Error(r.error || "Error");
    flash(`✓ Reporte ${r.estado || "actualizado"}.`);
    closeDrawer(); await loadData();
  } catch (e) { flash("⚠ " + e.message, "err"); }
}

/* ─── Enter en login ─── */
$("inPass") && $("inPass").addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
$("inUser") && $("inUser").addEventListener("keydown", e => { if (e.key === "Enter") $("inPass").focus(); });

/* ─── Init ─── */
(async function init() {
  try {
    const r = await api("/api/session");
    if (r.ok && r.token) {
      state.token   = r.token;
      state.user    = r.user;
      state.display = r.display;
      showApp(); await loadData();
    }
  } catch {}
})();
