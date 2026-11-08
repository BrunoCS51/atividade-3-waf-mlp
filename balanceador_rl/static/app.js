"use strict";

const $ = (id) => document.getElementById(id);
let state = null;
let pollTimer = null;
let interactivePollTimer = null;

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
  const verdict = comparison.verdict;
  const rlWinner = verdict ? verdict.winner === "q_learning" : rl.timeouts < rr.timeouts || (rl.timeouts === rr.timeouts && rl.average_latency_ms < rr.average_latency_ms);
  const rrWinner = verdict ? verdict.winner === "round_robin" : !rlWinner;
  $("comparison").className = "comparison";
  $("comparison").innerHTML = policyCard("Round-Robin tradicional", rr, rrWinner) + policyCard("Agente Q-Learning", rl, rlWinner);
  const overload = comparison.conditions?.offered_over_capacity ? ` Sobrecarga intencional: concorrência acima do limite efetivo ${comparison.conditions.scenario_concurrency_limit}.` : "";
  const conclusion = verdict?.equivalent ? `Resultados equivalentes: ${verdict.reason}.` : verdict ? `${verdict.winner === "q_learning" ? "Q-Learning" : "Round-Robin"}: ${verdict.reason}.` : "Comparação concluída.";
  $("compare-status").textContent = conclusion + overload;
}

function readInteractiveLoads() {
  return Object.fromEntries(["node1", "node2", "node3"].map((node) => [node, Number($(`load-${node}`).value)]));
}

function loadText(loads) {
  return `N1 ${Math.round(loads.node1)}% · N2 ${Math.round(loads.node2)}% · N3 ${Math.round(loads.node3)}%`;
}

function activeText(counts) {
  return `N1 ${counts.node1} · N2 ${counts.node2} · N3 ${counts.node3}`;
}

