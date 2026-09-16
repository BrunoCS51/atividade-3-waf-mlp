"use strict";

const POLL_INTERVAL_MS = 5000;
const SESSION_KEY = "waf-dashboard-monitor-session";

const appState = {
  data: null,
  loading: false,
  session: loadSession(),
  fingerprints: {},
  simulationSubmitting: false,
  history: emptyHistory(),
  selectedExampleResult: null,
  exampleList: [],
  selectedExample: null,
  resizeFrame: null
};

function emptyHistory() {
  return {
    fonte: null,
    pagina: 1,
    por_pagina: 10,
    paginas: 1,
    total: 0,
    itens: [],
    resumo: { total: 0, liberadas: 0, bloqueadas: 0, risco_medio: null },
    atualizado_em: null
  };
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const node = byId(id);
  const nextValue = String(value ?? "Não disponível");
  if (node && node.textContent !== nextValue) node.textContent = nextValue;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function available(value) {
  return value !== null && value !== undefined && value !== "";
}

function formatNumber(value, digits = 4) {
  if (!available(value) || Number.isNaN(Number(value))) return "N/D";
  return Number(value).toLocaleString("pt-BR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0
  });
}

function formatMetric(value) {
  if (!available(value)) return "N/D";
  return `${(Number(value) * 100).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}%`;
}

function formatSeconds(value) {
  return available(value) ? `${formatNumber(value, 3)} s` : "N/D";
}

function formatDate(value, includeSeconds = false) {
  if (!value) return "Não disponível";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Não disponível";
  return date.toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: includeSeconds ? "medium" : "short"
  });
}

function loadSession() {
  try {
    const stored = JSON.parse(localStorage.getItem(SESSION_KEY));
    return stored && stored.start ? stored : { start: null, end: null };
  } catch {
    return { start: null, end: null };
  }
}

function saveSessionState() {
  localStorage.setItem(SESSION_KEY, JSON.stringify(appState.session));
}

function fingerprint(value) {
  return JSON.stringify(value ?? null);
}

function renderWhenChanged(key, value, render) {
  const nextFingerprint = fingerprint(value);
  if (appState.fingerprints[key] === nextFingerprint) return false;
  appState.fingerprints[key] = nextFingerprint;
  render();
  return true;
}

function syncTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Dados atualizados";
  return `Dados atualizados · ${date.toLocaleTimeString("pt-BR")}`;
}

