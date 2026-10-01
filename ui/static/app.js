"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmt = (v) => {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};
const markdown = (text) => DOMPurify.sanitize(marked.parse(text || ""));

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.erro || data.detail || `HTTP ${resp.status}`);
  return data;
}

function table(columns, rows, { numeric = true, onClick } = {}) {
  const isNum = columns.map((_, i) => numeric && rows.length && rows.every((r) => r[i] === null || typeof r[i] === "number"));
  const head = columns.map((c, i) => `<th class="${isNum[i] ? "num" : ""}">${esc(c)}</th>`).join("");
  const body = rows.map((r, ri) => `<tr data-i="${ri}" class="${onClick ? "clickable" : ""}">` +
    r.map((v, i) => `<td class="${isNum[i] ? "num" : ""}">${esc(fmt(v))}</td>`).join("") + "</tr>").join("");
  const el = document.createElement("table");
  el.className = "data";
  el.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  if (onClick) el.querySelectorAll("tbody tr").forEach((tr) =>
    tr.addEventListener("click", () => { el.querySelectorAll("tr.selected").forEach((x) => x.classList.remove("selected")); tr.classList.add("selected"); onClick(+tr.dataset.i); }));
  return el;
}

/* ---------- abas e tema ---------- */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  if (name === "avaliacao" && !$("#ev-runs").children.length) loadRuns();
  if (name === "grafo" && cy) cy.resize();
  try { localStorage.setItem("aba", name); } catch {}
}
$("#theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch {}
});
// Grafo e gráfico leem as cores na hora de desenhar: redesenha em qualquer troca de tema
// (botão, sistema operacional ou script).
function onThemeChange() { restyleGraph(); if (chart) drawChart(lastResult); }
new MutationObserver(onThemeChange).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", onThemeChange);
try {
  const t = localStorage.getItem("tema"); if (t) document.documentElement.dataset.theme = t;
} catch {}

async function loadStatus() {
  try {
    const s = await api("/api/status");
    const n = Object.fromEntries(s.nos.map((x) => [x.label, x]));
    const adapt = (s.relacoes.find((r) => r.tipo === "ADAPTED_FROM") || {}).total || 0;
    const models = Array.isArray(s.modelos_omlx) ? "oMLX ok" : "oMLX fora do ar";
    $("#status").textContent =
      `Anime ${n.Anime?.completos ?? 0}/${n.Anime?.total ?? 0} completos · Mangá ${n.Manga?.completos ?? 0}/${n.Manga?.total ?? 0} · ADAPTED_FROM ${adapt} · ${models}`;
    const opt = $("#backend option[value=anthropic]");
    if (!s.anthropic_configurado) { opt.disabled = true; opt.textContent = "Claude (sem ANTHROPIC_API_KEY)"; }
    $("#backend").value = s.agent_backend === "anthropic" && s.anthropic_configurado ? "anthropic" : "omlx";
  } catch (e) { $("#status").textContent = `erro: ${e.message}`; }
}

/* ---------- chat ---------- */
let conversa = null;
const messages = $("#messages");
const input = $("#chat-input");

function addMsg(cls, html) {
  $("#chat-empty")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

function stepHtml(p) {
  let body = p.resultado;
  try {
    const obj = JSON.parse(p.resultado);
    body = JSON.stringify(obj, null, 2);
    if (obj.cypher) body = `${obj.cypher}\n\n— ${obj.total_linhas} linhas —\n${JSON.stringify(obj.linhas.slice(0, 15))}`;
  } catch {}
  return `<details class="step ${p.erro ? "err" : ""}"><summary><b>${esc(p.ferramenta)}</b>
    ${esc(JSON.stringify(p.args))} · ${p.segundos}s${p.erro ? " · erro" : ""}</summary><pre>${esc(body)}</pre></details>`;
}

async function sendChat(text) {
  if (!text.trim()) return;
  addMsg("user", esc(text));
  const bot = addMsg("bot", `<div class="steps"></div><div class="answer"><span class="thinking">pensando</span></div><div class="foot"></div>`);
  $("#chat-send").disabled = true;
  input.value = "";
  try {
    const resp = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensagem: text, conversa, backend: $("#backend").value }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const line = buffer.slice(0, idx).replace(/^data: /, "");
        buffer = buffer.slice(idx + 2);
        const ev = JSON.parse(line);
        if (ev.tipo === "inicio") conversa = ev.conversa;
        else if (ev.tipo === "passo") bot.querySelector(".steps").insertAdjacentHTML("beforeend", stepHtml(ev));
        else if (ev.tipo === "resposta") {
          bot.querySelector(".answer").innerHTML = markdown(ev.texto || "_(resposta vazia)_");
          bot.querySelector(".foot").textContent =
            `${ev.modelo} · ${ev.segundos}s · ${bot.querySelectorAll(".step").length} chamadas · parada: ${ev.parada}`;
        } else if (ev.tipo === "erro") {
          bot.querySelector(".answer").innerHTML = `<span class="fail">${esc(ev.mensagem)}</span>`;
        }
        messages.scrollTop = messages.scrollHeight;
      }
    }
  } catch (e) {
    bot.querySelector(".answer").innerHTML = `<span class="fail">${esc(e.message)}</span>`;
  } finally {
    $("#chat-send").disabled = false;
    input.focus();
  }
}

