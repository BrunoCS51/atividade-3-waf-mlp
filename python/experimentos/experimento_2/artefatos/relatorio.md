# Experimento 2 — CSIC 2010 — estado atual dos modelos

Cada modelo pode possuir arquitetura e configuração próprias após retreinamento controlado.
O conjunto reservado externo não participa do treinamento.

## BP

- Arquitetura: `76 → 228 → 1`
- Threshold: 0.09 (>=)
- Tempo: 347.970 s
- Teste: TN=1058, FP=1192, FN=23, TP=2227, F1=0.785676

## AG

- Arquitetura: `76 → 116 → 1`
- Threshold: 0.05 (>=)
- Tempo: 1946.856 s
- Teste: TN=1115, FP=1135, FN=93, TP=2157, F1=0.778419
