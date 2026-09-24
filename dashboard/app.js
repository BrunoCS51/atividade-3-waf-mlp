"use strict";

const STORAGE_KEY = "waf-dashboard-manual-labels-v1";
const state = {
  page: 1,
  pages: 1,
  experiments: null,
  experimentSignature: "",
  chartResizeTimer: null,
  manualLabels: loadManualLabels(),
  lastManual: null,
  testSource: "manual",
  reservedItems: [],
  activeExperimentTabs: {},
  trainingJob: null,
  trainingPollTimer: null,
};

const $ = (id) => document.getElementById(id);
const pct = (value) => value == null ? "Não disponível" : `${(Number(value) * 100).toFixed(2)}%`;
const num = (value, digits = 4) => value == null ? "Não disponível" : Number(value).toFixed(digits);
const modelLabel = (value) => String(value || "").replace("experimento_", "Experimento ").replace(":", " · ").toUpperCase();

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[character]));
}

function sanitizedText(value, maximum = 500) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, maximum);
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "Não disponível");
  if (Number.isInteger(number)) return number.toLocaleString("pt-BR");
  if (number !== 0 && Math.abs(number) < 0.001) return number.toExponential(3);
  return number.toLocaleString("pt-BR", { maximumFractionDigits: 6 });
}

function formatValue(value) {
  if (value == null || value === "") return "Não disponível";
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (typeof value === "number") return formatNumber(value);
  if (Array.isArray(value)) return value.map(formatValue).join(" → ");
  if (typeof value === "object") {
    return Object.entries(value).map(([key, item]) => `${friendlyLabel(key)}: ${formatValue(item)}`).join(" · ");
  }
  return String(value).replaceAll("_", " ");
}

const FRIENDLY_LABELS = {
  accuracy: "Accuracy", precision: "Precision", recall: "Recall", f1: "F1",
  fpr: "FPR", fnr: "FNR", epochs: "Épocas", learning_rate: "Learning rate",
  sample_shuffle_each_epoch: "Embaralhar a cada época", backward: "Atualização BP",
  seed: "Seed", population: "População", generations: "Gerações",
  selection_type: "Tipo de seleção", tournament_size: "Tamanho do torneio",
  crossover_type: "Tipo de crossover", crossover_rate: "Taxa de crossover",
  sbx_eta: "Eta SBX", mutation_type: "Tipo de mutação",
  mutation_rate: "Taxa de mutação", mutation_sigma: "Sigma da mutação",
  mutation_eta: "Eta da mutação", weight_min: "Limite inferior dos genes",
  weight_max: "Limite superior dos genes", elitism: "Elitismo",
  viability_note: "Observação de viabilidade", architecture: "Arquitetura",
  parameter_count: "Parâmetros da rede", epoch: "Época final",
  generation: "Geração final", online_mse_mean: "MSE online médio",
  train_mse_after_epoch: "MSE treino final", validation_mse: "MSE validação final",
  train_validation_gap: "Gap treino × validação", wall_seconds: "Tempo de parede",
  cpu_seconds: "Tempo de CPU", hidden_saturation_percentage: "Saturação da camada oculta",
  generation_best_train_mse: "Melhor fitness da geração",
  global_best_train_mse: "Melhor fitness global", mean_train_mse: "Fitness médio",
  population_diversity: "Diversidade populacional", gene_mean: "Média dos genes",
  gene_std: "Desvio dos genes", near_weight_boundaries_percentage: "Genes próximos aos limites",
  fitness_evaluations: "Avaliações de fitness", genes: "Número de genes",
};

const PARAMETER_NAMES = {
  selection_type: { 1: "Torneio", 2: "Roleta" },
  crossover_type: { 1: "Um ponto", 2: "SBX" },
  mutation_type: { 1: "Uniforme", 2: "Gaussiana", 3: "Polinomial" },
};

function friendlyLabel(key) {
  if (FRIENDLY_LABELS[key]) return FRIENDLY_LABELS[key];
  const layer = key.match(/^layer_(\d+)_(.+)$/);
  if (layer) return `Camada ${layer[1]} · ${friendlyLabel(layer[2])}`;
  const derived = key.replaceAll("_", " ");
  return derived.charAt(0).toUpperCase() + derived.slice(1);
}

function namedParameterValue(key, value) {
  const name = PARAMETER_NAMES[key]?.[value];
  return name ? `${name} (código ${value})` : value;
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function loadManualLabels() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch (error) {
    return {};
  }
}

function persistManualLabels() {
  try {
    const recent = Object.fromEntries(Object.entries(state.manualLabels).slice(-100));
    state.manualLabels = recent;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recent));
  } catch (error) {
    // O dashboard continua funcional quando o armazenamento local está indisponível.
  }
}

function decisionBadge(value) {
  const blocked = value === "BLOQUEIA";
  return `<span class="decision ${blocked ? "block" : "allow"}">${blocked ? "BLOQUEIA" : "LIBERA"}</span>`;
}

function correctnessBadge(decision, manual) {
  if (!manual) return "";
  const correct = decision === manual.expectedDecision;
  return `<span class="correctness ${correct ? "correct" : "incorrect"}">${correct ? "Correto" : "Incorreto"}</span>`;
}

function metricCards(metrics, threshold) {
  const entries = [
    ["Accuracy", pct(metrics.accuracy)], ["Precision", pct(metrics.precision)],
    ["Recall", pct(metrics.recall)], ["F1", pct(metrics.f1)],
    ["FPR", pct(metrics.fpr)], ["FNR", pct(metrics.fnr)],
    ["Threshold", formatNumber(threshold)],
  ];
  return entries.map(([name, value]) => `<div class="metric-card"><small>${name}</small><strong>${value}</strong></div>`).join("");
}

function confusionMatrix(metrics) {
  const cell = (key, tone, description) => `<div class="confusion-cell ${tone}"><small>${key.toUpperCase()}</small><strong>${formatNumber(metrics[key])}</strong><span>${description}</span></div>`;
  return `<div class="confusion-matrix" aria-label="Matriz de confusão">
    <div class="matrix-corner"><span>Real ↓</span><span>Previsto →</span></div>
    <div class="matrix-axis">NORMAL</div><div class="matrix-axis">ATAQUE</div>
    <div class="matrix-axis row-axis">NORMAL</div>${cell("tn", "positive", "Normal liberado corretamente")}${cell("fp", "negative", "Normal bloqueado incorretamente")}
    <div class="matrix-axis row-axis">ATAQUE</div>${cell("fn", "negative", "Ataque liberado incorretamente")}${cell("tp", "positive", "Ataque bloqueado corretamente")}
  </div>`;
}

function infoCards(entries, className = "info-card-grid") {
  const available = entries.filter(([, value]) => value !== undefined);
  return `<div class="${className}">${available.map(([name, value]) => {
    const formatted = formatValue(value);
    return `<div class="info-card"><small>${escapeHTML(name)}</small><strong title="${escapeHTML(formatted)}">${escapeHTML(formatted)}</strong></div>`;
  }).join("")}</div>`;
}

function parameterEntries(model) {
  const entries = [
    [friendlyLabel("architecture"), model.architecture],
    [friendlyLabel("parameter_count"), model.parameter_count],
  ];
  Object.entries(model.parameters || {}).forEach(([key, value]) => entries.push([friendlyLabel(key), namedParameterValue(key, value)]));
  if (!("seed" in (model.parameters || {})) && model.seed != null) entries.push([friendlyLabel("seed"), model.seed]);
  return entries;
}