async function loadData(options = {}) {
  if (appState.loading) return;
  appState.loading = true;
  const manual = Boolean(options.manual);
  const syncStatus = byId("sync-status");

  if (manual) {
    syncStatus.classList.add("syncing");
    byId("refresh-button").disabled = true;
  }

  try {
    const response = await fetch(`api/data?t=${Date.now()}`, {
      cache: "no-store"
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    appState.data = await response.json();
    renderIncrementally();
    await loadHistoryPage({ preservePage: true });
    setText("sync-status", syncTime(appState.data.gerado_em));
  } catch (error) {
    setText("sync-status", "Falha ao atualizar");
    if (!appState.data) renderConnectionError(error);
  } finally {
    appState.loading = false;
    syncStatus.classList.remove("syncing");
    if (manual) byId("refresh-button").disabled = false;
  }
}

function renderConnectionError() {
  setText("waf-status", "Dados indisponíveis");
  const dot = byId("waf-status-dot");
  dot.className = "status-dot offline";
}

function renderIncrementally() {
  const data = appState.data;

  renderWhenChanged(
    "overview",
    [data.waf, data.implantacao, data.rede, data.dataset],
    renderOverview
  );
  renderWhenChanged(
    "models",
    [data.diagnosticos, data.treinamento, data.pesos, data.rede],
    renderModels
  );
  renderWhenChanged("evaluations", data.avaliacao, renderEvaluations);
  renderWhenChanged("selection", data.implantacao, renderSelection);
  renderWhenChanged(
    "simulation",
    [data.simulacao, data.analise_features],
    renderSimulation
  );
  renderMonitor();
}

function renderOverview() {
  const data = appState.data;
  const online = Boolean(data?.waf?.online);
  setText("waf-status", online ? "Online" : "Indisponível");
  byId("waf-status-dot").className = `status-dot ${online ? "online" : "offline"}`;

  const deploymentWrapper = data?.implantacao;
  const deployment = deploymentWrapper?.disponivel ? deploymentWrapper.dados : null;
  const model = deployment?.modelo?.toUpperCase();
  const modelName = deployment?.modelo === "bp"
    ? "Backpropagation"
    : deployment?.modelo === "ag"
      ? "Algoritmo Genético"
      : "Modelo não disponível";

  setText("deployed-model", model || "N/D");
  setText("deployed-method", modelName);
  setText("deployed-threshold", available(deployment?.threshold)
    ? formatNumber(deployment.threshold, 3)
    : "N/D");
  setText("last-selection", formatDate(deployment?.data_hora_selecao));
  setText("selection-reason", deployment?.criterio || "Não disponível");
  setText("flow-model", model ? `MLP · ${model}` : "MLP");
  setText("flow-threshold", available(deployment?.threshold)
    ? `Risco > ${formatNumber(deployment.threshold, 3)}`
    : "Risco > N/D");

  const network = data?.rede?.disponivel ? data.rede : null;
  setText("network-inputs", network?.entradas ?? "N/D");
  setText("network-hidden", network?.ocultos ?? "N/D");
  setText("network-output", network?.saidas ?? "N/D");
  setText("network-weights", network?.quantidade_pesos ?? "N/D");
  renderNetworkMini(network?.arquitetura);

  const dataset = data?.dataset?.disponivel ? data.dataset : null;
  setText("dataset-total", dataset ? formatNumber(dataset.total, 0) : "N/D");
  setText("dataset-train", dataset ? formatNumber(dataset.treino, 0) : "N/D");
  setText("dataset-validation", dataset ? formatNumber(dataset.validacao, 0) : "N/D");
  setText("dataset-test", dataset ? formatNumber(dataset.teste, 0) : "N/D");

  const metrics = deployment?.metricas_validacao;
  setText("overview-accuracy", formatMetric(metrics?.acuracia));
  setText("overview-precision", formatMetric(metrics?.precisao));
  setText("overview-recall", formatMetric(metrics?.recall));
  setText("overview-f1", formatMetric(metrics?.f1));
}

function renderNetworkMini(architecture) {
  const container = byId("network-architecture");
  clear(container);

  const values = Array.isArray(architecture) ? architecture : ["—", "—", "—"];
  values.forEach((value, index) => {
    container.appendChild(element("span", "", value));
    if (index < values.length - 1) container.appendChild(element("i"));
  });
}

function renderMonitor() {
  const history = appState.history;
  const rows = history.itens || [];
  const summary = history.resumo || {};
  const monitorState = {
    history,
    session: appState.session,
    simulation: appState.data?.simulacao
  };
  const monitorFingerprint = fingerprint(monitorState);
  if (appState.fingerprints.monitor === monitorFingerprint) return;
  appState.fingerprints.monitor = monitorFingerprint;

  const allowed = Number(summary.liberadas || 0);
  const blocked = Number(summary.bloqueadas || 0);
  const total = Number(summary.total || 0);
  const riskAverage = summary.risco_medio;

  setText("requests-total", formatNumber(total, 0));
  setText("requests-allowed", formatNumber(allowed, 0));
  setText("requests-blocked", formatNumber(blocked, 0));
  setText("requests-allowed-percent", total ? `${formatNumber(allowed / total * 100, 1)}%` : "0%");
  setText("requests-blocked-percent", total ? `${formatNumber(blocked / total * 100, 1)}%` : "0%");
  setText("requests-risk-average", available(riskAverage) ? formatNumber(riskAverage, 4) : "N/D");
  setText("requests-updated", history.atualizado_em
    ? `Log atualizado ${formatDate(history.atualizado_em, true)}`
    : "Log ainda não disponível");

  renderSessionState();
  renderRequestsTable(rows);
  renderHistoryPagination();
  renderLatestOutcome();
}

function simulationBelongsToCurrentSession() {
  const simulation = appState.data?.simulacao;
  const started = simulation?.iniciado_em
    ? new Date(simulation.iniciado_em).getTime()
    : NaN;
  const sessionStart = appState.session.start
    ? new Date(appState.session.start).getTime()
    : NaN;
  const sessionEnd = appState.session.end
    ? new Date(appState.session.end).getTime()
    : Infinity;

  if (
    !Number.isFinite(started)
    || !Number.isFinite(sessionStart)
    || started < sessionStart
    || started > sessionEnd
  ) {
    return false;
  }
  return Number(simulation?.historico_total || 0) > 0;
}

async function loadHistoryPage(options = {}) {
  if (!appState.session.start) {
    appState.history = emptyHistory();
    renderMonitor();
    return;
  }

  const requestedPage = options.preservePage ? appState.history.pagina : 1;
  const params = new URLSearchParams({
    pagina: String(requestedPage || 1),
    por_pagina: "10"
  });
  let endpoint = "api/requests";
  if (simulationBelongsToCurrentSession()) {
    endpoint = "api/simulation/history";
  } else {
    params.set("inicio", appState.session.start);
    if (appState.session.end) params.set("fim", appState.session.end);
  }

  try {
    const response = await fetch(`${endpoint}?${params}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.erro || `HTTP ${response.status}`);
    appState.history = payload;
  } catch {
    appState.history = emptyHistory();
  }
  renderMonitor();
}

function renderHistoryPagination() {
  const history = appState.history;
  const total = Number(history.total || 0);
  const page = Number(history.pagina || 1);
  const pageSize = Number(history.por_pagina || 10);
  const pages = Number(history.paginas || 1);
  const first = total ? (page - 1) * pageSize + 1 : 0;
  const last = total ? Math.min(page * pageSize, total) : 0;
  setText("history-range", `Exibindo ${first}–${last} de ${total} requisições`);
  setText("history-page-status", `Página ${page} de ${pages}`);
  byId("history-prev").disabled = page <= 1;
  byId("history-next").disabled = page >= pages;
}

function renderLatestOutcome() {
  const latest = appState.history.itens?.[0];
  const safe = byId("outcome-safe");
  const blocked = byId("outcome-blocked");
  safe.classList.toggle("latest", latest?.decisao === "LIBERADA");
  blocked.classList.toggle("latest", latest?.decisao === "BLOQUEADA");
}

function renderSessionState() {
  const { start, end } = appState.session;
  const indicator = byId("session-indicator");
  const stopButton = byId("stop-monitor");
  const saveButton = byId("save-session");

  if (!start) {
    indicator.className = "session-indicator idle";
    setText("session-label", "Monitoramento inativo");
    setText("session-period", "Nenhuma sessão de demonstração está sendo contabilizada.");
    stopButton.disabled = true;
    saveButton.disabled = true;
    byId("start-monitor").textContent = "Iniciar monitoramento";
    updateSimulationControls();
    return;
  }

  if (end) {
    indicator.className = "session-indicator idle";
    setText("session-label", "Sessão encerrada");
    setText("session-period", `Período: ${formatDate(start, true)} — ${formatDate(end, true)}`);
    stopButton.disabled = true;
    saveButton.disabled = false;
    byId("start-monitor").textContent = "Iniciar nova sessão";
  } else {
    indicator.className = "session-indicator live";
    setText("session-label", "Monitoramento ativo");
    setText("session-period", `Requisições processadas desde ${new Date(start).toLocaleTimeString("pt-BR")}`);
    stopButton.disabled = false;
    saveButton.disabled = false;
    byId("start-monitor").textContent = "Reiniciar monitoramento";
  }
  updateSimulationControls();
}

function renderRequestsTable(rows) {
  const body = byId("requests-table");
  clear(body);

  if (!rows.length) {
    const row = element("tr");
    const cell = element("td", "empty-cell", "Nenhuma requisição registrada neste período.");
    cell.colSpan = 9;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  rows.forEach((request) => {
    const row = element("tr");
    row.appendChild(element("td", "", formatDate(request.data_hora, true)));
    row.appendChild(element("td", "", request.metodo || "N/D"));
    const path = element("td", "path-cell", request.caminho || "/");
    path.title = request.caminho || "/";
    row.appendChild(path);
    row.appendChild(element("td", "", formatNumber(request.risco, 4)));
    row.appendChild(element("td", "", formatNumber(request.threshold, 3)));

    const decisionCell = element("td");
    const isBlocked = request.decisao === "BLOQUEADA";
    decisionCell.appendChild(element(
      "span",
      `decision-badge ${isBlocked ? "blocked" : "safe"}`,
      request.decisao || "N/D"
    ));
    row.appendChild(decisionCell);
    row.appendChild(element("td", "", request.status_http ?? "N/D"));
    row.appendChild(element(
      "td",
      request.rotulo_real ? "truth-label" : "",
      request.rotulo_real || "—"
    ));
    const resultCell = element("td");
    if (request.resultado) {
      resultCell.appendChild(element(
        "span",
        `result-badge result-${request.resultado.toLowerCase()}`,
        request.resultado
      ));
    } else {
      resultCell.textContent = "—";
    }
    row.appendChild(resultCell);
    body.appendChild(row);
  });
}

function infoItem(label, value, className = "info-item") {
  const unavailable = value === "N/D" || value === "Não disponível";
  const item = element(
    "div",
    `${className}${unavailable ? " unavailable-value" : ""}`.trim()
  );
  if (unavailable) item.title = "Dados ainda não gerados";
  item.appendChild(element("small", "", label));
  item.appendChild(element("strong", "", value));
  return item;
}

function renderInfoGrid(id, items, className = "info-item") {
  const container = byId(id);
  clear(container);
  items.forEach(([label, value]) => container.appendChild(infoItem(label, value, className)));
}

function renderModels() {
  const diagnostics = appState.data?.diagnosticos || {};
  const bp = diagnostics.bp;
  const ag = diagnostics.ag;
  const bpConfig = appState.data?.treinamento?.bp || {};
  const agConfig = appState.data?.treinamento?.ag || {};
  const network = appState.data?.rede;

  renderAvailability("bp-availability", bp?.disponivel, "Disponível", "Ainda não disponível");
  renderAvailability("ag-availability", ag?.disponivel, "Disponível", "Ainda não disponível");

  renderInfoGrid("bp-training-stats", [
    ["Arquitetura", Array.isArray(bpConfig.rede) ? bpConfig.rede.join(" → ") : "N/D"],
    ["Épocas", bpConfig.epocas ?? "N/D"],
    ["Taxa de aprendizagem", formatNumber(bpConfig.taxa, 4)],
    ["MSE treino final", formatNumber(bp?.final?.mse_treino, 6)],
    ["MSE validação final", formatNumber(bp?.final?.mse_validacao, 6)],
    ["Gap treino–validação", formatNumber(bp?.final?.gap_treino_validacao, 6)],
    ["Tempo total", formatSeconds(bp?.tempo_total)],
    ["Tempo médio / época", formatSeconds(bp?.tempo_medio)],
    ["CPU total", formatSeconds(bp?.cpu_total)],
    ["CPU média / época", formatSeconds(bp?.cpu_media)]
  ]);

  const selectionNames = { 1: "Torneio", 2: "Roleta" };
  const crossoverNames = { 1: "Um ponto", 2: "SBX" };
  const mutationNames = { 1: "Uniforme", 2: "Gaussiana", 3: "Polinomial" };

  renderInfoGrid("ag-training-stats", [
    ["Arquitetura", Array.isArray(agConfig.rede) ? agConfig.rede.join(" → ") : "N/D"],
    ["População", agConfig.npop ?? "N/D"],
    ["Gerações", agConfig.geracoes ?? "N/D"],
    ["Número de genes", network?.quantidade_pesos ?? "N/D"],
    ["Intervalo dos pesos", available(agConfig.rmin) && available(agConfig.rmax) ? `[${agConfig.rmin}, ${agConfig.rmax}]` : "N/D"],
    ["Seleção", selectionNames[agConfig.tipo_selecao] || "N/D"],
    ["Crossover", crossoverNames[agConfig.tipo_crossover] || "N/D"],
    ["Mutação", mutationNames[agConfig.tipo_mutacao] || "N/D"],
    ["MSE treino final", formatNumber(ag?.final?.mse_treino, 6)],
    ["MSE validação final", formatNumber(ag?.final?.mse_validacao, 6)],
    ["Gap treino–validação", formatNumber(ag?.final?.gap_treino_validacao, 6)],
    ["Tempo total", formatSeconds(ag?.tempo_total)],
    ["Tempo médio / geração", formatSeconds(ag?.tempo_medio)],
    ["CPU total", formatSeconds(ag?.cpu_total)],
    ["CPU média / geração", formatSeconds(ag?.cpu_media)]
  ]);

  const bpWeights = appState.data?.pesos?.bp;
  const agWeights = appState.data?.pesos?.ag;
  renderInfoGrid("bp-diagnostics", [
    ["Última melhoria relevante", bp?.ultima_melhoria ? `Época ${bp.ultima_melhoria}` : "N/D"],
    ["Épocas sem melhoria", bp?.sem_melhoria ?? "N/D"],
    ["Ativações em saturação", available(bp?.final?.percentual_saturacao_oculta) ? `${formatNumber(bp.final.percentual_saturacao_oculta, 2)}%` : "N/D"],
    ["Magnitude média dos pesos", formatNumber(bpWeights?.magnitude_media, 5)],
    ["Desvio dos pesos", formatNumber(bpWeights?.desvio, 5)],
    ["Menor / maior peso", available(bpWeights?.menor) ? `${formatNumber(bpWeights.menor, 4)} / ${formatNumber(bpWeights.maior, 4)}` : "N/D"],
    ["ΔW médio · camada 1", formatNumber(bp?.final?.camada_1_delta_magnitude_media, 7)],
    ["ΔW máximo · camada 1", formatNumber(bp?.final?.camada_1_delta_magnitude_maxima, 7)],
    ["ΔW médio · camada 2", formatNumber(bp?.final?.camada_2_delta_magnitude_media, 7)],
    ["ΔW máximo · camada 2", formatNumber(bp?.final?.camada_2_delta_magnitude_maxima, 7)]
  ], "diagnostic-item");

  renderInfoGrid("ag-diagnostics", [
    ["Última melhoria relevante", ag?.ultima_melhoria ? `Geração ${ag.ultima_melhoria}` : "N/D"],
    ["Gerações sem melhoria", ag?.sem_melhoria ?? "N/D"],
    ["Diversidade final", formatNumber(ag?.final?.diversidade, 5)],
    ["Média dos genes", formatNumber(ag?.final?.media_genes, 5)],
    ["Desvio dos genes", formatNumber(ag?.final?.desvio_genes, 5)],
    ["Menor / maior gene", available(ag?.final?.menor_gene) ? `${formatNumber(ag.final.menor_gene, 3)} / ${formatNumber(ag.final.maior_gene, 3)}` : "N/D"],
    ["Genes próximos aos limites", available(ag?.final?.percentual_limites) ? `${formatNumber(ag.final.percentual_limites, 2)}%` : "N/D"],
    ["Magnitude média · melhor", formatNumber(agWeights?.magnitude_media, 5)]
  ], "diagnostic-item");

  renderNeurons(bp?.final);
  drawLearningChart("bp-chart", bp?.linhas || [], "epoca");
  drawLearningChart("ag-chart", ag?.linhas || [], "geracao");
}

function renderAvailability(id, isAvailable, availableText, unavailableText) {
  const node = byId(id);
  node.textContent = isAvailable ? availableText : unavailableText;
  node.className = `availability ${isAvailable ? "available" : "unavailable"}`;
}

function renderNeurons(finalRow) {
  const container = byId("hidden-neurons");
  clear(container);

  for (let index = 1; index <= 10; index += 1) {
    const value = finalRow?.[`neuronio_${index}_media_ativacao`]
      ?? finalRow?.[`neuronio_${index}_media`];
    const cell = element("div", "neuron-cell");
    cell.appendChild(element("span", "", `Neurônio ${index}`));
    cell.appendChild(element("strong", "", available(value) ? formatNumber(value, 3) : "N/D"));
    container.appendChild(cell);
  }
}

function drawLearningChart(canvasId, rows, axisField) {
  const canvas = byId(canvasId);
  const width = Math.max(canvas.clientWidth, 320);
  const height = 260;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const values = rows.flatMap((row) => [row.mse_treino, row.mse_validacao])
    .map(Number)
    .filter(Number.isFinite);

  if (!rows.length || !values.length) {
    context.fillStyle = "#607078";
    context.font = "12px system-ui";
    context.textAlign = "center";
    context.fillText("Dados de diagnóstico ainda não disponíveis", width / 2, height / 2);
    return;
  }

  const padding = { top: 22, right: 15, bottom: 31, left: 52 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const maximum = Math.max(...values);
  const minimum = Math.min(...values);
  const range = maximum - minimum || maximum || 1;

  context.strokeStyle = "#e2e8ea";
  context.fillStyle = "#738289";
  context.font = "10px system-ui";
  context.textAlign = "right";
  context.lineWidth = 1;

  for (let line = 0; line <= 4; line += 1) {
    const y = padding.top + plotHeight * line / 4;
    const label = maximum - range * line / 4;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
    context.fillText(label.toFixed(4), padding.left - 7, y + 3);
  }

  const drawSeries = (field, color) => {
    context.beginPath();
    context.strokeStyle = color;
    context.lineWidth = 2;
    rows.forEach((row, index) => {
      const x = padding.left + (rows.length === 1 ? 0 : index / (rows.length - 1)) * plotWidth;
      const value = Number(row[field]);
      const y = padding.top + (maximum - value) / range * plotHeight;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
  };

  drawSeries("mse_treino", "#176b73");
  drawSeries("mse_validacao", "#b96b3d");

  context.textAlign = "left";
  context.fillStyle = "#176b73";
  context.fillRect(padding.left, 4, 15, 3);
  context.fillStyle = "#526269";
  context.fillText("Treino", padding.left + 20, 9);
  context.fillStyle = "#b96b3d";
  context.fillRect(padding.left + 76, 4, 15, 3);
  context.fillStyle = "#526269";
  context.fillText("Validação", padding.left + 96, 9);

  context.textAlign = "center";
  context.fillText("1", padding.left, height - 8);
  context.fillText(String(rows[rows.length - 1]?.[axisField] ?? rows.length), width - padding.right, height - 8);
  context.fillStyle = "#738289";
  context.fillText(axisField === "epoca" ? "Épocas" : "Gerações", width / 2, height - 8);
}

function renderEvaluations() {
  const wrapper = appState.data?.avaliacao;
  const evaluation = wrapper?.disponivel ? wrapper.dados : null;
  renderEvaluationGroup("validation-evaluations", evaluation?.validacao, "Validação");
  renderEvaluationGroup("test-evaluation", evaluation?.teste, "Teste final");
}

function renderEvaluationGroup(containerId, group, label) {
  const container = byId(containerId);
  clear(container);

  if (!group || typeof group !== "object" || !Object.keys(group).length) {
    container.appendChild(element("div", "empty-state", `${label} ainda não disponível.`));
    return;
  }

  Object.entries(group).forEach(([model, metrics]) => {
    container.appendChild(evaluationCard(model, metrics, label));
  });
}

function evaluationCard(model, metrics, label) {
  const card = element("article", "evaluation-card");
  const matrixSide = element("div");
  matrixSide.appendChild(element("h4", "", `${label} · ${model.toUpperCase()}`));
  matrixSide.appendChild(element("span", "threshold-note", `Threshold ${formatNumber(metrics.threshold, 3)}`));
  matrixSide.appendChild(confusionMatrix(metrics));

  const metricsSide = element("div");
  metricsSide.appendChild(element("h4", "", "Métricas de classificação"));
  const grid = element("div", "evaluation-metrics");
  [
    ["Acurácia", formatMetric(metrics.acuracia)],
    ["Precisão", formatMetric(metrics.precisao)],
    ["Recall", formatMetric(metrics.recall)],
    ["F1", formatMetric(metrics.f1)]
  ].forEach(([name, value]) => grid.appendChild(infoItem(name, value, "")));
  metricsSide.appendChild(grid);
  card.append(matrixSide, metricsSide);
  return card;
}

function confusionMatrix(metrics) {
  const matrix = element("div", "confusion-matrix");
  matrix.appendChild(element("span", "matrix-label axis-label", "Real ↓\nPredito →"));
  matrix.appendChild(element("span", "matrix-label", "Normal"));
  matrix.appendChild(element("span", "matrix-label", "Ataque"));
  matrix.appendChild(element("span", "matrix-label axis-label", "Normal"));
  matrix.appendChild(matrixCell("TN", metrics.tn, false));
  matrix.appendChild(matrixCell("FP", metrics.fp, true));
  matrix.appendChild(element("span", "matrix-label axis-label", "Ataque"));
  matrix.appendChild(matrixCell("FN", metrics.fn, true));
  matrix.appendChild(matrixCell("TP", metrics.tp, false));
  return matrix;
}

function matrixCell(label, value, error) {
  const numericValue = Number(value);
  const errorClass = error
    ? numericValue > 0 ? " error-active" : " error-zero"
    : "";
  const cell = element("div", `matrix-cell${errorClass}`);
  const content = element("div");
  content.appendChild(element("strong", "", value ?? "N/D"));
  content.appendChild(element("small", "", label));
  cell.appendChild(content);
  return cell;
}

function renderSelection() {
  const wrapper = appState.data?.implantacao;
  const selection = wrapper?.disponivel ? wrapper.dados : null;
  setText("alpha-fn", available(selection?.alpha_fn) ? formatNumber(selection.alpha_fn, 2) : "N/D");
  setText("beta-fp", available(selection?.beta_fp) ? formatNumber(selection.beta_fp, 2) : "N/D");
  setText("selected-model", selection?.modelo?.toUpperCase() || "N/D");
  setText("selected-threshold", available(selection?.threshold)
    ? `Threshold ${formatNumber(selection.threshold, 3)}`
    : "Threshold N/D");
  setText("selected-reason", selection?.criterio || "Seleção ainda não disponível.");

  const container = byId("selection-candidates");
  clear(container);
  const candidates = selection?.candidatos;

  if (!candidates) {
    container.appendChild(element("div", "empty-state", "Resultados da seleção ainda não disponíveis."));
    return;
  }

  Object.entries(candidates).forEach(([model, metrics]) => {
    const card = element("article", `candidate-card${selection.modelo === model ? " selected" : ""}`);
    card.appendChild(element("h4", "", model.toUpperCase()));
    const list = element("dl");
    [
      ["Threshold", formatNumber(metrics.threshold, 3)],
      ["FN", metrics.fn ?? "N/D"],
      ["FP", metrics.fp ?? "N/D"],
      ["Custo", formatNumber(metrics.custo_seguranca, 3)],
      ["Precisão", formatMetric(metrics.precisao)],
      ["Recall", formatMetric(metrics.recall)],
      ["F1", formatMetric(metrics.f1)]
    ].forEach(([name, value]) => {
      const row = element("div");
      row.appendChild(element("dt", "", name));
      const semanticClass = name === "FN" && value !== "N/D"
        ? Number(value) === 0 ? "semantic-positive" : "semantic-attention"
        : "";
      row.appendChild(element("dd", semanticClass, value));
      list.appendChild(row);
    });
    card.appendChild(list);
    container.appendChild(card);
  });
}

function renderSimulation() {
  const simulation = appState.data?.simulacao;
  const datasetAvailable = Boolean(simulation?.dataset?.disponivel);
  const serviceAvailable = Boolean(simulation?.servico_local_disponivel);
  const statusNames = {
    idle: "Pronta para iniciar",
    running: "Simulação em andamento",
    completed: "Avaliação concluída",
    error: "Execução interrompida"
  };

  setText(
    "simulation-message",
    simulation?.mensagem || "Verificando dataset e serviço local…"
  );
  setText(
    "simulation-dataset",
    datasetAvailable ? "2 arquivos locais disponíveis" : "Arquivos não disponíveis"
  );
  setText(
    "simulation-service",
    serviceAvailable ? "Disponível" : "Indisponível"
  );
  setText(
    "simulation-status",
    statusNames[simulation?.status] || "Aguardando"
  );

  const processed = Number(simulation?.processadas || 0);
  const total = Number(simulation?.total || 0);
  const progress = byId("simulation-progress");
  progress.max = Math.max(total, 1);
  progress.value = Math.min(processed, Math.max(total, 1));
  setText(
    "simulation-progress-label",
    simulation?.status === "running"
      ? "Simulação em andamento"
      : simulation?.status === "completed"
        ? "Simulação concluída"
        : "Aguardando execução"
  );
  setText("simulation-progress-count", `${processed} / ${total}`);
  setText("simulation-normal-count", simulation?.normais_reais || 0);
  setText("simulation-attack-count", simulation?.ataques_reais || 0);
  setText("simulation-allowed-count", simulation?.liberadas || 0);
  setText("simulation-blocked-count", simulation?.bloqueadas || 0);

  const confusion = simulation?.confusao || {};
  const metrics = simulation?.metricas || {};
  setText("simulation-tn", confusion.tn || 0);
  setText("simulation-fp", confusion.fp || 0);
  setText("simulation-fn", confusion.fn || 0);
  setText("simulation-tp", confusion.tp || 0);
  setText("simulation-accuracy", formatMetric(metrics.accuracy || 0));
  setText("simulation-precision", formatMetric(metrics.precision || 0));
  setText("simulation-recall", formatMetric(metrics.recall || 0));
  setText("simulation-f1", formatMetric(metrics.f1 || 0));
  setText("simulation-fpr", formatMetric(metrics.false_positive_rate || 0));
  setText("simulation-fnr", formatMetric(metrics.false_negative_rate || 0));
  setText(
    "simulation-evaluated",
    `${simulation?.avaliadas || 0} avaliadas`
  );
  setText(
    "simulation-errors-summary",
    simulation?.erros
      ? `${simulation.erros} requisição(ões) não produziram decisão 200/403 e foram excluídas das métricas.`
      : "Todas as requisições processadas produziram uma decisão válida do WAF."
  );

  byId("simulation-results").hidden = processed === 0;
  const errorNode = byId("simulation-error");
  errorNode.hidden = simulation?.status !== "error";
  if (simulation?.status === "error") {
    errorNode.textContent = simulation.mensagem || "Falha na simulação controlada.";
  }
  renderFeatureAnalysis();
  updateSimulationControls();
}

function featureStatsText(stats, type) {
  if (!stats || !stats.quantidade) return "Sem observações";
  if (type === "binaria") {
    const distribution = `0: ${formatMetric(stats.percentual_zero)} · 1: ${formatMetric(stats.percentual_um)}`;
    return stats.acima_limite
      ? `${distribution} · acima ${stats.acima_limite} (${formatMetric(stats.percentual_acima_limite)})`
      : distribution;
  }
  return [
    `média ${formatNumber(stats.media, 3)}`,
    `mediana ${formatNumber(stats.mediana, 3)}`,
    `P95 ${formatNumber(stats.p95, 3)}`,
    `mín–máx ${formatNumber(stats.minimo, 3)}–${formatNumber(stats.maximo, 3)}`,
    `acima ${stats.acima_limite} (${formatMetric(stats.percentual_acima_limite)})`,
    `clipping ${stats.clipping} (${formatMetric(stats.percentual_clipping)})`
  ].join(" · ");
}

function renderFeatureAnalysis() {
  const analysis = appState.data?.analise_features;
  const section = byId("feature-analysis");
  section.hidden = !analysis?.disponivel;
  if (!analysis?.disponivel) return;

  const comparisonBody = byId("feature-comparison-table");
  const classBody = byId("feature-class-table");
  const clippingBody = byId("feature-clipping-table");
  clear(comparisonBody);
  clear(classBody);
  clear(clippingBody);

  analysis.schema.forEach((feature) => {
    const name = feature.nome;
    const original = analysis.original.features[name];
    const csic = analysis.csic.features[name];
    const comparisonRow = element("tr");
    comparisonRow.appendChild(element("th", "feature-name", name));
    comparisonRow.appendChild(element("td", "", feature.tipo));
    comparisonRow.appendChild(element("td", "", formatNumber(feature.limite, 3)));
    comparisonRow.appendChild(element("td", "stats-original", featureStatsText(original, feature.tipo)));
    comparisonRow.appendChild(element("td", "stats-csic", featureStatsText(csic, feature.tipo)));
    comparisonBody.appendChild(comparisonRow);

    const normal = analysis.csic.classes.NORMAL.features[name];
    const attack = analysis.csic.classes.ATAQUE.features[name];
    const classRow = element("tr");
    classRow.appendChild(element("th", "feature-name", name));
    classRow.appendChild(element("td", "", featureStatsText(normal, feature.tipo)));
    classRow.appendChild(element("td", "", featureStatsText(attack, feature.tipo)));
    classBody.appendChild(classRow);
  });

  analysis.impacto_limites.forEach((impact) => {
    const row = element("tr");
    const percentage = impact.percentual_csic_acima || 0;
    row.classList.toggle("has-clipping", percentage > 0);
    row.appendChild(element("th", "feature-name", impact.nome));
    row.appendChild(element("td", "", formatNumber(impact.limite, 3)));
    row.appendChild(element("td", "", formatNumber(impact.maximo_original, 3)));
    row.appendChild(element("td", "", formatNumber(impact.maximo_csic, 3)));
    row.appendChild(element("td", "", formatMetric(impact.percentual_original_acima)));
    row.appendChild(element("td", "", formatMetric(percentage)));
    clippingBody.appendChild(row);
  });

  const counts = appState.data?.simulacao?.exemplos_disponiveis || {};
  ["tn", "fp", "fn", "tp"].forEach((result) => {
    setText(`example-count-${result}`, counts[result.toUpperCase()] || 0);
  });
}

async function selectExampleResult(result) {
  appState.selectedExampleResult = result;
  appState.selectedExample = null;
  document.querySelectorAll(".example-filter").forEach((button) => {
    button.classList.toggle("active", button.dataset.result === result);
  });
  const select = byId("diagnostic-example-select");
  clear(select);
  select.disabled = true;
  byId("example-detail").hidden = true;
  byId("example-empty").hidden = false;

  try {
    const response = await fetch(`api/simulation/examples?resultado=${encodeURIComponent(result)}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.erro || `HTTP ${response.status}`);
    appState.exampleList = payload.itens || [];
    if (!appState.exampleList.length) {
      select.appendChild(element("option", "", `Nenhum exemplo ${result} disponível`));
      setText("example-empty", `A simulação atual não contém exemplos ${result}.`);
      return;
    }
    appState.exampleList.forEach((item) => {
      const option = element("option", "", `#${item.id} · ${item.metodo} ${item.caminho}`);
      option.value = item.id;
      select.appendChild(option);
    });
    select.disabled = false;
    await loadExample(select.value);
  } catch (error) {
    setText("example-empty", error.message || "Não foi possível carregar os exemplos.");
  }
}

async function loadExample(id) {
  if (!id) return;
  try {
    const response = await fetch(`api/simulation/example?id=${encodeURIComponent(id)}`, { cache: "no-store" });
    const item = await response.json();
    if (!response.ok) throw new Error(item.erro || `HTTP ${response.status}`);
    appState.selectedExample = item;
    renderExampleDetail(item);
  } catch (error) {
    byId("example-detail").hidden = true;
    byId("example-empty").hidden = false;
    setText("example-empty", error.message || "Não foi possível carregar o exemplo.");
  }
}

function renderExampleDetail(item) {
  const metadata = byId("example-metadata");
  clear(metadata);
  [
    ["Horário", formatDate(item.data_hora, true)],
    ["Requisição", `${item.metodo} ${item.caminho}`],
    ["Rótulo real", item.rotulo_real],
    ["Decisão", item.decisao],
    ["Resultado", item.resultado],
    ["Risco / threshold", `${formatNumber(item.risco, 6)} / ${formatNumber(item.threshold, 3)}`]
  ].forEach(([label, value]) => {
    const wrapper = element("div");
    wrapper.appendChild(element("dt", "", label));
    wrapper.appendChild(element("dd", "", value));
    metadata.appendChild(wrapper);
  });

  const body = byId("example-features-table");
  clear(body);
  (item.features || []).forEach((feature) => {
    const row = element("tr", feature.clipping ? "has-clipping" : "");
    row.appendChild(element("th", "feature-name", feature.nome));
    row.appendChild(element("td", "", formatNumber(feature.valor_bruto, 6)));
    row.appendChild(element("td", "", formatNumber(feature.limite, 3)));
    row.appendChild(element("td", "", formatNumber(feature.valor_normalizado, 6)));
    row.appendChild(element(
      "td",
      "",
      feature.clipping
        ? `Excedeu ${formatNumber(feature.limite, 3)} → 1,000`
        : "Não"
    ));
    body.appendChild(row);
  });
  byId("example-empty").hidden = true;
  byId("example-detail").hidden = false;
}

function updateSimulationControls() {
  const button = byId("start-simulation");
  if (!button) return;
  const simulation = appState.data?.simulacao;
  const activeSession = Boolean(appState.session.start && !appState.session.end);
  const running = simulation?.status === "running";
  button.disabled = (
    appState.simulationSubmitting
    || running
    || !activeSession
    || !simulation?.dataset?.disponivel
    || !simulation?.servico_local_disponivel
  );
  button.textContent = running ? "Simulação em andamento" : "Iniciar simulação";
  byId("simulation-quantity").disabled = running;
  document.querySelectorAll('input[name="simulation-mode"]').forEach((input) => {
    input.disabled = running;
  });
}

async function startSimulation() {
  const activeSession = Boolean(appState.session.start && !appState.session.end);
  if (!activeSession || appState.simulationSubmitting) return;

  const selectedMode = document.querySelector(
    'input[name="simulation-mode"]:checked'
  );
  const errorNode = byId("simulation-error");
  errorNode.hidden = true;
  appState.simulationSubmitting = true;
  updateSimulationControls();

  try {
    const response = await fetch("api/simulation/start", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        modo: selectedMode?.value || "MISTO",
        quantidade: Number(byId("simulation-quantity").value),
        monitor_ativo: true
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.erro || `HTTP ${response.status}`);
    appState.history = emptyHistory();
    appState.selectedExampleResult = null;
    appState.exampleList = [];
    appState.selectedExample = null;
    renderMonitor();
    await loadData({ manual: true });
  } catch (error) {
    errorNode.textContent = error.message || "Não foi possível iniciar a simulação.";
    errorNode.hidden = false;
  } finally {
    appState.simulationSubmitting = false;
    updateSimulationControls();
  }
}

function startMonitoring() {
  appState.session = { start: new Date().toISOString(), end: null };
  appState.history = emptyHistory();
  saveSessionState();
  renderMonitor();
  loadHistoryPage();
}

function stopMonitoring() {
  if (!appState.session.start) return;
  appState.session.end = new Date().toISOString();
  saveSessionState();
  renderMonitor();
  loadHistoryPage({ preservePage: true });
}

function saveSessionSummary() {
  const historySummary = appState.history.resumo || {};
  const total = Number(historySummary.total || 0);
  const blocked = Number(historySummary.bloqueadas || 0);
  const allowed = Number(historySummary.liberadas || 0);
  const summary = {
    inicio: appState.session.start,
    fim: appState.session.end || new Date().toISOString(),
    total,
    liberadas: allowed,
    bloqueadas: blocked,
    percentual_liberadas: total ? allowed / total * 100 : 0,
    percentual_bloqueadas: total ? blocked / total * 100 : 0
  };
  const blob = new Blob([JSON.stringify(summary, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `resumo-monitoramento-${Date.now()}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function setupNavigation() {
  const links = [...document.querySelectorAll(".nav-link")];
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((link) => {
        const active = link.getAttribute("href") === `#${entry.target.id}`;
        link.classList.toggle("active", active);
        if (active) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    });
  }, { rootMargin: "-30% 0px -60% 0px" });

  sections.forEach((section) => observer.observe(section));
}

function setupNeuralBackground() {
  const canvas = document.createElement("canvas");
  canvas.className = "neural-background";
  canvas.setAttribute("aria-hidden", "true");
  document.body.prepend(canvas);

  const context = canvas.getContext("2d", { alpha: true });
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const precisePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const primaryColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--primary")
    .trim();
  const colorMatch = primaryColor.match(
    /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i
  );
  const color = colorMatch
    ? colorMatch.slice(1).map((part) => parseInt(part, 16))
    : [23, 107, 115];

  let width = 0;
  let height = 0;
  let particles = [];
  let animationFrame = null;
  let resizeFrame = null;
  let previousTimestamp = 0;

  const pointer = {
    x: 0,
    y: 0,
    targetX: 0,
    targetY: 0,
    active: false
  };

  function rgba(alpha) {
    return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
  }

  function createParticle() {
    return {
      x: Math.random() * width,
      y: Math.random() * height,
      velocityX: (Math.random() - 0.5) * 0.18,
      velocityY: (Math.random() - 0.5) * 0.18,
      radius: 1.2 + Math.random() * 1.35
    };
  }

  function resizeCanvas() {
    width = window.innerWidth;
    height = window.innerHeight;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);

    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    const particleCount = Math.max(
      42,
      Math.min(105, Math.round(width * height / 15000))
    );
    particles = Array.from({ length: particleCount }, createParticle);

    pointer.x = width / 2;
    pointer.y = height / 2;
    pointer.targetX = pointer.x;
    pointer.targetY = pointer.y;
    drawFrame(false);
  }

  function displayPosition(particle) {
    if (!pointer.active || reducedMotion.matches) {
      return { x: particle.x, y: particle.y };
    }

    const deltaX = particle.x - pointer.x;
    const deltaY = particle.y - pointer.y;
    const distance = Math.hypot(deltaX, deltaY) || 1;
    const influenceRadius = 190;

    if (distance >= influenceRadius) {
      return { x: particle.x, y: particle.y };
    }

    const influence = (1 - distance / influenceRadius) ** 2;
    const displacement = influence * 16;
    return {
      x: particle.x + deltaX / distance * displacement,
      y: particle.y + deltaY / distance * displacement
    };
  }

  function updateParticles() {
    pointer.x += (pointer.targetX - pointer.x) * 0.075;
    pointer.y += (pointer.targetY - pointer.y) * 0.075;

    particles.forEach((particle) => {
      particle.x += particle.velocityX;
      particle.y += particle.velocityY;

      if (particle.x < -10) particle.x = width + 10;
      else if (particle.x > width + 10) particle.x = -10;

      if (particle.y < -10) particle.y = height + 10;
      else if (particle.y > height + 10) particle.y = -10;
    });
  }

  function drawFrame(update = true) {
    context.clearRect(0, 0, width, height);
    if (update && !reducedMotion.matches) updateParticles();

    if (pointer.active && !reducedMotion.matches) {
      const glow = context.createRadialGradient(
        pointer.x,
        pointer.y,
        0,
        pointer.x,
        pointer.y,
        210
      );
      glow.addColorStop(0, rgba(0.075));
      glow.addColorStop(1, rgba(0));
      context.fillStyle = glow;
      context.fillRect(
        pointer.x - 210,
        pointer.y - 210,
        420,
        420
      );
    }

    const positions = particles.map(displayPosition);
    const connectionDistance = width < 700 ? 108 : 138;

    for (let first = 0; first < positions.length; first += 1) {
      for (let second = first + 1; second < positions.length; second += 1) {
        const deltaX = positions[first].x - positions[second].x;
        const deltaY = positions[first].y - positions[second].y;
        const distance = Math.hypot(deltaX, deltaY);

        if (distance >= connectionDistance) continue;

        const alpha = (1 - distance / connectionDistance) * 0.19;
        context.beginPath();
        context.moveTo(positions[first].x, positions[first].y);
        context.lineTo(positions[second].x, positions[second].y);
        context.strokeStyle = rgba(alpha);
        context.lineWidth = 0.8;
        context.stroke();
      }
    }

    particles.forEach((particle, index) => {
      const position = positions[index];
      context.beginPath();
      context.arc(position.x, position.y, particle.radius, 0, Math.PI * 2);
      context.fillStyle = rgba(0.48);
      context.fill();

      context.beginPath();
      context.arc(position.x, position.y, particle.radius + 2.8, 0, Math.PI * 2);
      context.fillStyle = rgba(0.065);
      context.fill();
    });
  }

  function animate(timestamp) {
    if (document.hidden || reducedMotion.matches) {
      animationFrame = null;
      return;
    }

    if (timestamp - previousTimestamp >= 33) {
      drawFrame(true);
      previousTimestamp = timestamp;
    }
    animationFrame = requestAnimationFrame(animate);
  }

  function startAnimation() {
    if (animationFrame || document.hidden || reducedMotion.matches) return;
    previousTimestamp = performance.now();
    animationFrame = requestAnimationFrame(animate);
  }

  function stopAnimation() {
    if (!animationFrame) return;
    cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  window.addEventListener("resize", () => {
    if (resizeFrame) return;
    resizeFrame = requestAnimationFrame(() => {
      resizeCanvas();
      resizeFrame = null;
    });
  }, { passive: true });

  if (precisePointer.matches) {
    window.addEventListener("pointermove", (event) => {
      if (reducedMotion.matches) return;
      pointer.targetX = event.clientX;
      pointer.targetY = event.clientY;
      pointer.active = true;
    }, { passive: true });

    document.documentElement.addEventListener("pointerleave", () => {
      pointer.active = false;
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAnimation();
    else startAnimation();
  });

  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) {
      stopAnimation();
      pointer.active = false;
      drawFrame(false);
    } else {
      startAnimation();
    }
  });

  resizeCanvas();
  startAnimation();
}

