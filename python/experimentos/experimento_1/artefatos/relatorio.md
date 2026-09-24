# Experimento 1 — dataset original — rodada oficial

Arquitetura baseline única: `9 → 10 → 1`.
Não houve busca de arquitetura e o conjunto reservado não foi utilizado.

## Dataset e metodologia

- Amostras: 10000
- Treino: 6999
- Validação: 1499
- Teste: 1502
- Normalização: configuracao academica original

## BP

- Threshold: 0.47 (>)
- Tempo: 41.974 s
- Parâmetros: `{"epochs": 100, "learning_rate": 0.01, "sample_shuffle_each_epoch": true, "backward": "comportamento academico legado preservado", "seed": 42}`
- Validação: TN=973, FP=2, FN=0, TP=524, accuracy=0.998666, precision=0.996198, recall=1.000000, F1=0.998095, FPR=0.002051, FNR=0.000000
- Teste: TN=974, FP=2, FN=0, TP=526, accuracy=0.998668, precision=0.996212, recall=1.000000, F1=0.998102, FPR=0.002049, FNR=0.000000
- Diagnóstico: `python/experimentos/experimento_1/artefatos/bp/diagnostico.csv`

## AG

- Threshold: 0.46 (>)
- Tempo: 8.912 s
- Parâmetros: `{"population": 100, "generations": 100, "selection_type": 1, "tournament_size": 3, "crossover_type": 2, "crossover_rate": 0.8, "sbx_eta": 1.0, "mutation_type": 1, "mutation_rate": 0.02, "mutation_sigma": 0.1, "mutation_eta": 20.0, "weight_min": -5.0, "weight_max": 5.0, "elitism": 1, "seed": 43}`
- Validação: TN=970, FP=5, FN=0, TP=524, accuracy=0.996664, precision=0.990548, recall=1.000000, F1=0.995252, FPR=0.005128, FNR=0.000000
- Teste: TN=969, FP=7, FN=0, TP=526, accuracy=0.995340, precision=0.986867, recall=1.000000, F1=0.993390, FPR=0.007172, FNR=0.000000
- Diagnóstico: `python/experimentos/experimento_1/artefatos/ag/diagnostico.csv`
