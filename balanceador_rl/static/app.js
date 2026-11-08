"use strict";

const $ = (id) => document.getElementById(id);
let state = null;
let pollTimer = null;

const number = (value, digits = 2) => Number(value || 0).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const duration = (seconds) => `${Math.round(Number(seconds || 0))} s`;

async function api(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function renderQTable(data) {
  const labels = { carga_baixa: "Carga baixa", carga_media: "Carga média", carga_alta: "Carga alta" };
  $("q-table").innerHTML = Object.entries(data.q_table).map(([networkState, actions]) => {
    const best = data.policy[networkState];
    return `<tr><th>${labels[networkState]}</th>${["node1", "node2", "node3"].map((node) => `<td class="${node === best ? "best-q" : ""}">${number(actions[node])}</td>`).join("")}<td class="policy">→ ${best}</td></tr>`;
  }).join("");
  $("best-node").textContent = data.last_training ? data.policy.carga_alta : "Ainda empatada";
}

function drawChart(curve = []) {
  const canvas = $("learning-chart");
  const ratio = Math.min(devicePixelRatio || 1, 2);
  const width = Math.max(canvas.clientWidth, 300);
  const height = 230;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const pad = { x: 34, y: 18, bottom: 27 };
  ctx.strokeStyle = "#e3e8ef"; ctx.lineWidth = 1;
  for (let index = 0; index < 5; index += 1) { const y = pad.y + index * (height - pad.y - pad.bottom) / 4; ctx.beginPath(); ctx.moveTo(pad.x, y); ctx.lineTo(width - 10, y); ctx.stroke(); }
  if (!curve.length) { ctx.fillStyle = "#8893a5"; ctx.font = "12px sans-serif"; ctx.fillText("A curva aparecerá durante o treinamento.", 55, height / 2); return; }
  const series = [
    { color: "#4f46e5", value: (row) => (row.reward + 100) / 120 },
    { color: "#e28b21", value: (row) => Math.min(row.latency_ms, 650) / 650 },
    { color: "#1c9a7c", value: (row) => row.epsilon / .30 },
  ];
  series.forEach(({ color, value }) => {
    ctx.strokeStyle = color; ctx.lineWidth = 1.8; ctx.beginPath();
    curve.forEach((row, index) => {
      const x = pad.x + index * (width - pad.x - 10) / Math.max(curve.length - 1, 1);
      const y = pad.y + (1 - value(row)) * (height - pad.y - pad.bottom);
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }); ctx.stroke();
  });
  ctx.fillStyle = "#778398"; ctx.font = "10px sans-serif"; ctx.fillText("1", pad.x, height - 8); ctx.fillText(String(curve.length), width - 30, height - 8);
}

function renderTraining(data) {
  const job = data.training || data.last_training;
  if (!job) { $("training-status").textContent = "Não iniciado"; drawChart([]); return; }
  const active = ["queued", "running"].includes(job.status);
  $("training-status").textContent = active ? "Em andamento" : job.status === "completed" ? "Concluído" : "Falhou";
  $("training-detail").textContent = `${job.current_episode}/${job.episodes} episódios · ${job.timeouts} timeouts`;
  $("epsilon-value").textContent = `${number(job.epsilon * 100, 1)}%`;
  $("progress-bar").style.width = `${job.percent || 0}%`;
  $("progress-percent").textContent = `${Math.round(job.percent || 0)}%`;
  $("progress-message").textContent = job.message;
  $("progress-time").textContent = active ? `${duration(job.elapsed_seconds)} · faltam ~${duration(job.remaining_seconds)}` : duration(job.elapsed_seconds);
  $("train").disabled = active;
  $("reset").disabled = active;
  drawChart(job.curve || []);
  if (active) { clearTimeout(pollTimer); pollTimer = setTimeout(loadStatus, 800); }
}

function policyCard(title, result, winner) {
  const pct = (value) => `${number(100 * value / result.requests, 1)}%`;
  return `<article class="policy-card ${winner ? "winner" : ""}"><header><strong>${title}</strong>${winner ? '<span class="winner-label">MELHOR RESULTADO</span>' : ""}</header><div class="metric-list"><span><small>Latência média OK</small><strong>${number(result.average_latency_ms, 1)} ms</strong></span><span><small>P95</small><strong>${number(result.p95_latency_ms, 1)} ms</strong></span><span><small>Respostas &lt;100 ms</small><strong>${result.under_100ms}/${result.requests} · ${pct(result.under_100ms)}</strong></span><span><small>Timeouts</small><strong>${result.timeouts}/${result.requests} · ${pct(result.timeouts)}</strong></span><span><small>Tempo da rajada</small><strong>${number(result.wall_seconds, 2)} s</strong></span><span><small>Erros de rede</small><strong>${result.errors}</strong></span></div><div class="route-line">Rotas: node1 ${result.routes.node1} · node2 ${result.routes.node2} · node3 ${result.routes.node3}</div></article>`;
}

function renderComparison(comparison) {
  if (!comparison) return;
  const rr = comparison.round_robin; const rl = comparison.q_learning;
  const rlWinner = rl.timeouts < rr.timeouts || (rl.timeouts === rr.timeouts && rl.average_latency_ms < rr.average_latency_ms);
  $("comparison").className = "comparison";
  $("comparison").innerHTML = policyCard("Round-Robin tradicional", rr, !rlWinner) + policyCard("Agente Q-Learning", rl, rlWinner);
  $("compare-status").textContent = comparison.trained_q_table ? "Comparação feita com a Q-Table treinada." : "Atenção: comparação feita antes do treinamento.";
}

async function loadInfrastructure() {
  try {
    const data = await api("/api/infrastructure");
    $("infra-status").textContent = data.online ? "Online" : "Indisponível";
    $("infra-detail").textContent = data.online ? "Proxy e três nós respondendo" : "Suba o profile reforco";
    Object.entries(data.nodes).forEach(([node, item]) => {
      const card = document.querySelector(`[data-node="${node}"]`); card.classList.toggle("online", item.online); card.querySelector("small").textContent = item.timeout ? "> 500 ms · timeout" : `${number(item.latency_ms, 1)} ms`;
    });
  } catch (error) { $("infra-status").textContent = "Indisponível"; $("infra-detail").textContent = error.message; }
}

async function loadStatus() {
  try { state = await api("/api/status"); renderQTable(state); renderTraining(state); renderComparison(state.last_comparison); } catch (error) { $("progress-message").textContent = error.message; }
}

$("train").addEventListener("click", async () => {
  if (!confirm("Zerar a Q-Table atual e iniciar um novo treinamento?")) return;
  try { state = await api("/api/train", { method: "POST", body: JSON.stringify({ episodes: Number($("episodes").value), seed: Number($("seed").value) }) }); renderQTable(state); renderTraining(state); } catch (error) { alert(error.message); }
});

$("reset").addEventListener("click", async () => {
  if (!confirm("Limpar a Q-Table, o último treinamento e a comparação?")) return;
  try { await api("/api/reset", { method: "POST", body: "{}" }); await loadStatus(); } catch (error) { alert(error.message); }
});

$("compare").addEventListener("click", async () => {
  $("compare").disabled = true; $("compare-status").textContent = "Executando duas rajadas reais…";
  try { renderComparison(await api("/api/compare", { method: "POST", body: JSON.stringify({ requests: Number($("requests").value), concurrency: Number($("concurrency").value), seed: Number($("seed").value) }) })); } catch (error) { $("compare-status").textContent = error.message; } finally { $("compare").disabled = false; }
});

addEventListener("resize", () => drawChart((state?.training || state?.last_training)?.curve || []), { passive: true });
loadStatus(); loadInfrastructure(); setInterval(loadInfrastructure, 15000);