$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat(input.value); });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(input.value); }
});
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => sendChat(c.textContent)));
$("#new-chat").addEventListener("click", () => {
  if (conversa) fetch(`/api/chat/${conversa}`, { method: "DELETE" });
  conversa = null;
  messages.innerHTML = "";
});
$("#backend").addEventListener("change", () => $("#new-chat").click());

/* ---------- analytics ---------- */
let chart = null;
let lastResult = null;

function showResult(r) {
  lastResult = r;
  $("#cy-code").value = r.cypher || "";
  const wrap = $("#cy-table");
  wrap.innerHTML = "";
  if (r.colunas) wrap.appendChild(table(r.colunas, r.linhas));
  drawChart(r);
}

function chartable(r) {
  if (!r || !r.linhas || r.linhas.length < 2 || r.linhas.length > 60 || r.colunas.length < 2) return null;
  const numCols = r.colunas.map((_, i) => r.linhas.every((x) => typeof x[i] === "number"));
  const value = numCols.lastIndexOf(true);
  if (value < 0) return null;
  const label = r.colunas.findIndex((_, i) => i !== value && r.linhas.every((x) => typeof x[i] !== "object" || x[i] === null));
  if (label < 0) return null;
  return { label, value };
}

function drawChart(r) {
  if (chart) { chart.destroy(); chart = null; }
  const pick = chartable(r);
  $("#cy-chart-wrap").hidden = !pick;
  if (!pick) return;
  const grid = css("--border"), ink = css("--text-2");
  chart = new Chart($("#cy-chart"), {
    type: "bar",
    data: {
      labels: r.linhas.map((x) => fmt(x[pick.label])),
      datasets: [{ label: r.colunas[pick.value], data: r.linhas.map((x) => x[pick.value]),
        backgroundColor: css("--series-1"), maxBarThickness: 24, borderRadius: 4, borderSkipped: "start" }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: `${r.colunas[pick.value]} por ${r.colunas[pick.label]}`, color: css("--text"), align: "start" },
        tooltip: { callbacks: { label: (c) => ` ${r.colunas[pick.value]}: ${fmt(c.parsed.y)}` } },
      },
      scales: {
        x: { ticks: { color: ink, maxRotation: 60, autoSkip: true }, grid: { display: false } },
        y: { ticks: { color: ink }, grid: { color: grid }, border: { display: false } },
      },
    },
  });
}

$("#cy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#cy-question").value.trim();
  if (!q) return;
  $("#cy-ask").disabled = true;
  $("#cy-meta").textContent = "gerando…";
  $("#cy-attempts").innerHTML = "";
  try {
    const r = await api("/api/cypher", { method: "POST", body: { pergunta: q } });
    $("#cy-meta").textContent = r.ok
      ? `${r.modelo} · ${r.tentativas.length} tentativa(s) · ${r.segundos}s · ${r.total_linhas} linhas`
      : `não consegui gerar uma consulta válida (${r.tentativas.length} tentativas)`;
    $("#cy-attempts").innerHTML = r.tentativas.filter((t) => t.erro).map((t, i) =>
      `<div class="attempt"><b>Tentativa ${i + 1}:</b> ${esc(t.erro)}<details><summary>resposta do modelo</summary><pre>${esc(t.resposta)}</pre></details></div>`).join("");
    if (!r.ok) $("#cy-code").value = r.tentativas.at(-1)?.resposta || "";
    else showResult(r);
  } catch (err) { $("#cy-meta").innerHTML = `<span class="fail">${esc(err.message)}</span>`; }
  finally { $("#cy-ask").disabled = false; }
});