function diagnosticEntries(model, algorithm) {
  const entries = [];
  const series = model.diagnostic?.series || [];
  if (algorithm === "ag" && series.length) {
    const first = series[0];
    if (first.global_best_train_mse != null) entries.push(["Melhor fitness inicial", first.global_best_train_mse]);
    if (first.population_diversity != null) entries.push(["Diversidade inicial", first.population_diversity]);
  }
  Object.entries(model.diagnostic?.final || {}).forEach(([key, value]) => entries.push([friendlyLabel(key), value]));
  Object.entries(model.training || {}).forEach(([key, value]) => {
    if (!entries.some(([name]) => name === friendlyLabel(key))) entries.push([friendlyLabel(key), value]);
  });
  return entries;
}

function curveSummary(model, algorithm) {
  const final = model.diagnostic?.final || {};
  const keys = algorithm === "bp"
    ? ["epoch", "train_mse_after_epoch", "validation_mse", "train_validation_gap"]
    : ["generation", "global_best_train_mse", "mean_train_mse", "validation_mse", "population_diversity"];
  return infoCards(keys.filter((key) => final[key] != null).map((key) => [friendlyLabel(key), final[key]]), "curve-summary");
}

function diagnosticAnalysisPanel(experiment, algorithm) {
  const analysis = window.DiagnosticAnalysis.evaluateModel(experiment, algorithm);
  const criteria = analysis.checks.map((check) => `<div class="analysis-check ${check.passed ? "passed" : "failed"}">
    <span>${escapeHTML(check.label)}</span><strong>${pct(check.value)}</strong><small>${check.operator === ">=" ? "Meta mínima" : "Meta máxima"}: ${pct(check.target)}</small><i>${check.passed ? "Atende" : "Investigar"}</i>
  </div>`).join("");
  const recommendations = analysis.recommendations.map((item) => `<article class="recommendation-card ${item.level}">
    <div class="recommendation-head"><span>${escapeHTML(item.area)}</span><i>${item.level === "keep" ? "Manter" : item.level === "priority" ? "Prioridade" : "Próximo teste"}</i></div>
    <h5>${escapeHTML(item.title)}</h5>
    <p>${escapeHTML(item.reason)}</p>
    <div><small>Ação sugerida</small><strong>${escapeHTML(item.action)}</strong></div>
  </article>`).join("");
  return `<section class="analysis-section">
    <div class="subsection-heading"><div><span>Análise de arquitetura e treinamento</span><small>Interpretação orientativa dos indicadores já registrados</small></div><span class="analysis-status ${analysis.status}">${analysis.status === "aceitavel" ? "Referência atendida" : "Requer investigação"} · ${analysis.passedCount}/${analysis.totalChecks}</span></div>
    <div class="analysis-method-note"><strong>Base metodológica</strong><span>${escapeHTML(analysis.basis)}</span><small>Metas acadêmicas referenciais e configuráveis; não são limites universais.</small></div>
    <div class="analysis-check-grid">${criteria}</div>
    <div class="recommendation-grid">${recommendations}</div>
    <p class="analysis-disclaimer">${escapeHTML(analysis.disclaimer)}</p>
  </section>`;
}

function signedDelta(value, previous, lowerIsBetter = false, percentage = false) {
  const difference = Number(value) - Number(previous);
  if (!Number.isFinite(difference)) return { text: "—", tone: "neutral" };
  const improved = lowerIsBetter ? difference < 0 : difference > 0;
  const worsened = lowerIsBetter ? difference > 0 : difference < 0;
  const formatted = percentage
    ? `${difference >= 0 ? "+" : ""}${(difference * 100).toFixed(2)} p.p.`
    : `${difference >= 0 ? "+" : ""}${formatNumber(difference)}`;
  return { text: difference === 0 ? "sem alteração" : formatted, tone: improved ? "better" : worsened ? "worse" : "neutral" };
}

function historyVerdict(event) {
  const before = event.previous.metrics.validacao || {};
  const after = event.result.metrics.validacao || {};
  const costBefore = Number(before.security_cost);
  const costAfter = Number(after.security_cost);
  if (Number.isFinite(costBefore) && Number.isFinite(costAfter) && costAfter !== costBefore) {
    return costAfter < costBefore
      ? { tone: "better", label: "Melhorou na validação", detail: `Custo de segurança ${formatNumber(costBefore)} → ${formatNumber(costAfter)}` }
      : { tone: "worse", label: "Piorou na validação", detail: `Custo de segurança ${formatNumber(costBefore)} → ${formatNumber(costAfter)}` };
  }
  const f1Before = Number(before.f1);
  const f1After = Number(after.f1);
  if (Number.isFinite(f1Before) && Number.isFinite(f1After) && f1After !== f1Before) {
    return f1After > f1Before
      ? { tone: "better", label: "Melhorou na validação", detail: `F1 ${pct(f1Before)} → ${pct(f1After)}` }
      : { tone: "worse", label: "Piorou na validação", detail: `F1 ${pct(f1Before)} → ${pct(f1After)}` };
  }
  return { tone: "neutral", label: "Resultado equivalente", detail: "Sem variação no critério principal." };
}

function changedTrainingParameters(event) {
  const before = event.previous.parameters || {};
  const after = event.result.parameters || {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  const changes = keys.filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]));
  const architectureChanged = JSON.stringify(event.previous.architecture) !== JSON.stringify(event.result.architecture);
  const items = [];
  if (architectureChanged) items.push(`<span><small>Arquitetura</small><strong>${event.previous.architecture.join(" → ")} → ${event.result.architecture.join(" → ")}</strong></span>`);
  changes.forEach((key) => items.push(`<span><small>${escapeHTML(friendlyLabel(key))}</small><strong>${escapeHTML(formatValue(namedParameterValue(key, before[key])))} → ${escapeHTML(formatValue(namedParameterValue(key, after[key])))}</strong></span>`));
  return items.length ? items.join("") : `<span><small>Configuração</small><strong>Sem alteração registrada</strong></span>`;
}

function historyMetric(label, key, event, percentage = false, lowerIsBetter = false) {
  const before = event.previous.metrics.teste?.[key];
  const after = event.result.metrics.teste?.[key];
  const delta = signedDelta(after, before, lowerIsBetter, percentage);
  const value = percentage ? `${pct(before)} → ${pct(after)}` : `${formatNumber(before)} → ${formatNumber(after)}`;
  return `<div><small>${label}</small><strong>${value}</strong><span class="history-delta ${delta.tone}">${delta.text}</span></div>`;
}

function retrainingHistoryPanel(model) {
  const history = model.retraining_history || [];
  if (!history.length) return `<section class="retraining-history"><div class="subsection-heading"><div><span>Histórico de retreinamentos</span><small>Comparação entre versões deste modelo</small></div><span class="history-count">0 retreinos</span></div><div class="history-empty">Nenhum retreinamento registrado. A rodada oficial continua sendo a única versão deste modelo.</div></section>`;
  return `<section class="retraining-history">
    <div class="subsection-heading"><div><span>Histórico de retreinamentos</span><small>Validação orienta a avaliação; teste é mostrado apenas como observação final</small></div><span class="history-count">${history.length} ${history.length === 1 ? "retreino" : "retreinos"}</span></div>
    <div class="history-list">${history.map((event) => {
      const verdict = historyVerdict(event);
      const date = event.completed_at ? new Date(event.completed_at).toLocaleString("pt-BR") : "Data não disponível";
      return `<article class="history-entry ${verdict.tone}">
        <header><div><span>Retreino #${event.sequence}</span><time>${escapeHTML(date)}</time></div><strong>${verdict.label}<small>${verdict.detail}</small></strong></header>
        <div class="history-parameters">${changedTrainingParameters(event)}</div>
        <div class="history-metrics">
          ${historyMetric("FN · ataques liberados", "fn", event, false, true)}
          ${historyMetric("FP · normais bloqueadas", "fp", event, false, true)}
          ${historyMetric("Recall", "recall", event, true)}
          ${historyMetric("F1", "f1", event, true)}
          ${historyMetric("Accuracy", "accuracy", event, true)}
          ${historyMetric("Threshold", "threshold", event)}
        </div>
      </article>`;
    }).join("")}</div>
  </section>`;
}