function redrawChartsAfterResize() {
  if (!appState.data || appState.resizeFrame) return;
  appState.resizeFrame = requestAnimationFrame(() => {
    const diagnostics = appState.data.diagnosticos || {};
    drawLearningChart("bp-chart", diagnostics.bp?.linhas || [], "epoca");
    drawLearningChart("ag-chart", diagnostics.ag?.linhas || [], "geracao");
    appState.resizeFrame = null;
  });
}

byId("refresh-button").addEventListener("click", () => loadData({ manual: true }));
byId("start-monitor").addEventListener("click", startMonitoring);
byId("stop-monitor").addEventListener("click", stopMonitoring);
byId("save-session").addEventListener("click", saveSessionSummary);
byId("start-simulation").addEventListener("click", startSimulation);
byId("history-prev").addEventListener("click", () => {
  appState.history.pagina = Math.max(1, Number(appState.history.pagina || 1) - 1);
  loadHistoryPage({ preservePage: true });
});
byId("history-next").addEventListener("click", () => {
  appState.history.pagina = Math.min(
    Number(appState.history.paginas || 1),
    Number(appState.history.pagina || 1) + 1
  );
  loadHistoryPage({ preservePage: true });
});
document.querySelectorAll(".example-filter").forEach((button) => {
  button.addEventListener("click", () => selectExampleResult(button.dataset.result));
});
byId("diagnostic-example-select").addEventListener("change", (event) => {
  loadExample(event.target.value);
});
window.addEventListener("resize", redrawChartsAfterResize, { passive: true });
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) loadData();
});

setupNavigation();
setupNeuralBackground();
loadData();
setInterval(() => {
  if (!document.hidden) loadData();
}, POLL_INTERVAL_MS);