$("#cy-run").addEventListener("click", async () => {
  $("#cy-run").disabled = true;
  try {
    const r = await api("/api/cypher/executar", { method: "POST", body: { cypher: $("#cy-code").value } });
    $("#cy-meta").textContent = `executado à mão · ${r.segundos}s · ${r.total_linhas} linhas`;
    $("#cy-attempts").innerHTML = "";
    showResult(r);
  } catch (err) { $("#cy-meta").innerHTML = `<span class="fail">${esc(err.message)}</span>`; }
  finally { $("#cy-run").disabled = false; }
});

/* ---------- grafo ---------- */
let cy = null;
const EDGE_VAR = { RECOMMENDS: "--edge-rec", RELATED_TO: "--edge-rel", ADAPTED_FROM: "--edge-ada", PRODUCED_BY: "--edge-aut", WRITTEN_BY: "--edge-aut" };

function graphStyle() {
  return [
    { selector: "node", style: {
      "background-color": css("--series-1"), label: "data(name)", color: css("--text"), "font-size": 10,
      "text-wrap": "ellipsis", "text-max-width": 110, "text-valign": "bottom", "text-margin-y": 3,
      width: "data(size)", height: "data(size)", "border-width": 2, "border-color": css("--surface") } },
    { selector: "node[?sketch]", style: { "background-color": css("--surface"), "border-color": css("--muted"), "border-style": "dashed" } },
    { selector: "node[kind = 'Studio'], node[kind = 'Author']", style: { shape: "round-rectangle", "background-color": css("--edge-aut") } },
    { selector: "node[kind = 'Manga']", style: { shape: "round-diamond" } },
    { selector: "node[?center]", style: { "border-color": css("--text"), "border-width": 3, "font-weight": 700, "font-size": 12 } },
    { selector: "edge", style: { width: "data(w)", "line-color": "data(color)", "curve-style": "bezier", opacity: 0.8,
      "target-arrow-shape": "data(arrow)", "target-arrow-color": "data(color)", "arrow-scale": 0.7 } },
    { selector: "edge:selected, edge.hover", style: { label: "data(label)", "font-size": 9, color: css("--text-2"), "text-background-color": css("--surface"), "text-background-opacity": 1 } },
  ];
}
function restyleGraph() {
  if (!cy) return;
  cy.style(graphStyle());
  cy.edges().forEach((e) => e.data("color", css(EDGE_VAR[e.data("type")])));
}

async function openNode(label, malId) {
  const g = await api(`/api/grafo/no/${label}/${malId}`);
  renderDetails(g);
  const centerId = `${label}:${malId}`;
  const nodes = new Map([[centerId, { data: { id: centerId, kind: label, mal_id: malId,
    name: g.props.titulo || g.props.nome, size: 34, center: true, sketch: g.props.completo === false } }]]);
  const edges = [];
  for (const a of g.arestas) {
    const id = `${a.label}:${a.mal_id}`;
    if (!nodes.has(id)) nodes.set(id, { data: { id, kind: a.label, mal_id: a.mal_id, name: a.titulo,
      size: a.top ? 22 : 16, sketch: a.completo === false } });
    const [s, t] = a.sentido === "entrada" ? [id, centerId] : [centerId, id];
    edges.push({ data: { id: `${a.tipo}:${s}:${t}:${a.detalhe}`, source: s, target: t, type: a.tipo,
      color: css(EDGE_VAR[a.tipo]), arrow: a.tipo === "RECOMMENDS" ? "none" : "triangle",
      w: a.tipo === "RECOMMENDS" ? Math.min(1 + Math.log2(1 + (a.detalhe || 0)), 7) : 1.5,
      label: a.tipo === "RECOMMENDS" ? `${a.detalhe} votos` : `${a.tipo.toLowerCase()}${a.detalhe ? ` (${a.detalhe})` : ""}` } });
  }
  const elements = [...nodes.values(), ...edges];
  if (!cy) {
    cy = cytoscape({ container: $("#g-canvas"), elements, style: graphStyle(), wheelSensitivity: 0.3 });
    cy.on("tap", "node", (e) => { const d = e.target.data(); if (!d.center) openNode(d.kind, d.mal_id); });
    cy.on("mouseover", "edge", (e) => e.target.addClass("hover"));
    cy.on("mouseout", "edge", (e) => e.target.removeClass("hover"));
  } else {
    cy.elements().remove();
    cy.add(elements);
  }
  cy.layout({ name: "concentric", concentric: (n) => (n.data("center") ? 2 : 1), levelWidth: () => 1,
    minNodeSpacing: 28, animate: false }).run();
}

