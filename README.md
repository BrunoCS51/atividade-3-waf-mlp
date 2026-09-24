# WAF com MLP — experimentos comparáveis

- **Aluno 1:** Bruno Sousa de Castro — **RA:** 5132956
- **Aluno 2:** Dener Reis Menezes — **RA:** 5170343

O projeto protege uma aplicação PHP por meio de um WAF em Flask e mantém dois experimentos acadêmicos independentes, mas com a mesma estrutura de avaliação. A implementação da MLP, do Backpropagation, do Algoritmo Genético, das métricas e da inferência é compartilhada; extractors, features, normalizações, pesos e thresholds pertencem a cada experimento.

## Estrutura relevante

```text
python/
├── mlp.py, ga.py, experiment_core.py       # código acadêmico comum
├── model_runtime.py, server.py              # inferência paralela e WAF
├── experimentos/
│   ├── treinar_oficial.py                   # uma rodada oficial, protegida contra repetição
│   ├── experimento_1/
│   │   ├── config.py, extractor.py, requisicoes.csv
│   │   └── artefatos/{bp,ag}/
│   └── experimento_2/
│       ├── config.py
│       └── artefatos/{bp,ag}/
dashboard/                                   # monitor e comparação E1 × E2
tratamento_dados/features_http.py            # contrato/extractor único das 76 features
```

## Experimentos oficiais

| Experimento | Dataset | Features | Arquitetura BP e AG | Normalização |
|---|---|---:|---|---|
| 1 | Dataset original do professor | 9 | `9 → 10 → 1` | limites fixos do extractor E1 |
| 2 | `csic_experimento2_desenvolvimento.csv` | 76 | `76 → 77 → 1` | robusta, ajustada somente nas 21.000 amostras de treino |

O Experimento 2 utiliza o split estratificado congelado de 30.000 amostras: 21.000 treino, 4.500 validação e 4.500 teste. O conjunto reservado CSIC não participa do treinamento, da escolha de threshold nem dos resultados oficiais atuais.

A rodada oficial já foi concluída uma única vez. O marcador `rodada_oficial.json` faz o script recusar uma segunda execução acidental. Não execute `python/experimentos/treinar_oficial.py` para iniciar o ambiente; treinamento não é necessário para servir os modelos.

Cada pasta `artefatos/` contém configuração, contrato de features, normalização, manifesto e índices do split, resultados consolidados e relatório. Em `bp/` e `ag/` ficam separadamente `pesos.json`, `resultado.json` e `diagnostico.csv`.

## Modelo principal e shadow

Os quatro modelos são carregados na inicialização. `WAF_PRIMARY_MODEL` escolhe o único modelo que libera a requisição para o PHP ou devolve HTTP 403:

```powershell
$env:WAF_PRIMARY_MODEL = "experimento_1:bp"  # padrão
# alternativas: experimento_1:ag, experimento_2:bp, experimento_2:ag
docker compose up --build
```

O algoritmo usado no outro experimento pode ser definido por `WAF_SHADOW_E1_ALGORITHM` e `WAF_SHADOW_E2_ALGORITHM` (`bp` ou `ag`). Quando o experimento é o principal, o algoritmo indicado no próprio `WAF_PRIMARY_MODEL` prevalece. Para cada requisição, E1 extrai 9 features e E2 reutiliza diretamente `tratamento_dados/features_http.py` para extrair 76. Ambos produzem score e decisão, mas somente o principal controla o HTTP.

## Execução e dashboard

```powershell
docker compose up --build
```

- Aplicação protegida: <http://localhost:8080/>
- Dashboard: <http://localhost:8080/dashboard/>

O dashboard começa pelo monitor operacional. Cada linha mostra E1 e E2 para a mesma requisição, o modelo principal e a decisão HTTP efetiva. A seção seguinte apresenta os experimentos lado a lado, com arquitetura, dataset, BP, AG, métricas, matrizes, curvas diagnósticas e parâmetros lidos dos artefatos oficiais — não há resultados codificados manualmente na interface.

No painel **Teste de requisição**, a entrada pode ser escrita manualmente ou escolhida do conjunto `csic_experimento2_reservado.jsonl`. Essa reserva foi separada antes do desenvolvimento e não participou de treino, validação, teste interno, normalização, threshold ou seleção dos modelos. A classe conhecida acompanha o replay pelo pipeline real e permite comparar o esperado com E1 e E2. O mesmo caso pode ser enviado sequencialmente em quantidades predefinidas de até 500 vezes, sem limpar o histórico temporal.

Cada aba BP/AG também apresenta uma **análise de arquitetura e treinamento** baseada nos mesmos critérios para os dois experimentos. As regras usam apenas treino, validação e diagnósticos registrados para sugerir próximos testes isolados de capacidade, épocas/gerações e otimização. As metas exibidas são referências acadêmicas configuráveis, não limites universais; nenhuma sugestão altera automaticamente arquitetura, parâmetros ou pesos. A análise das entradas não recomenda excluir features enquanto não houver importância por permutação, redundância e ablação medidas na validação.

A aba **Configurar treino** permite iniciar, de forma explícita, um novo treinamento isolado de BP ou AG em cada experimento. No BP podem ser ajustados camadas ocultas, épocas e learning rate; no AG, camadas ocultas, população, gerações e os operadores nomeados de seleção, crossover e mutação com seus parâmetros. Entradas/saída, dataset, split, normalização e seed continuam fixos. A interface mostra progresso e estimativa de tempo, mantém a versão atual ativa durante o processamento e, ao concluir, arquiva os artefatos anteriores em `historico_treinamentos/` antes de atualizar resultados e runtime. Apenas um treinamento pode ser executado por vez.

Ao final de cada aba BP/AG, o **Histórico de retreinamentos** compara cada versão resultante com a imediatamente anterior. São exibidos apenas arquitetura, parâmetros alterados, threshold, métricas essenciais e variações de FN/FP, recall, F1 e accuracy. O parecer “melhorou/piorou” usa primeiro o custo de segurança da validação; as diferenças do teste permanecem identificadas como observação final. Modelos nunca retreinados exibem histórico zerado.

As decisões de hiperparâmetros devem ser feitas pelas métricas de validação. Embora o painel apresente o teste após cada execução para completar o relatório, consultar repetidamente esse resultado durante a busca pode introduzir viés; o teste deve ser tratado como avaliação final da configuração escolhida. O conjunto CSIC reservado para testes no monitor nunca entra nesse fluxo.

O histórico `python/monitor_waf.csv` é runtime, começa ausente/vazio e é criado automaticamente na primeira requisição. Ele registra somente timestamp, método, caminho sanitizado, modelo principal, scores/decisões E1/E2 e status final; query, body e cookies não são armazenados.

## Validação mínima, sem treinamento

```powershell
python -m unittest python/test_integracao_final.py
node --check dashboard/app.js
docker compose config
```

Esses testes verificam os quatro modelos, arquiteturas, separação de pesos e thresholds, split/normalização E2, inferência E1/E2 para uma requisição, autoridade exclusiva do principal e leitura do dashboard. Eles não treinam, não acessam o conjunto reservado e não fazem replay massivo.

## Limitação observada

Esta é uma baseline estrutural, não uma busca de arquitetura. Em especial, o AG `76 → 77 → 1` usa configuração reduzida e viável para 6.007 parâmetros; a rodada única deve ser interpretada como ponto de partida diagnóstico, não como evidência de arquitetura ou hiperparâmetros ótimos.
