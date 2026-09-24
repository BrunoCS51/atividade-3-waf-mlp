(function exposeDiagnosticAnalysis(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.DiagnosticAnalysis = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function diagnosticAnalysisFactory() {
  "use strict";

  const ACCEPTANCE = Object.freeze({
    accuracy: { label: "Accuracy", operator: ">=", target: 0.95 },
    precision: { label: "Precision", operator: ">=", target: 0.95 },
    recall: { label: "Recall", operator: ">=", target: 0.95 },
    f1: { label: "F1", operator: ">=", target: 0.95 },
    fpr: { label: "FPR", operator: "<=", target: 0.05 },
    fnr: { label: "FNR", operator: "<=", target: 0.05 },
  });

  const finite = (value) => Number.isFinite(Number(value));
  const roundUp = (value) => Math.max(2, Math.ceil(Number(value)));

  function metricChecks(metrics) {
    return Object.entries(ACCEPTANCE).map(([key, criterion]) => {
      const value = Number(metrics?.[key]);
      const passed = finite(value) && (criterion.operator === ">=" ? value >= criterion.target : value <= criterion.target);
      return { key, ...criterion, value: finite(value) ? value : null, passed };
    });
  }

  function recentImprovement(series, key) {
    const rows = (series || []).filter((row) => finite(row[key]));
    if (rows.length < 2) return null;
    const start = Number(rows[Math.max(0, Math.floor(rows.length * 0.8) - 1)][key]);
    const end = Number(rows[rows.length - 1][key]);
    return Math.abs(start) > 1e-12 ? (start - end) / Math.abs(start) : 0;
  }

  function oscillationRatio(series, key) {
    const values = (series || []).map((row) => Number(row[key])).filter(Number.isFinite);
    if (values.length < 4) return 0;
    const signs = [];
    for (let index = 1; index < values.length; index += 1) {
      const delta = values[index] - values[index - 1];
      if (Math.abs(delta) > 1e-10) signs.push(Math.sign(delta));
    }
    if (signs.length < 2) return 0;
    let changes = 0;
    for (let index = 1; index < signs.length; index += 1) {
      if (signs[index] !== signs[index - 1]) changes += 1;
    }
    return changes / (signs.length - 1);
  }

  function architectureCandidates(architecture) {
    const input = architecture[0];
    const output = architecture[architecture.length - 1];
    const hidden = architecture.slice(1, -1);
    if (hidden.length === 1) {
      const width = hidden[0];
      return {
        wider: [input, roundUp(width * 1.5), output],
        deeper: [input, width, roundUp(width / 2), output],
      };
    }
    return {
      wider: [input, ...hidden.map((width) => roundUp(width * 1.25)), output],
      deeper: [input, ...hidden, roundUp(hidden[hidden.length - 1] / 2), output],
    };
  }

  function evaluateModel(experiment, algorithm) {
    const model = experiment.models[algorithm];
    const train = model.metrics.treino;
    const validation = model.metrics.validacao;
    const final = model.diagnostic?.final || {};
    const series = model.diagnostic?.series || [];
    const checks = metricChecks(validation);
    const passedCount = checks.filter((check) => check.passed).length;
    const acceptable = passedCount === checks.length;
    const f1Gap = finite(train.f1) && finite(validation.f1) ? Number(train.f1) - Number(validation.f1) : null;
    const mseGap = finite(final.train_validation_gap) ? Number(final.train_validation_gap) : null;
    const similarTrainValidation = Math.abs(f1Gap || 0) <= 0.03;
    const lowTrainPerformance = Number(train.f1) < ACCEPTANCE.f1.target || Number(train.accuracy) < ACCEPTANCE.accuracy.target;
    const underfitSignal = !acceptable && lowTrainPerformance && similarTrainValidation;
    const overfitSignal = finite(f1Gap) && f1Gap > 0.05;
    const candidates = architectureCandidates(model.architecture);
    const recommendations = [];

    if (acceptable && !overfitSignal) {
      recommendations.push({
        area: "Arquitetura",
        level: "keep",
        title: "Manter a arquitetura atual",
        reason: "Os critérios referenciais foram atendidos na validação e não há gap relevante em relação ao treino.",
        action: `Preservar ${model.architecture.join(" → ")} na próxima rodada; não existe evidência atual para adicionar camadas ou neurônios.`,
      });
    } else if (overfitSignal) {
      recommendations.push({
        area: "Arquitetura",
        level: "warn",
        title: "Não aumentar a capacidade agora",
        reason: "O desempenho de treino está materialmente acima da validação, sinal compatível com perda de generalização.",
        action: "Testar primeiro uma rede menor ou regularização, mantendo o conjunto de validação como critério. Adicionar camadas pode ampliar o gap.",
      });
    } else if (underfitSignal && algorithm === "ag" && Number(model.parameters?.population) < 32) {
      recommendations.push({
        area: "Arquitetura",
        level: "investigate",
        title: "Adiar a conclusão sobre novas camadas",
        reason: "Treino e validação estão fracos de forma semelhante, mas o AG usou uma população pequena para a quantidade de genes.",
        action: `Primeiro reavaliar o otimizador na arquitetura ${model.architecture.join(" → ")}. Se continuar limitado, comparar isoladamente ${candidates.wider.join(" → ")} e ${candidates.deeper.join(" → ")}.`,
      });
    } else {
      recommendations.push({
        area: "Arquitetura",
        level: "investigate",
        title: "Testar aumento controlado de capacidade",
        reason: "Treino e validação apresentam desempenho limitado e próximo entre si; isso é compatível com subajuste, mas não prova que a arquitetura seja a única causa.",
        action: `Comparar, em rodadas separadas, a largura ${candidates.wider.join(" → ")} e a profundidade ${candidates.deeper.join(" → ")}, mantendo os demais fatores fixos.`,
      });
    }

    if (algorithm === "bp") {
      const trend = recentImprovement(series, "validation_mse");
      const epochs = Number(model.parameters?.epochs);
      if (!acceptable && finite(trend) && trend > 0.01) {
        recommendations.push({
          area: "Orçamento de treino",
          level: "try",
          title: "Aumentar épocas em uma rodada controlada",
          reason: `O MSE de validação ainda melhorou ${(trend * 100).toFixed(2)}% no trecho final registrado.`,
          action: `Testar ${Math.ceil(epochs * 1.5)} épocas, preservando learning rate e arquitetura para isolar o efeito.`,
        });
      } else {
        recommendations.push({
          area: "Orçamento de treino",
          level: acceptable ? "keep" : "warn",
          title: acceptable ? "Épocas suficientes para a referência atual" : "Mais épocas, isoladamente, têm baixa prioridade",
          reason: finite(trend) ? `A melhoria recente do MSE de validação foi ${(trend * 100).toFixed(2)}%.` : "O artefato não contém série suficiente para medir a tendência final.",
          action: acceptable ? `Manter ${epochs} épocas.` : "Priorizar a investigação de representação/arquitetura; aumentar épocas somente como teste isolado.",
        });
      }
      const oscillation = oscillationRatio(series, "validation_mse");
      const saturation = Number(final.hidden_saturation_percentage);
      const learningRate = Number(model.parameters?.learning_rate);
      const shouldReduceRate = !acceptable && oscillation > 0.55;
      recommendations.push({
        area: "Otimização",
        level: shouldReduceRate ? "try" : saturation > 35 ? "warn" : "keep",
        title: shouldReduceRate ? "Testar learning rate menor" : "Manter learning rate nesta etapa",
        reason: `Oscilação direcional da validação: ${(oscillation * 100).toFixed(1)}%; saturação oculta final: ${finite(saturation) ? saturation.toFixed(2) : "N/D"}%.`,
        action: shouldReduceRate ? `Comparar ${learningRate} com ${learningRate / 2}, sem mudar épocas ou arquitetura na mesma rodada.` : `Preservar ${learningRate}; não há sinal conjunto suficiente para reduzi-lo automaticamente.`,
      });
    } else {
      const trend = recentImprovement(series, "global_best_train_mse");
      const generations = Number(model.parameters?.generations);
      const population = Number(model.parameters?.population);
      const genes = Number(model.training?.genes || model.parameter_count);
      const firstDiversity = Number(series[0]?.population_diversity);
      const finalDiversity = Number(final.population_diversity);
      const diversityRatio = finite(firstDiversity) && firstDiversity > 0 ? finalDiversity / firstDiversity : null;
      recommendations.push({
        area: "Orçamento de treino",
        level: !acceptable && finite(trend) && trend > 0.005 ? "try" : acceptable ? "keep" : "warn",
        title: !acceptable && finite(trend) && trend > 0.005 ? "Aumentar gerações em teste isolado" : acceptable ? "Gerações suficientes para a referência atual" : "Aumentar gerações não basta por si só",
        reason: finite(trend) ? `O melhor fitness mudou ${(trend * 100).toFixed(2)}% no trecho final.` : "O artefato não contém série suficiente para medir a tendência final.",
        action: !acceptable && finite(trend) && trend > 0.005 ? `Testar ${Math.ceil(generations * 1.5)} gerações mantendo população e operadores.` : acceptable ? `Manter ${generations} gerações.` : "Revisar diversidade e tamanho populacional antes de ampliar somente as gerações.",
      });
      const smallPopulation = finite(genes) && population < Math.max(32, Math.sqrt(genes) / 2);
      const collapsed = finite(diversityRatio) && diversityRatio < 0.25;
      recommendations.push({
        area: "Otimização",
        level: !acceptable && (smallPopulation || collapsed) ? "try" : "keep",
        title: !acceptable && smallPopulation ? "Testar população maior" : collapsed ? "Investigar perda de diversidade" : "Manter configuração evolutiva nesta etapa",
        reason: `População ${population} para ${finite(genes) ? genes : "N/D"} genes; diversidade final ${finite(finalDiversity) ? finalDiversity.toFixed(6) : "N/D"}${finite(diversityRatio) ? ` (${(diversityRatio * 100).toFixed(1)}% da inicial)` : ""}.`,
        action: !acceptable && smallPopulation ? `Comparar população ${population} com ${Math.max(32, population * 2)}, mantendo gerações, crossover e mutação fixos.` : collapsed ? "Comparar uma alteração isolada na mutação ou na população; não alterar ambas simultaneamente." : "Nenhuma mudança evolutiva é indicada pelos critérios atuais.",
      });
    }

    recommendations.push({
      area: "Generalização",
      level: overfitSignal ? "warn" : "keep",
      title: overfitSignal ? "Gap treino–validação requer atenção" : "Treino e validação estão coerentes entre si",
      reason: `Gap de F1 treino–validação: ${finite(f1Gap) ? (f1Gap * 100).toFixed(2) : "N/D"} p.p.; gap de MSE: ${finite(mseGap) ? mseGap.toFixed(6) : "N/D"}.`,
      action: overfitSignal ? "Evitar usar o conjunto de teste para decidir; comparar regularização ou menor capacidade usando validação." : "Continuar tomando decisões de ajuste exclusivamente pela validação.",
    });

    const highFpr = Number(validation.fpr) > ACCEPTANCE.fpr.target;
    const highFnr = Number(validation.fnr) > ACCEPTANCE.fnr.target;
    recommendations.push({
      area: "Próximo experimento",
      level: acceptable ? "keep" : "priority",
      title: acceptable ? "Configuração atende à referência" : highFpr ? "Priorizar redução de falsos positivos" : highFnr ? "Priorizar redução de falsos negativos" : "Melhorar equilíbrio das métricas",
      reason: `Na validação: FPR ${(Number(validation.fpr) * 100).toFixed(2)}% e FNR ${(Number(validation.fnr) * 100).toFixed(2)}%.`,
      action: acceptable ? "Conservar como baseline e só substituir após uma comparação controlada reproduzível." : "Alterar um único fator por rodada, registrar a hipótese e aceitar a mudança somente se melhorar os critérios de validação sem degradar recall/FNR.",
    });

    return {
      basis: "Treino + validação; o conjunto de teste não participa das recomendações",
      status: acceptable ? "aceitavel" : "investigar",
      passedCount,
      totalChecks: checks.length,
      checks,
      evidence: {
        trainF1: Number(train.f1), validationF1: Number(validation.f1),
        validationFpr: Number(validation.fpr), validationFnr: Number(validation.fnr),
        f1Gap, mseGap,
      },
      recommendations,
      disclaimer: "Heurísticas diagnósticas não demonstram causalidade nem escolhem automaticamente uma arquitetura. Cada sugestão deve ser validada em uma nova rodada controlada.",
    };
  }

  function evaluateInputs(experiment) {
    const features = experiment.features?.ordered_features || [];
    const normalization = experiment.normalization?.features || [];
    const methods = {};
    normalization.forEach((feature) => {
      methods[feature.metodo] = (methods[feature.metodo] || 0) + 1;
    });
    return {
      featureCount: features.length || Number(experiment.feature_count),
      normalizationMethods: methods,
      status: "evidencia_insuficiente",
      conclusion: "Os artefatos atuais não contêm importância por feature, permutação ou ablação. Portanto, nenhuma entrada deve ser removida apenas por quantidade ou magnitude de pesos.",
      nextSteps: [
        "Medir importância por permutação exclusivamente na validação.",
        "Investigar variância quase nula e redundância/correlação entre entradas.",
        "Confirmar qualquer remoção com ablação e novo treinamento controlado.",
        "Usar o teste somente depois de congelar a nova seleção de features.",
      ],
    };
  }

  return { ACCEPTANCE, evaluateModel, evaluateInputs, metricChecks, recentImprovement, oscillationRatio };
}));