function inputAnalysisPanel(experiment) {
  const analysis = window.DiagnosticAnalysis.evaluateInputs(experiment);
  const methods = Object.entries(analysis.normalizationMethods).map(([method, count]) => `<span><strong>${formatNumber(count)}</strong>${escapeHTML(friendlyLabel(method))}</span>`).join("");
  return `<section class="input-analysis">
    <div class="subsection-heading"><div><span>Análise das entradas</span><small>O que os artefatos permitem concluir sobre as ${formatNumber(analysis.featureCount)} features</small></div><span class="analysis-status insufficient">Evidência insuficiente para remover</span></div>
    <div class="input-analysis-summary"><div><small>Features atuais</small><strong>${formatNumber(analysis.featureCount)}</strong></div><p>${escapeHTML(analysis.conclusion)}</p></div>
    <div class="normalization-methods">${methods}</div>
    <div class="input-next-steps"><strong>Próxima investigação recomendada</strong><ol>${analysis.nextSteps.map((step) => `<li>${escapeHTML(step)}</li>`).join("")}</ol></div>
  </section>`;
}

function trainingField(label, name, value, attributes = "") {
  return `<label><span>${escapeHTML(label)}</span><input name="${escapeHTML(name)}" value="${escapeHTML(value)}" ${attributes} required></label>`;
}

function trainingSelect(label, name, value, choices) {
  return `<label><span>${escapeHTML(label)}</span><select name="${escapeHTML(name)}">${choices.map(([optionValue, optionLabel]) => `<option value="${optionValue}" ${Number(value) === Number(optionValue) ? "selected" : ""}>${escapeHTML(optionLabel)}</option>`).join("")}</select></label>`;
}

function architectureEditor(model) {
  const architecture = model.architecture;
  const hidden = architecture.slice(1, -1).join(", ");
  return `<div class="architecture-editor field-wide"><span class="fixed-layer"><small>Entradas fixas</small><strong>${architecture[0]}</strong></span><i>→</i><label><span>Neurônios das camadas ocultas</span><input name="hidden_layers" value="${escapeHTML(hidden)}" placeholder="Ex.: 77 ou 77, 39" required><small>Separe até três camadas por vírgula.</small></label><i>→</i><span class="fixed-layer"><small>Saída fixa</small><strong>1</strong></span></div>`;
}

function trainingAdvice(experiment, algorithm) {
  const analysis = window.DiagnosticAnalysis.evaluateModel(experiment, algorithm);
  return `<div class="training-advice"><span>Sugestões da análise atual</span><ul>${analysis.recommendations.slice(0, 3).map((item) => `<li><strong>${escapeHTML(item.area)}:</strong> ${escapeHTML(item.action)}</li>`).join("")}</ul><small>Altere um fator por rodada sempre que possível.</small></div>`;
}

function trainingForm(experimentId, experiment, algorithm) {
  const model = experiment.models[algorithm];
  const parameters = model.parameters || {};
  const title = algorithm === "bp" ? "Backpropagation" : "Algoritmo Genético";
  const fields = algorithm === "bp" ? `
    ${trainingField("Épocas", "epochs", parameters.epochs, 'type="number" min="1" max="2000" step="1"')}
    ${trainingField("Learning rate", "learning_rate", parameters.learning_rate, 'type="number" min="0.000001" max="1" step="0.000001"')}
  ` : `
    ${trainingField("População", "population", parameters.population, 'type="number" min="4" max="500" step="2"')}
    ${trainingField("Gerações", "generations", parameters.generations, 'type="number" min="1" max="1000" step="1"')}
    ${trainingSelect("Seleção", "selection_type", parameters.selection_type, [[1, "Torneio"], [2, "Roleta"]])}
    ${trainingField("Tamanho do torneio", "tournament_size", parameters.tournament_size, 'type="number" min="2" max="500" step="1"')}
    ${trainingSelect("Crossover", "crossover_type", parameters.crossover_type, [[1, "Um ponto"], [2, "SBX — Simulated Binary Crossover"]])}
    ${trainingField("Taxa de crossover", "crossover_rate", parameters.crossover_rate, 'type="number" min="0" max="1" step="0.01"')}
    ${trainingField("Eta SBX", "sbx_eta", parameters.sbx_eta, 'type="number" min="0.01" max="100" step="0.01"')}
    ${trainingSelect("Mutação", "mutation_type", parameters.mutation_type, [[1, "Uniforme"], [2, "Gaussiana"], [3, "Polinomial"]])}
    ${trainingField("Taxa de mutação", "mutation_rate", parameters.mutation_rate, 'type="number" min="0" max="1" step="0.001"')}
    ${trainingField("Sigma da mutação", "mutation_sigma", parameters.mutation_sigma, 'type="number" min="0" max="10" step="0.01"')}
    ${trainingField("Eta da mutação", "mutation_eta", parameters.mutation_eta, 'type="number" min="0.01" max="200" step="0.01"')}
    ${trainingField("Gene mínimo", "weight_min", parameters.weight_min, 'type="number" min="-100" max="100" step="0.1"')}
    ${trainingField("Gene máximo", "weight_max", parameters.weight_max, 'type="number" min="-100" max="100" step="0.1"')}
  `;
  return `<form class="training-form" data-training-form data-experiment-id="${experimentId}" data-algorithm="${algorithm}">
    <div class="training-form-head"><div><span class="panel-kicker">${algorithm.toUpperCase()}</span><h5>${title}</h5><p>Configuração atual carregada dos artefatos.</p></div><span>${formatNumber(model.parameter_count)} parâmetros atuais</span></div>
    ${trainingAdvice(experiment, algorithm)}
    <div class="training-field-grid">${architectureEditor(model)}${fields}</div>
    <div class="training-immutable"><strong>Preservado automaticamente</strong><span>dataset, split, normalização, seed, cálculo de threshold e conjunto reservado externo.</span></div>
    <button class="button-primary training-submit" type="submit">Treinar ${algorithm.toUpperCase()}</button>
  </form>`;
}

function trainingConfigurationPanel(experimentId, experiment) {
  return `<section class="experiment-panel training-panel" data-panel="training" hidden>
    <div class="overview-title"><div><span class="panel-kicker">Configuração de treino</span><h4>Retreinamento controlado</h4></div><span>Um modelo por vez · backup automático</span></div>
    <div class="training-warning"><strong>Atenção</strong><p>Ao concluir com sucesso, o modelo selecionado passa a substituir sua versão operacional/shadow. O teste é calculado somente para avaliação final; decisões de ajuste devem continuar baseadas na validação.</p></div>
    <div class="training-form-grid">${trainingForm(experimentId, experiment, "bp")}${trainingForm(experimentId, experiment, "ag")}</div>
  </section>`;
}