function drawInteractiveChart(records = []) {
  const canvas = $("interactive-chart");
  const ratio = Math.min(devicePixelRatio || 1, 2);
  const width = Math.max(canvas.clientWidth, 300); const height = 260;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, width, height);
  const pad = { left: 38, right: 12, top: 16, bottom: 28 };
  ctx.font = "10px sans-serif"; ctx.fillStyle = "#7a8698"; ctx.strokeStyle = "#e3e8ef";
  [0, 25, 50, 75, 100].forEach((value) => { const y = pad.top + (100 - value) / 100 * (height - pad.top - pad.bottom); ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke(); ctx.fillText(`${value}%`, 6, y + 3); });
  if (!records.length) { ctx.fillText("A utilização de CPU aparecerá a cada decisão.", 65, height / 2); return; }
  const colors = { node1: "#4f46e5", node2: "#e28b21", node3: "#c53c52" };
  Object.entries(colors).forEach(([node, color]) => {
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
    records.forEach((record, index) => { const x = pad.left + index / Math.max(records.length - 1, 1) * (width - pad.left - pad.right); const y = pad.top + (100 - (record.cpu_after || record.loads_after)[node]) / 100 * (height - pad.top - pad.bottom); if (!index) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.stroke();
  });
  ctx.fillStyle = "#7a8698"; ctx.fillText("1", pad.left, height - 8); ctx.fillText(String(records.length), width - 28, height - 8);
}

function renderInteractive(simulation) {
  const active = simulation?.status === "running";
  const records = simulation?.records || [];
  const latest = records.at(-1);
  const loads = simulation?.loads || readInteractiveLoads();
  const cpu = simulation?.cpu_utilization || loads;
  const activeCounts = simulation?.active_counts || { node1: 0, node2: 0, node3: 0 };
  $("interactive-start").disabled = active;
  $("interactive-apply").disabled = !active;
  $("interactive-stop").disabled = !active;
  $("interactive-learning").disabled = active;
  $("train").disabled = active || ["queued", "running"].includes(state?.training?.status);
  $("compare").disabled = active;
  $("interactive-badge").textContent = !simulation ? "Aguardando" : active ? "Executando" : simulation.status === "completed" ? "Concluída" : simulation.status === "stopped" ? "Interrompida" : "Falhou";
  $("interactive-progress-bar").style.width = `${simulation?.percent || 0}%`;
  $("interactive-progress-percent").textContent = `${Math.round(simulation?.percent || 0)}%`;
  $("interactive-message").textContent = simulation?.message || "A Q-Table treinada será copiada para esta sessão.";
  ["node1", "node2", "node3"].forEach((node) => {
    const card = document.querySelector(`[data-live-node="${node}"]`);
    const lastForNode = [...records].reverse().find((record) => record.action === node);
    card.classList.toggle("selected", latest?.action === node);
    card.classList.toggle("saturated", Boolean(simulation?.saturation?.[node]));
    card.querySelector(".load-bar i").style.width = `${cpu[node]}%`;
    card.querySelector("b").textContent = `${Math.round(cpu[node])}% CPU`;
    card.querySelector("small").textContent = lastForNode ? `Latência: ${lastForNode.timeout ? "timeout" : `${number(lastForNode.latency_ms, 1)} ms`}` : "Latência: —";
    card.querySelector("em").textContent = `Ativas: ${activeCounts[node]} · escolhas: ${simulation?.route_counts?.[node] || 0}`;
    card.querySelector("mark").textContent = simulation?.saturation?.[node] ? "Saturado" : "Saudável";
  });
  if (latest) {
    $("last-decision").textContent = `#${latest.request} · ${latest.action} por ${latest.mode === "exploracao" ? "exploração" : "explotação"}`;
    const parts = latest.reward_parts || {};
    const learningLabel = simulation?.learning_mode === "fixed" ? "Q fixa" : "Q atualizada";
    $("last-decision-detail").textContent = `${latest.state.replaceAll("_", " ")} · CPU ${number(latest.selected?.cpu, 0)}% · ${latest.selected?.active_requests || 1} ativa(s) · ${number(latest.latency_ms, 1)} ms · R ${latest.reward >= 0 ? "+" : ""}${number(latest.reward, 1)} (latência ${parts.latency_reward ?? latest.reward}) · ${learningLabel} ${number(latest.q_before)} → ${number(latest.q_after)}`;
  }
  $("interactive-history").innerHTML = records.length ? [...records].reverse().slice(0, 30).map((record) => `<tr><td>${record.request}</td><td>${record.state.replace("carga_", "")}</td><td class="decision-action">${record.action}${record.selected?.saturated ? ' <span class="saturation-label">saturado</span>' : ""}</td><td>${record.mode === "exploracao" ? "exploração" : "explotação"}</td><td>${loadText(record.cpu_before || record.loads_before)}</td><td>${activeText(record.active_before || {node1:0,node2:0,node3:0})}</td><td>${record.timeout ? "timeout" : `${number(record.latency_ms, 1)} ms`}</td><td class="${record.reward >= 0 ? "reward-positive" : "reward-negative"}" title="Latência ${record.reward_parts?.latency_reward ?? record.reward}; CPU −${number(record.reward_parts?.cpu_penalty, 1)}; concorrência −${number(record.reward_parts?.concurrency_penalty, 1)}; saturação −${number(record.reward_parts?.saturation_penalty, 1)}">${record.reward >= 0 ? "+" : ""}${number(record.reward, 1)}</td><td>${number(record.q_before)} → ${number(record.q_after)}${record.q_updated ? " · atualizada" : " · fixa"}</td></tr>`).join("") : '<tr><td colspan="9">Nenhuma decisão registrada.</td></tr>';
  drawInteractiveChart(records);
  clearTimeout(interactivePollTimer);
  if (active) interactivePollTimer = setTimeout(loadInteractive, 500);
}

async function loadInteractive() {
  try { const simulation = await api(`/api/interactive?t=${Date.now()}`); if (state) state.interactive = simulation; renderInteractive(simulation); } catch (error) { $("interactive-message").textContent = error.message; }
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
  try { state = await api("/api/status"); renderQTable(state); renderTraining(state); renderComparison(state.last_comparison); renderInteractive(state.interactive); } catch (error) { $("progress-message").textContent = error.message; }
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

["node1", "node2", "node3"].forEach((node) => $("load-" + node).addEventListener("input", () => {
  $("load-" + node + "-value").textContent = `${$("load-" + node).value}%`;
  if (!state?.interactive || state.interactive.status !== "running") renderInteractive(state?.interactive);
}));

$("interactive-start").addEventListener("click", async () => {
  try {
    const simulation = await api("/api/interactive/start", { method: "POST", body: JSON.stringify({ loads: readInteractiveLoads(), requests: Number($("interactive-requests").value), epsilon: Number($("interactive-epsilon").value), interval_ms: Number($("interactive-interval").value), concurrency: Number($("interactive-concurrency").value), learning_mode: $("interactive-learning").value, seed: Number($("seed").value) }) });
    if (state) state.interactive = simulation; renderInteractive(simulation);
  } catch (error) { alert(error.message); }
});

$("interactive-apply").addEventListener("click", async () => {
  try { const simulation = await api("/api/interactive/load", { method: "POST", body: JSON.stringify({ loads: readInteractiveLoads() }) }); if (state) state.interactive = simulation; renderInteractive(simulation); } catch (error) { alert(error.message); }
});

$("interactive-stop").addEventListener("click", async () => {
  try { const simulation = await api("/api/interactive/stop", { method: "POST", body: "{}" }); if (state) state.interactive = simulation; renderInteractive(simulation); } catch (error) { alert(error.message); }
});

addEventListener("resize", () => { drawChart((state?.training || state?.last_training)?.curve || []); drawInteractiveChart(state?.interactive?.records || []); }, { passive: true });
loadStatus(); loadInfrastructure(); setInterval(loadInfrastructure, 15000);