function renderDetails(g) {
  const p = g.props;
  const rows = [["Nota", p.nota], ["Rank", p.rank], ["Ano", p.ano], ["Formato", p.tipo], ["Status", p.status],
    ["Episódios", p.episodios], ["Capítulos", p.capitulos], ["Fonte", p.fonte], ["Membros", p.membros?.toLocaleString?.("pt-BR")]]
    .filter(([, v]) => v !== undefined && v !== null);
  const groups = {};
  for (const a of g.arestas) (groups[a.tipo] ||= []).push(a);
  const names = { RECOMMENDS: "Recomendações", RELATED_TO: "Relacionados", ADAPTED_FROM: "Adaptação",
    PRODUCED_BY: g.label === "Studio" ? "Animes" : "Estúdio", WRITTEN_BY: g.label === "Author" ? "Mangás" : "Autores" };
  $("#g-details").innerHTML = `
    <h3>${esc(p.titulo || p.nome)}${p.top ? '<span class="badge">top</span>' : ""}${p.completo === false ? '<span class="badge">esboço</span>' : ""}</h3>
    <div class="sub">${esc(g.label)} · mal_id ${p.mal_id}${p.titulo_en && p.titulo_en !== p.titulo ? ` · ${esc(p.titulo_en)}` : ""}</div>
    ${rows.length ? `<dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(fmt(v))}</dd>`).join("")}</dl>` : ""}
    ${p.generos?.length ? `<div class="tags">${p.generos.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>` : ""}
    ${p.sinopse ? `<p class="syn">${esc(p.sinopse.slice(0, 600))}${p.sinopse.length > 600 ? "…" : ""}</p>` : ""}
    ${Object.entries(groups).map(([t, list]) => `<h4>${names[t] || t} (${list.length})</h4><ul>` +
      list.slice(0, 25).map((a) => `<li><a href="#" data-l="${a.label}" data-id="${a.mal_id}">${esc(a.titulo)}</a>` +
        `${a.detalhe !== null && a.detalhe !== undefined ? ` <span class="muted">${esc(t === "RECOMMENDS" ? `${a.detalhe} votos` : a.detalhe)}</span>` : ""}` +
        `${a.nota ? ` <span class="muted">· ${fmt(a.nota)}</span>` : ""}</li>`).join("") + "</ul>").join("")}`;
  $("#g-details").querySelectorAll("a[data-l]").forEach((a) =>
    a.addEventListener("click", (e) => { e.preventDefault(); openNode(a.dataset.l, +a.dataset.id); }));
}

let searchTimer = null;
$("#g-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = $("#g-search").value.trim();
  if (q.length < 2) { $("#g-results").hidden = true; return; }
  searchTimer = setTimeout(async () => {
    const rows = await api(`/api/grafo/busca?q=${encodeURIComponent(q)}`);
    const ul = $("#g-results");
    ul.innerHTML = rows.map((r) => `<li data-l="${r.label}" data-id="${r.mal_id}">${esc(r.titulo)}
      <small>${r.label}${r.titulo_en && r.titulo_en !== r.titulo ? ` · ${esc(r.titulo_en)}` : ""}${r.nota ? ` · ${fmt(r.nota)}` : ""}${r.top ? " · top" : ""}${r.completo === false ? " · esboço" : ""}</small></li>`).join("")
      || `<li class="muted">nada encontrado</li>`;
    ul.hidden = false;
    ul.querySelectorAll("li[data-l]").forEach((li) => li.addEventListener("click", () => {
      ul.hidden = true; $("#g-search").value = li.firstChild.textContent.trim(); openNode(li.dataset.l, +li.dataset.id);
    }));
  }, 200);
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("#g-results").hidden = true; });

/* ---------- avaliação ---------- */
let runs = [];
async function loadRuns() {
  runs = await api("/api/avaliacoes");
  renderRuns();
}
function renderRuns() {
  const f = $("#ev-filter").value;
  const list = runs.filter((r) => !f || r.tipo === f);
  const wrap = $("#ev-runs");
  wrap.innerHTML = "";
  const el = document.createElement("table");
  el.className = "data";
  el.innerHTML = `<thead><tr><th>Quando</th><th>Tipo</th><th>Conjunto</th><th>Modelo</th><th>Acertos</th><th class="num">Mediana</th></tr></thead><tbody>` +
    list.map((r, i) => `<tr class="clickable" data-i="${i}"><td>${esc(r.quando.replace(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/, "$3/$2 $4:$5"))}</td>
      <td>${esc(r.tipo)}</td><td>${esc(r.conjunto)}</td><td>${esc(r.modelo)}</td>
      <td><span class="bar"><i style="width:${(100 * r.acertos / r.total).toFixed(0)}%"></i></span>${r.acertos}/${r.total}</td>
      <td class="num">${fmt(r.mediana_s)}s</td></tr>`).join("") + "</tbody>";
  el.querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", () => {
    el.querySelectorAll("tr.selected").forEach((x) => x.classList.remove("selected"));
    tr.classList.add("selected");
    openRun(list[+tr.dataset.i].nome);
  }));
  wrap.appendChild(el);
}
async function openRun(nome) {
  const d = await api(`/api/avaliacoes/${encodeURIComponent(nome)}`);
  const agent = d.resumo.tipo === "agente";
  const box = $("#ev-detail");
  box.innerHTML = `<h3>${esc(d.resumo.modelo)} · ${d.resumo.acertos}/${d.resumo.total}</h3>`;
  const cols = agent ? ["", "id", "categoria", "pergunta", "cobertura", "passos", "s", "problemas"]
                     : ["", "id", "pergunta", "tentativas", "s", "erros"];
  const rows = d.linhas.map((r) => agent
    ? [(r.passou ? "✅" : "❌"), r.id, r.categoria, r.pergunta, r.cobertura, r.passos, r.segundos,
       [!r.ferramenta_ok && "ferramenta", !r.cobertura_ok && `faltaram: ${(r.faltaram || []).join(", ")}`,
        !r.conteudo_ok && "conteúdo", r.notas_sem_fonte?.length && `notas sem fonte: ${r.notas_sem_fonte.join(", ")}`].filter(Boolean).join(" · ")]
    : [(r.correto ? "✅" : r.executou ? "⚠️" : "❌"), r.id, r.pergunta, r.tentativas, r.segundos, (r.erros || []).join(" | ").slice(0, 200)]);
  const detail = document.createElement("div");
  box.appendChild(table(cols, rows, { numeric: false, onClick: (i) => {
    const r = d.linhas[i];
    detail.innerHTML = agent
      ? `<h3>${esc(r.id)} · resposta</h3><div class="msg bot"><div class="answer">${markdown(r.resposta)}</div></div>
         <pre>${esc(JSON.stringify(r.chamadas, null, 2))}</pre>`
      : `<h3>${esc(r.id)} · Cypher</h3><pre>${esc(r.cypher || "(nenhum)")}</pre>
         <h3>Linhas (até 20)</h3><pre>${esc(JSON.stringify(r.linhas))}</pre>
         ${(r.respostas || []).map((x, k) => `<details><summary>resposta ${k + 1} do modelo</summary><pre>${esc(x)}</pre></details>`).join("")}`;
  } }));
  box.appendChild(detail);
}
$("#ev-filter").addEventListener("change", renderRuns);
$("#ev-reload").addEventListener("click", loadRuns);

/* ---------- início ---------- */
loadStatus();
try { const a = localStorage.getItem("aba"); if (a) showTab(a); } catch {}