function chartLegend(algorithm) {
  const labels = algorithm === "bp"
    ? [["#1769e0", "MSE treino"], ["#e08a17", "MSE validação"]]
    : [["#1769e0", "Melhor fitness"], ["#6f55bd", "Fitness médio"], ["#e08a17", "Fitness validação"]];
  return labels.map(([color, text]) => `<span><i style="--legend-color:${color}"></i>${text}</span>`).join("");
}

function modelPanel(experimentId, algorithm, experiment) {
  const model = experiment.models[algorithm];
  const testSampleCount = experiment.split.teste.total;
  const metrics = model.metrics.teste;
  const title = algorithm === "bp" ? "Backpropagation" : "Algoritmo Genético";
  const curveTitle = algorithm === "bp" ? "Evolução do erro (MSE)" : "Evolução do fitness por geração";
  return `<section class="experiment-panel model-panel" data-panel="${algorithm}" hidden>
    <div class="model-heading"><div><span class="panel-kicker">${algorithm.toUpperCase()}</span><h4>${title}</h4><p>Arquitetura ${model.architecture.join(" → ")} · desenvolvimento e avaliação oficial.</p></div><span class="threshold">threshold ${formatNumber(model.threshold)} (${escapeHTML(model.threshold_comparison)})</span></div>
    <section class="result-section"><div class="subsection-heading"><div><span>Resultado no conjunto de teste</span><small>Métricas finais, independentes das curvas de desenvolvimento</small></div><div class="test-meta"><span>${formatNumber(testSampleCount)} amostras</span><span>${formatNumber(model.training?.wall_seconds)} s de treinamento</span></div></div>
      <div class="metric-grid">${metricCards(metrics, model.threshold)}</div>
      ${confusionMatrix(metrics)}
    </section>
    <section class="development-section"><div class="subsection-heading"><div><span>${curveTitle}</span><small>${algorithm === "bp" ? "Épocas de treino e validação" : "Fitness real registrado no diagnóstico do AG"}</small></div><div class="chart-legend">${chartLegend(algorithm)}</div></div>
      <div class="chart-wrap"><canvas class="chart" id="chart-${experimentId}-${algorithm}" aria-label="${curveTitle}"></canvas></div>
      ${algorithm === "ag" ? `<div class="secondary-curve"><div class="subsection-heading"><div><span>Diversidade populacional</span><small>Evolução real registrada a cada geração</small></div><div class="chart-legend"><span><i style="--legend-color:#0f9f7f"></i>Diversidade</span></div></div><div class="chart-wrap compact"><canvas class="chart" id="chart-${experimentId}-ag-diversity" aria-label="Evolução da diversidade populacional"></canvas></div></div>` : ""}
      ${curveSummary(model, algorithm)}
    </section>
    <section class="card-section"><div class="subsection-heading"><div><span>Parâmetros</span><small>Configuração utilizada no treinamento</small></div></div>${infoCards(parameterEntries(model))}</section>
    <section class="card-section"><div class="subsection-heading"><div><span>Diagnóstico</span><small>Indicadores observados durante e após o treinamento</small></div></div>${infoCards(diagnosticEntries(model, algorithm))}</section>
    ${diagnosticAnalysisPanel(experiment, algorithm)}
    ${retrainingHistoryPanel(model)}
  </section>`;
}

function comparisonTable(experiment) {
  const bp = experiment.models.bp;
  const ag = experiment.models.ag;
  const rows = [
    ["Accuracy", pct(bp.metrics.teste.accuracy), pct(ag.metrics.teste.accuracy)],
    ["Recall", pct(bp.metrics.teste.recall), pct(ag.metrics.teste.recall)],
    ["FPR", pct(bp.metrics.teste.fpr), pct(ag.metrics.teste.fpr)],
    ["F1", pct(bp.metrics.teste.f1), pct(ag.metrics.teste.f1)],
    ["Tempo", `${formatNumber(bp.training.wall_seconds)} s`, `${formatNumber(ag.training.wall_seconds)} s`],
  ];
  return `<div class="comparison-table"><div class="comparison-row comparison-head"><span>Métrica</span><strong>BP</strong><strong>AG</strong></div>${rows.map(([name, bpValue, agValue]) => `<div class="comparison-row"><span>${name}</span><strong>${bpValue}</strong><strong>${agValue}</strong></div>`).join("")}</div>`;
}

function architectureSummary(experiment) {
  const bp = experiment.models.bp.architecture.join(" → ");
  const ag = experiment.models.ag.architecture.join(" → ");
  return { bp, ag, shared: bp === ag, label: bp === ag ? bp : `BP ${bp} · AG ${ag}` };
}

function experimentOverview(id, experiment) {
  const datasetName = experiment.dataset.path.split(/[\\/]/).pop();
  const split = `${experiment.split.treino.total.toLocaleString("pt-BR")} / ${experiment.split.validacao.total.toLocaleString("pt-BR")} / ${experiment.split.teste.total.toLocaleString("pt-BR")}`;
  const architectures = architectureSummary(experiment);
  const cards = [
    ["Dataset", datasetName], ["Amostras", experiment.dataset.samples],
    ["Features", experiment.feature_count], ["Split T / V / T", split],
    [architectures.shared ? "Arquitetura" : "Arquiteturas", architectures.label],
  ];
  return `<section class="experiment-panel overview-panel active" data-panel="overview">
    <div class="overview-title"><div><span class="panel-kicker">Visão geral</span><h4>Pipeline e resultados comparáveis</h4></div><span>${architectures.shared ? "BP e AG usam a mesma arquitetura" : "Arquiteturas independentes por modelo"}</span></div>
    ${infoCards(cards, "overview-card-grid")}
    <div class="flow-strip" aria-label="Fluxo do experimento"><span>Requisição</span><i>→</i><span>Extractor</span><i>→</i><span>${experiment.feature_count} features</span><i>→</i><span>Normalização</span><i>→</i><span>MLP ${architectures.label}</span><i>→</i><span>Decisão</span></div>
    <div class="overview-comparison"><div class="subsection-heading"><div><span>Comparação BP × AG</span><small>${architectures.shared ? "Mesma arquitetura; " : "Arquiteturas independentes; "}nenhuma seleção automática de vencedor</small></div></div>${comparisonTable(experiment)}</div>
    ${inputAnalysisPanel(experiment)}
  </section>`;
}

function renderExperiments(experiments) {
  $("experiment-grid").innerHTML = Object.entries(experiments).map(([id, experiment]) => {
    const architectures = architectureSummary(experiment);
    const architecture = architectures.shared
      ? escapeHTML(architectures.label)
      : `<span><small>BP</small>${escapeHTML(architectures.bp)}</span><span><small>AG</small>${escapeHTML(architectures.ag)}</span>`;
    return `<article class="experiment-card" data-experiment="${id}">
      <header class="experiment-header"><h3>${escapeHTML(experiment.title)}</h3><div class="architecture ${architectures.shared ? "" : "multi-model"}">${architecture}</div>
        <div class="experiment-meta"><span>${experiment.feature_count} features</span><span>${experiment.dataset.samples.toLocaleString("pt-BR")} amostras</span><span>Split ${experiment.split.treino.total}/${experiment.split.validacao.total}/${experiment.split.teste.total}</span></div>
        <div class="dataset-line"><span>Dataset</span><code title="${escapeHTML(experiment.dataset.path)}">${escapeHTML(experiment.dataset.path)}</code></div>
      </header>
      <div class="experiment-tabs" role="tablist" aria-label="Seções de ${escapeHTML(experiment.title)}">
        <button class="experiment-tab active" type="button" data-tab="overview" role="tab" aria-selected="true">Visão geral</button>
        <button class="experiment-tab" type="button" data-tab="bp" role="tab" aria-selected="false">Backpropagation</button>
        <button class="experiment-tab" type="button" data-tab="ag" role="tab" aria-selected="false">Algoritmo Genético</button>
        <button class="experiment-tab" type="button" data-tab="training" role="tab" aria-selected="false">Configurar treino</button>
      </div>
      ${experimentOverview(id, experiment)}${modelPanel(id, "bp", experiment)}${modelPanel(id, "ag", experiment)}${trainingConfigurationPanel(id, experiment)}
    </article>`;
  }).join("");

  document.querySelectorAll(".experiment-tab").forEach((button) => button.addEventListener("click", () => activateExperimentTab(button)));
  document.querySelectorAll("[data-training-form]").forEach((form) => form.addEventListener("submit", submitTraining));
  const requestedTab = new URLSearchParams(window.location.search).get("tab");
  document.querySelectorAll(".experiment-card").forEach((card) => {
    const tab = state.activeExperimentTabs[card.dataset.experiment] || (["bp", "ag", "training"].includes(requestedTab) ? requestedTab : "overview");
    const button = card.querySelector(`.experiment-tab[data-tab="${tab}"]`);
    if (button) activateExperimentTab(button);
  });
}

