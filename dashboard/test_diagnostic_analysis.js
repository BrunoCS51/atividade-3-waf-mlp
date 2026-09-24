"use strict";

const assert = require("node:assert/strict");
const analysis = require("./diagnostic-analysis.js");

function experiment(validationF1, validationFpr) {
  const model = {
    architecture: [9, 10, 1], parameter_count: 111,
    parameters: { epochs: 100, learning_rate: 0.01 },
    training: { genes: 111 },
    metrics: {
      treino: { accuracy: validationF1, f1: validationF1 },
      validacao: { accuracy: validationF1, precision: validationF1, recall: 0.99, f1: validationF1, fpr: validationFpr, fnr: 0.01 },
    },
    diagnostic: { final: { train_validation_gap: 0.001, hidden_saturation_percentage: 10 }, series: [{ validation_mse: 0.2 }, { validation_mse: 0.1 }] },
  };
  return { feature_count: 9, features: { ordered_features: Array(9).fill("x") }, normalization: { features: [] }, models: { bp: model } };
}

const acceptable = analysis.evaluateModel(experiment(0.98, 0.01), "bp");
const investigate = analysis.evaluateModel(experiment(0.70, 0.40), "bp");
const agExperiment = experiment(0.70, 0.40);
agExperiment.models.ag = JSON.parse(JSON.stringify(agExperiment.models.bp));
agExperiment.models.ag.parameters = { population: 16, generations: 20, mutation_rate: 0.02 };
agExperiment.models.ag.diagnostic.series = [
  { global_best_train_mse: 0.4, population_diversity: 0.5 },
  { global_best_train_mse: 0.2, population_diversity: 0.05 },
];
agExperiment.models.ag.diagnostic.final.population_diversity = 0.05;
const agInvestigate = analysis.evaluateModel(agExperiment, "ag");
assert.equal(acceptable.status, "aceitavel");
assert.equal(investigate.status, "investigar");
assert.deepEqual(acceptable.recommendations.map((item) => item.area), investigate.recommendations.map((item) => item.area));
assert.deepEqual(investigate.recommendations.map((item) => item.area), agInvestigate.recommendations.map((item) => item.area));
assert.equal(analysis.evaluateInputs(experiment(0.98, 0.01)).status, "evidencia_insuficiente");
console.log("diagnostic-analysis: OK");
