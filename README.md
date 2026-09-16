# Ambiente WAF com Inteligência Artificial

Este ambiente contém a simulação de uma aplicação protegida por um modelo de Machine Learning (Perceptron Multicamadas).

## Como subir e testar
No terminal, execute:
```bash
docker compose up -d --build
```
Acesse `http://localhost:8080`.

## Dashboard de monitoramento

Com os containers em execucao, abra:

```text
http://localhost:8080/dashboard/
```

O dashboard lê os arquivos de diagnóstico, avaliação e seleção presentes em
`python/`, além de um log técnico seguro das decisões do WAF. O **Monitor WAF**
acompanha requisições e decisões em tempo quase real e pode iniciar a avaliação
externa controlada descrita abaixo; o **Painel ML** apresenta treinamento,
diagnósticos, validação, seleção e teste final.

O painel não executa treinamentos, não seleciona modelos e não altera a decisão
do WAF. Arquivos opcionais ausentes são apresentados como não disponíveis.

## Avaliação externa controlada — HTTP CSIC 2010

Esta integração tem finalidade exclusivamente educacional e acadêmica. O
**HTTP DATASET CSIC 2010** é usado para observar o comportamento do WAF com
requisições externas ao conjunto original do projeto. Ele não participa do
treinamento, validação, teste interno, seleção do modelo ou escolha do
threshold.

Arquivos utilizados:

- `normalTrafficTraining.txt`: requisições cujo ground truth externo é
  `NORMAL`. Apesar do nome original, o arquivo não treina a MLP deste projeto;
- `anomalousTrafficTest.txt`: requisições cujo ground truth externo é
  `ATAQUE`.

Fonte: [Machine-Learning-on-CSIC-2010, por Monkey-D-Groot](https://github.com/Monkey-D-Groot/Machine-Learning-on-CSIC-2010).

O repositório-fonte consultado não apresenta arquivo de licença nem declaração
clara de licença de redistribuição. A atribuição acima não substitui uma
licença. Por isso, os arquivos brutos não são versionados neste projeto e ficam
ignorados pelo Git. Para baixá-los localmente das duas URLs fixas da fonte:

```bash
python python/download_csic2010.py
```

Depois de subir o ambiente, inicie uma sessão no **Monitor WAF**, escolha
Normais, Ataques ou Misto e uma quantidade. O modo Misto usa proporções
equivalentes, seed fixa e ordem embaralhada. A execução é sequencial, com
pequeno intervalo, para avaliar classificação sem atuar como teste de carga.

A avaliação externa usa um único replay sequencial pelo pipeline real. A feature
temporal `request_rate` é calculada normalmente pelo extractor durante toda a
sequência, sem limpeza de estado entre as requisições. Consequentemente, a
cadência artificialmente curta do replayer também pode aumentar essa feature e
influenciar risco, decisão e métricas. Essa é uma limitação metodológica
observada da simulação, não uma correção ou alteração do modelo.

Toda requisição é reconstruída e enviada exclusivamente ao Nginx local. Hosts
presentes no dataset são descartados, redirects não são seguidos e não existe
campo para configurar outro alvo. Cookies, `JSESSIONID`, `Authorization`,
tokens, bodies e headers sensíveis não são persistidos nem enviados ao
navegador.

Fluxo resumido:

```text
CSIC 2010
  → parser seguro
  → replayer local
  → Nginx
  → WAF Python
  → extractor
  → 9 features
  → MLP selecionada
  → risk > threshold
  → LIBERADA / BLOQUEADA
  → comparação com o ground truth CSIC
  → matriz de confusão + métricas
```

As métricas desta avaliação externa aparecem separadas das métricas internas:
accuracy, precision, recall, F1-score, False Positive Rate e False Negative
Rate, além de TN, FP, FN e TP.

Após a simulação, a seção **Análise das características** compara, no backend,
as nove features brutas do dataset original com as requisições CSIC da execução
atual. O painel mostra estatísticas numéricas ou distribuições binárias, recortes
por rótulo real, ocorrências acima dos limites do extractor e exemplos
sanitizados TN/FP/FN/TP com valores brutos e normalizados. Essa análise é apenas
observacional: não recalcula decisões, não altera features, pesos ou o threshold.

O **Histórico de requisições** pertence à sessão atual do monitor, é reiniciado
visualmente ao abrir uma nova sessão e carrega somente 10 registros por página,
sempre do mais recente para o mais antigo. Risco e threshold exibidos na
simulação são os valores já usados pelo WAF na própria classificação.