function activateExperimentTab(button) {
  const card = button.closest(".experiment-card");
  const tab = button.dataset.tab;
  state.activeExperimentTabs[card.dataset.experiment] = tab;
  card.querySelectorAll(".experiment-tab").forEach((item) => {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  card.querySelectorAll(".experiment-panel").forEach((panel) => {
    const active = panel.dataset.panel === tab;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  if (tab === "bp" || tab === "ag") {
    const id = card.dataset.experiment;
    requestAnimationFrame(() => drawChart(
      $(`chart-${id}-${tab}`), state.experiments[id].models[tab].diagnostic.series, tab
    ));
    if (tab === "ag") {
      requestAnimationFrame(() => drawChart(
        $(`chart-${id}-ag-diversity`), state.experiments[id].models.ag.diagnostic.series, "diversity"
      ));
    }
  }
}

function durationText(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "Calculando…";
  if (value < 60) return `${Math.max(0, Math.round(value))} s`;
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return `${minutes} min ${remainder} s`;
}

function trainingPayload(form) {
  const data = new FormData(form);
  const experimentId = form.dataset.experimentId;
  const algorithm = form.dataset.algorithm;
  const experiment = state.experiments[experimentId];
  const hidden = String(data.get("hidden_layers") || "").split(/[,;x×→\s]+/).filter(Boolean).map(Number);
  if (!hidden.length || hidden.some((value) => !Number.isInteger(value) || value <= 0)) {
    throw new Error("Informe as camadas ocultas com números inteiros separados por vírgula.");
  }
  const architecture = [experiment.feature_count, ...hidden, 1];
  const number = (name) => Number(data.get(name));
  const parameters = algorithm === "bp" ? {
    epochs: number("epochs"),
    learning_rate: number("learning_rate"),
  } : {
    population: number("population"),
    generations: number("generations"),
    selection_type: number("selection_type"),
    tournament_size: number("tournament_size"),
    crossover_type: number("crossover_type"),
    crossover_rate: number("crossover_rate"),
    sbx_eta: number("sbx_eta"),
    mutation_type: number("mutation_type"),
    mutation_rate: number("mutation_rate"),
    mutation_sigma: number("mutation_sigma"),
    mutation_eta: number("mutation_eta"),
    weight_min: number("weight_min"),
    weight_max: number("weight_max"),
  };
  return { experiment_id: experimentId, algorithm, architecture, parameters };
}

function openTrainingDialog(job = null) {
  const dialog = $("training-dialog");
  $("training-dialog-close").disabled = true;
  $("training-result").hidden = true;
  $("training-progress-bar").style.width = `${job?.percent || 0}%`;
  $("training-progress-percent").textContent = `${Math.round(job?.percent || 0)}%`;
  $("training-progress-step").textContent = job ? `${job.current} de ${job.total}` : "Preparando…";
  $("training-progress-message").textContent = job?.message || "Validando configuração e preparando treinamento…";
  $("training-elapsed").textContent = durationText(job?.elapsed_seconds || 0);
  $("training-remaining").textContent = durationText(job?.remaining_seconds ?? job?.estimated_seconds);
  if (!dialog.open) dialog.showModal();
}

function renderTrainingJob(job) {
  state.trainingJob = job;
  const finished = ["completed", "failed"].includes(job.status);
  const percent = job.status === "completed" ? 100 : Number(job.percent || 0);
  $("training-dialog-title").textContent = `${job.experiment_id.replace("experimento_", "Experimento ")} · ${job.algorithm.toUpperCase()}`;
  $("training-progress-bar").style.width = `${Math.min(100, percent)}%`;
  $("training-progress-percent").textContent = `${Math.round(percent)}%`;
  $("training-progress-step").textContent = `${job.current} de ${job.total}`;
  $("training-progress-message").textContent = job.message;
  $("training-elapsed").textContent = durationText(job.elapsed_seconds);
  $("training-remaining").textContent = job.status === "completed" ? "Concluído" : durationText(job.remaining_seconds ?? job.estimated_seconds);
  $("training-dialog").classList.toggle("failed", job.status === "failed");
  if (finished) {
    const result = $("training-result");
    result.hidden = false;
    result.className = `training-result ${job.status}`;
    result.innerHTML = job.status === "completed"
      ? `<strong>Treinamento concluído</strong><span>Threshold ${formatNumber(job.result.threshold)} · F1 validação ${pct(job.result.validation.f1)} · F1 teste ${pct(job.result.test.f1)}</span><small>A página foi atualizada com os novos artefatos. A versão anterior permanece no histórico de treinamentos.</small>`
      : `<strong>Treinamento não concluído</strong><span>${escapeHTML(job.error || "Erro não informado")}</span><small>Os artefatos anteriores foram preservados.</small>`;
    $("training-dialog-close").disabled = false;
  }
}

async function pollTraining(jobId) {
  clearTimeout(state.trainingPollTimer);
  try {
    const job = await getJSON(`api/training/status?job_id=${encodeURIComponent(jobId)}&t=${Date.now()}`);
    renderTrainingJob(job);
    if (["queued", "running"].includes(job.status)) {
      state.trainingPollTimer = setTimeout(() => pollTraining(jobId), 900);
    } else if (job.status === "completed") {
      await loadData();
    }
  } catch (error) {
    $("training-progress-message").textContent = `Falha ao consultar o progresso: ${error.message}`;
    state.trainingPollTimer = setTimeout(() => pollTraining(jobId), 2000);
  }
}

async function submitTraining(event) {
  event.preventDefault();
  let payload;
  try {
    payload = trainingPayload(event.currentTarget);
  } catch (error) {
    window.alert(error.message);
    return;
  }
  const currentArchitecture = state.experiments[payload.experiment_id].models[payload.algorithm].architecture.join(" → ");
  const nextArchitecture = payload.architecture.join(" → ");
  const confirmed = window.confirm(`Iniciar o retreinamento de ${payload.experiment_id.replace("experimento_", "Experimento ")} ${payload.algorithm.toUpperCase()}?\n\nArquitetura atual: ${currentArchitecture}\nNova arquitetura: ${nextArchitecture}\n\nA versão atual será arquivada e só será substituída após o treinamento terminar com sucesso.`);
  if (!confirmed) return;
  openTrainingDialog();
  try {
    const job = await postJSON("api/training/start", payload);
    renderTrainingJob(job);
    pollTraining(job.job_id);
  } catch (error) {
    renderTrainingJob({
      experiment_id: payload.experiment_id, algorithm: payload.algorithm,
      status: "failed", current: 0, total: 0, percent: 0,
      elapsed_seconds: 0, message: "Não foi possível iniciar o treinamento.",
      error: error.message,
    });
  }
}

async function resumeActiveTraining() {
  try {
    const job = await getJSON(`api/training/active?t=${Date.now()}`);
    if (job?.job_id && ["queued", "running"].includes(job.status)) {
      openTrainingDialog(job);
      renderTrainingJob(job);
      pollTraining(job.job_id);
    }
  } catch (error) {
    // O monitor continua disponível mesmo quando o serviço de treino está offline.
  }
}

function drawChart(canvas, series, algorithm) {
  if (!canvas || !series?.length || canvas.closest("[hidden]")) return;
  const definitions = algorithm === "bp"
    ? [["train_mse_after_epoch", "#1769e0"], ["validation_mse", "#e08a17"]]
    : algorithm === "diversity"
      ? [["population_diversity", "#0f9f7f"]]
      : [["global_best_train_mse", "#1769e0"], ["mean_train_mse", "#6f55bd"], ["validation_mse", "#e08a17"]];
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(canvas.clientWidth, 300);
  const height = Math.max(canvas.clientHeight, 220);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const values = series.flatMap((row) => definitions.map(([key]) => Number(row[key]))).filter(Number.isFinite);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (maximum === minimum) { maximum += 0.5; minimum -= 0.5; }
  const padding = { left: 52, right: 16, top: 16, bottom: 36 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const range = maximum - minimum;
  ctx.clearRect(0, 0, width, height);
  ctx.font = "10px system-ui";
  ctx.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (plotHeight * index / 4);
    const value = maximum - range * index / 4;
    ctx.strokeStyle = "#e3eaf2";
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillStyle = "#748197"; ctx.textAlign = "right"; ctx.fillText(value.toFixed(3), padding.left - 7, y + 3);
  }
  definitions.forEach(([key, color]) => {
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2;
    series.forEach((row, index) => {
      const value = Number(row[key]);
      if (!Number.isFinite(value)) return;
      const x = padding.left + index * plotWidth / Math.max(series.length - 1, 1);
      const y = padding.top + (maximum - value) * plotHeight / range;
      index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  });
  ctx.fillStyle = "#748197"; ctx.textAlign = "center";
  ctx.fillText("1", padding.left, height - 17);
  ctx.fillText(String(series.length), width - padding.right, height - 17);
  ctx.fillText(algorithm === "bp" ? "Épocas" : "Gerações", padding.left + plotWidth / 2, height - 6);
  const verticalLabel = algorithm === "bp" ? "MSE" : algorithm === "diversity" ? "Diversidade" : "Fitness (MSE)";
  ctx.save(); ctx.translate(12, padding.top + plotHeight / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(verticalLabel, 0, 0); ctx.restore();
}

async function loadData() {
  try {
    const data = await getJSON(`api/data?t=${Date.now()}`);
    $("waf-status").textContent = data.waf.online ? "Online" : "Offline";
    $("status-dot").classList.toggle("online", data.waf.online);
    $("primary-model").textContent = modelLabel(data.waf.primary_model);
    $("sync").textContent = `Atualizado ${new Date(data.generated_at).toLocaleTimeString("pt-BR")}`;
    const signature = JSON.stringify(data.experiments);
    if (signature !== state.experimentSignature) {
      state.experiments = data.experiments;
      state.experimentSignature = signature;
      renderExperiments(state.experiments);
    }
  } catch (error) {
    $("sync").textContent = `Erro: ${error.message}`;
  }
}

function expectedCell(manual) {
  if (!manual) return `<span class="not-informed">Não informado</span>`;
  return `<span class="expected-badge ${manual.expectedClass === "ATAQUE" ? "attack" : "normal"}">${manual.expectedClass}</span><small>${manual.expectedDecision === "BLOQUEIA" ? "Deveria bloquear" : "Deveria liberar"}</small>`;
}

function requestCell(row, prefix, manual) {
  const decision = row[`${prefix}_decision`];
  return `<div class="model-result"><strong>${String(row[`${prefix}_algorithm`] || "").toUpperCase()} · ${num(row[`${prefix}_score`])}</strong>${decisionBadge(decision)}${correctnessBadge(decision, manual)}</div>`;
}

async function loadRequests() {
  try {
    const data = await getJSON(`api/requests?page=${state.page}&per_page=15&t=${Date.now()}`);
    state.page = data.page;
    state.pages = data.pages;
    $("total").textContent = data.summary.total;
    $("allowed").textContent = data.summary.allowed;
    $("blocked").textContent = data.summary.blocked;
    $("disagreements").textContent = data.summary.disagreements;
    $("page").textContent = `Página ${data.page} de ${data.pages}`;
    $("prev").disabled = data.page <= 1;
    $("next").disabled = data.page >= data.pages;
    $("history-updated").textContent = data.updated_at ? `Atualizado ${new Date(data.updated_at).toLocaleTimeString("pt-BR")}` : "Histórico vazio";
    $("request-rows").innerHTML = data.items.length ? data.items.map((row) => {
      const manual = state.manualLabels[row.timestamp];
      return `<tr><td>${new Date(row.timestamp).toLocaleTimeString("pt-BR")}</td>
        <td><strong>${escapeHTML(row.method)}</strong><small title="${escapeHTML(row.target_path)}">${escapeHTML(row.target_path)}</small></td>
        <td>${expectedCell(manual)}</td><td>${requestCell(row, "e1", manual)}</td><td>${requestCell(row, "e2", manual)}</td>
        <td><strong>${modelLabel(row.primary_model)}</strong><small>${escapeHTML(row.operational_decision)}</small></td><td><strong>${row.status_http}</strong></td></tr>`;
    }).join("") : `<tr><td colspan="7" class="empty">Aguardando requisições</td></tr>`;

    if (!state.lastManual) {
      const labeled = data.items.find((row) => state.manualLabels[row.timestamp]);
      if (labeled) {
        state.lastManual = { row: labeled, manual: state.manualLabels[labeled.timestamp] };
        renderLatestRequest();
      }
    }
    return data;
  } catch (error) {
    $("history-updated").textContent = `Erro: ${error.message}`;
    return null;
  }
}

async function clearMonitorHistory() {
  const confirmed = window.confirm("Limpar todo o histórico do Monitor WAF, a última requisição e os indicadores? Esta ação não altera modelos nem experimentos.");
  if (!confirmed) return;
  const button = $("clear-history");
  button.disabled = true;
  button.textContent = "Limpando…";
  try {
    await postJSON("api/requests/clear", {});
    state.page = 1;
    state.pages = 1;
    state.lastManual = null;
    state.manualLabels = {};
    try { localStorage.removeItem(STORAGE_KEY); } catch (error) { /* armazenamento opcional */ }
    const latest = $("latest-request-content");
    latest.className = "latest-request-empty";
    latest.textContent = "Envie um teste manual para visualizar a comparação detalhada.";
    await loadRequests();
    $("history-updated").textContent = "Histórico limpo";
  } catch (error) {
    $("history-updated").textContent = `Não foi possível limpar: ${error.message}`;
  } finally {
    button.disabled = false;
    button.textContent = "Limpar histórico";
  }
}

function experimentDecisionCard(title, row, prefix) {
  const algorithm = row[`${prefix}_algorithm`];
  const experimentId = prefix === "e1" ? "experimento_1" : "experimento_2";
  const model = state.experiments?.[experimentId]?.models?.[algorithm];
  const manual = state.lastManual.manual;
  const correct = row[`${prefix}_decision`] === manual.expectedDecision;
  return `<article class="latest-decision-card"><div class="latest-card-head"><span>${title}</span>${correctnessBadge(row[`${prefix}_decision`], manual)}</div>
    <dl><div><dt>Algoritmo</dt><dd>${escapeHTML(String(algorithm || "Não disponível").toUpperCase())}</dd></div>
      <div><dt>Score</dt><dd>${num(row[`${prefix}_score`], 6)}</dd></div>
      <div><dt>Threshold</dt><dd>${model ? formatNumber(model.threshold) : "Não disponível"}</dd></div>
      <div><dt>Decisão</dt><dd>${decisionBadge(row[`${prefix}_decision`])}</dd></div></dl></article>`;
}

function renderLatestRequest() {
  if (!state.lastManual) return;
  const { row, manual } = state.lastManual;
  const e1Correct = row.e1_decision === manual.expectedDecision;
  const e2Correct = row.e2_decision === manual.expectedDecision;
  let summary = "Nenhum experimento correspondeu ao esperado nesta requisição.";
  if (e1Correct && e2Correct) summary = "Ambos corresponderam ao resultado esperado.";
  else if (e1Correct) summary = "Somente E1 correspondeu ao esperado.";
  else if (e2Correct) summary = "Somente E2 correspondeu ao esperado.";
  const content = $("latest-request-content");
  content.className = "latest-request-content";
  content.innerHTML = `<div class="latest-metadata">
    <span><small>Horário</small><strong>${new Date(row.timestamp).toLocaleTimeString("pt-BR")}</strong></span>
    <span><small>Método</small><strong>${escapeHTML(row.method)}</strong></span>
    <span><small>Path</small><strong>${escapeHTML(row.target_path)}</strong></span>
    <span><small>HTTP efetivo</small><strong>${row.status_http}</strong></span>
    <span class="metadata-wide"><small>Origem do teste</small><strong>${manual.source === "reserved" ? `Reserva CSIC · registro #${formatNumber(manual.sourceSequence)}` : "Entrada manual"}</strong></span>
    <span class="metadata-wide"><small>Query sanitizada</small><code>${escapeHTML(manual.query || "Não informada")}</code></span>
    <span class="metadata-wide"><small>Body sanitizado</small><code>${escapeHTML(manual.body || "Não informado")}</code></span>
  </div>
  <div class="latest-comparison">${experimentDecisionCard("Experimento 1", row, "e1")}${experimentDecisionCard("Experimento 2", row, "e2")}
    <article class="latest-decision-card expected-card"><div class="latest-card-head"><span>Resultado esperado</span>${expectedCell(manual)}</div>
      <dl><div><dt>Classe esperada</dt><dd>${manual.expectedClass}</dd></div><div><dt>Deveria</dt><dd>${manual.expectedDecision}</dd></div><div><dt>E1 acertou?</dt><dd>${e1Correct ? "SIM" : "NÃO"}</dd></div><div><dt>E2 acertou?</dt><dd>${e2Correct ? "SIM" : "NÃO"}</dd></div></dl></article>
  </div><p class="comparison-summary">${summary}</p>`;
}

function updateBodyVisibility() {
  const supportsBody = !["GET", "HEAD"].includes($("test-method").value);
  $("body-field").hidden = !supportsBody;
}

function setTestSource(source) {
  state.testSource = source;
  document.querySelectorAll(".test-source-tab").forEach((button) => {
    const active = button.dataset.testSource === source;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("manual-fields").hidden = source !== "manual";
  $("reserved-fields").hidden = source !== "reserved";
  if (source === "reserved" && !state.reservedItems.length) loadReservedSamples(true);
}

function selectedReservedRequest() {
  return state.reservedItems.find((item) => item.record_id === $("reserved-request").value) || null;
}

function renderReservedPreview() {
  const item = selectedReservedRequest();
  if (!item) {
    $("reserved-preview").textContent = "Nenhuma requisição disponível para o filtro selecionado.";
    return;
  }
  const body = item.body_preview || "Sem body";
  $("reserved-preview").innerHTML = `<div><span class="expected-badge ${item.expected_class === "ATAQUE" ? "attack" : "normal"}">${item.expected_class}</span><strong>${escapeHTML(item.method)}</strong><small>Registro reservado #${formatNumber(item.source_sequence)}</small></div>
    <code title="${escapeHTML(item.target)}">${escapeHTML(item.target)}</code>
    <p><strong>Body:</strong> ${escapeHTML(body)}${item.body_truncated ? "…" : ""}</p>`;
}

async function loadReservedSamples(resetMethods = false) {
  const select = $("reserved-request");
  const refresh = $("refresh-reserved");
  const methodSelect = $("reserved-method");
  select.disabled = true;
  refresh.disabled = true;
  select.innerHTML = `<option value="">Carregando reserva…</option>`;
  try {
    const label = $("reserved-class").value;
    const method = resetMethods ? "" : methodSelect.value;
    const data = await getJSON(`api/reserved?label=${encodeURIComponent(label)}&method=${encodeURIComponent(method)}&limit=20&t=${Date.now()}`);
    if (resetMethods) {
      methodSelect.replaceChildren(new Option("Todos os métodos", ""));
      data.available_methods.forEach((availableMethod) => methodSelect.add(new Option(availableMethod, availableMethod)));
    }
    state.reservedItems = data.items;
    select.replaceChildren();
    data.items.forEach((item, index) => {
      const compactTarget = item.target.length > 110 ? `${item.target.slice(0, 107)}…` : item.target;
      select.add(new Option(`${index + 1}. [${item.method}] ${compactTarget}`, item.record_id));
    });
    const classPlural = data.expected_class === "ATAQUE" ? "de ataque" : "normais";
    $("reserved-count").textContent = `${formatNumber(data.available_count)} requisições ${classPlural} disponíveis neste filtro; nenhuma participou dos experimentos.`;
    renderReservedPreview();
  } catch (error) {
    state.reservedItems = [];
    select.innerHTML = `<option value="">Reserva indisponível</option>`;
    $("reserved-count").textContent = `Não foi possível consultar a reserva: ${error.message}`;
    renderReservedPreview();
  } finally {
    select.disabled = false;
    refresh.disabled = false;
  }
}

function parseManualDefinition() {
  const rawValue = sanitizedText($("test-url").value, 1000);
  if (!rawValue) throw new Error("Informe uma URL ou caminho para o teste.");
  const parsed = new URL(rawValue, window.location.origin);
  if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("Use uma URL HTTP/HTTPS ou um caminho iniciado por /. ");
  if (parsed.pathname.startsWith("/dashboard")) throw new Error("Escolha um caminho da aplicação protegida, fora de /dashboard.");
  const localUrl = new URL(`${parsed.pathname}${parsed.search}`, window.location.origin);
  const expectedClass = $("expected-class").value;
  return {
    source: "manual",
    expectedClass,
    expectedDecision: expectedClass === "ATAQUE" ? "BLOQUEIA" : "LIBERA",
    method: $("test-method").value,
    url: localUrl,
    query: sanitizedText(localUrl.search.slice(1)),
    body: sanitizedText($("test-body").value, 4000),
  };
}

async function waitForHistory(method, path, startedAt) {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const data = await getJSON(`api/requests?page=1&per_page=50&t=${Date.now()}`);
    const row = data.items.find((item) => item.method === method && item.target_path === path && new Date(item.timestamp).getTime() >= startedAt - 2000);
    if (row) return row;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return null;
}

async function submitManualTest(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  const status = $("manual-test-status");
  const repeatCount = Number($("repeat-count").value);
  button.disabled = true;
  let completed = 0;
  try {
    const manualDefinition = state.testSource === "manual" ? parseManualDefinition() : null;
    const reserved = state.testSource === "reserved" ? selectedReservedRequest() : null;
    if (state.testSource === "reserved" && !reserved) throw new Error("Escolha uma requisição da reserva CSIC.");
    for (let index = 0; index < repeatCount; index += 1) {
      status.textContent = `Enviando ${index + 1} de ${repeatCount} pelo pipeline real…`;
      const startedAt = Date.now();
      let responseStatus;
      let method;
      let path;
      let manual;
      if (manualDefinition) {
        method = manualDefinition.method;
        path = manualDefinition.url.pathname;
        const options = { method, cache: "no-store", credentials: "same-origin", headers: {} };
        if (!["GET", "HEAD"].includes(method)) {
          options.body = manualDefinition.body;
          options.headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8";
        }
        const response = await fetch(manualDefinition.url, options);
        responseStatus = response.status;
        manual = {
          source: "manual",
          expectedClass: manualDefinition.expectedClass,
          expectedDecision: manualDefinition.expectedDecision,
          method,
          path,
          query: manualDefinition.query,
          body: manualDefinition.body,
          responseStatus,
        };
      } else {
        const replay = await postJSON("api/reserved/execute", { record_id: reserved.record_id });
        method = reserved.method;
        path = reserved.path;
        responseStatus = replay.status_http;
        manual = {
          source: "reserved",
          recordId: reserved.record_id,
          sourceSequence: reserved.source_sequence,
          expectedClass: reserved.expected_class,
          expectedDecision: reserved.expected_decision,
          method,
          path,
          query: sanitizedText(reserved.query),
          body: sanitizedText(reserved.body_preview),
          responseStatus,
        };
      }
      const row = await waitForHistory(method, path, startedAt);
      if (!row) throw new Error("A requisição foi enviada, mas o registro do monitor ainda não ficou disponível.");
      state.manualLabels[row.timestamp] = manual;
      state.lastManual = { row, manual };
      completed += 1;
    }
    persistManualLabels();
    renderLatestRequest();
    state.page = 1;
    await loadRequests();
    status.textContent = `${completed} ${completed === 1 ? "requisição concluída" : "requisições concluídas"}. Comparação registrada no histórico.`;
  } catch (error) {
    if (completed) {
      persistManualLabels();
      renderLatestRequest();
      state.page = 1;
      await loadRequests();
    }
    status.textContent = `${completed ? `${completed} concluída(s). ` : ""}Não foi possível continuar: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function initManualTest() {
  document.querySelectorAll(".test-source-tab").forEach((button) => button.addEventListener("click", () => setTestSource(button.dataset.testSource)));
  $("test-method").addEventListener("change", updateBodyVisibility);
  $("reserved-class").addEventListener("change", () => loadReservedSamples(true));
  $("reserved-method").addEventListener("change", () => loadReservedSamples(false));
  $("reserved-request").addEventListener("change", renderReservedPreview);
  $("refresh-reserved").addEventListener("click", () => loadReservedSamples(false));
  $("repeat-count").addEventListener("change", () => {
    const count = Number($("repeat-count").value);
    $("send-test").textContent = count === 1 ? "Enviar requisição de teste" : `Enviar a mesma requisição ${count} vezes`;
  });
  $("manual-test-form").addEventListener("submit", submitManualTest);
  updateBodyVisibility();
  setTestSource("manual");
}

function initBackground() {
  const canvas = $("network-background");
  const ctx = canvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let nodes = [];
  let pointer = { x: -9999, y: -9999 };
  let frame = 0;
  function resize() {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = innerWidth * ratio;
    canvas.height = innerHeight * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const count = Math.min(95, Math.max(36, Math.floor(innerWidth * innerHeight / 18000)));
    nodes = Array.from({ length: count }, () => ({ x: Math.random() * innerWidth, y: Math.random() * innerHeight, vx: (Math.random() - 0.5) * 0.12, vy: (Math.random() - 0.5) * 0.12, r: 1.2 + Math.random() * 1.5 }));
  }
  function draw() {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    nodes.forEach((node, index) => {
      if (!reduced) {
        node.x += node.vx; node.y += node.vy;
        if (node.x < 0 || node.x > innerWidth) node.vx *= -1;
        if (node.y < 0 || node.y > innerHeight) node.vy *= -1;
        const dx = node.x - pointer.x; const dy = node.y - pointer.y; const distance = Math.hypot(dx, dy);
        if (distance < 145 && distance > 0) { node.x += dx / distance * 0.23; node.y += dy / distance * 0.23; }
      }
      for (let otherIndex = index + 1; otherIndex < nodes.length; otherIndex += 1) {
        const other = nodes[otherIndex]; const distance = Math.hypot(node.x - other.x, node.y - other.y);
        if (distance < 125) {
          ctx.strokeStyle = `rgba(23,105,224,${0.16 * (1 - distance / 125)})`;
          ctx.beginPath(); ctx.moveTo(node.x, node.y); ctx.lineTo(other.x, other.y); ctx.stroke();
        }
      }
      ctx.fillStyle = "rgba(23,105,224,.30)"; ctx.beginPath(); ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2); ctx.fill();
    });
    if (!reduced && !document.hidden) frame = requestAnimationFrame(draw);
  }
  addEventListener("resize", resize);
  addEventListener("pointermove", (event) => { pointer = { x: event.clientX, y: event.clientY }; }, { passive: true });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduced) { cancelAnimationFrame(frame); draw(); } });
  resize(); draw();
}

function initNavigation() {
  const links = [...document.querySelectorAll(".nav-link")];
  const sections = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
  const activate = (id) => links.forEach((link) => {
    const active = link.getAttribute("href") === `#${id}`;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location"); else link.removeAttribute("aria-current");
  });
  links.forEach((link) => link.addEventListener("click", () => activate(link.getAttribute("href").slice(1))));
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (visible) activate(visible.target.id);
  }, { rootMargin: "-24% 0px -58%", threshold: [0, 0.1, 0.35] });
  sections.forEach((section) => observer.observe(section));
}

addEventListener("resize", () => {
  clearTimeout(state.chartResizeTimer);
  state.chartResizeTimer = setTimeout(() => {
    document.querySelectorAll(".experiment-panel:not([hidden]) .chart").forEach((canvas) => {
      const [, experimentId, algorithm, diversity] = canvas.id.match(/^chart-(experimento_\d+)-(bp|ag)(-diversity)?$/) || [];
      if (experimentId && algorithm) drawChart(canvas, state.experiments[experimentId].models[algorithm].diagnostic.series, diversity ? "diversity" : algorithm);
    });
  }, 160);
}, { passive: true });

$("prev").addEventListener("click", () => { state.page -= 1; loadRequests(); });
$("next").addEventListener("click", () => { state.page += 1; loadRequests(); });
$("clear-history").addEventListener("click", clearMonitorHistory);
$("training-dialog-close").addEventListener("click", () => $("training-dialog").close());
$("training-dialog").addEventListener("cancel", (event) => {
  if (state.trainingJob && ["queued", "running"].includes(state.trainingJob.status)) event.preventDefault();
});
initNavigation();
initManualTest();
initBackground();
loadData();
loadRequests();
resumeActiveTraining();
setInterval(loadRequests, 3000);
setInterval(loadData, 30000);
