# Construção dos datasets — Experimento 2

## Contrato final

O contrato oficial contém **76 features**, em ordem fixa, selecionadas das 152 candidatas. Foram removidas **76**.

A lista ordenada está em `esquema_final_features.csv` e na constante `FEATURES_EXPERIMENTO_2` de `features_http.py`. O CSV de desenvolvimento usa essa ordem e acrescenta somente `label` ao final.

## Política de ausentes

Nenhum `None` é gravado. Valores ausentes são convertidos para `0.0` apenas quando há indicador explícito no mesmo vetor. Exemplos: query/body usam `*_present`; host usa `url_host_present`; porta usa `url_port_present` + `url_port_valid`; Content-Type e Content-Length usam seus indicadores de presença/validade. Assim, ausência, zero real e invalidade continuam distinguíveis. Não houve normalização.

## Reserva anterior ao desenvolvimento

Seed documentada: **20260917**. Cada requisição bruta recebeu uma chave pseudoaleatória SHA-256 formada por seed, classe, posição e hash do conteúdo. Os 15.000 menores valores de cada classe foram destinados ao desenvolvimento antes de qualquer extração de features. As demais requisições foram reservadas.

O CSV de desenvolvimento foi posteriormente embaralhado com `random.Random(seed)`; não existe alternância artificial entre labels.

| Partição | Normal | Anômalo | Total |
| --- | ---: | ---: | ---: |
| Desenvolvimento | 15.000 | 15.000 | 30000 |
| Reservado | 21.000 | 10.065 | 31065 |
| Total | 36.000 | 25.065 | 61065 |

## Rastreabilidade e replay

O reservado é JSONL e mantém target original, método, versão, path, query, headers, Content-Type, body em Base64 e a requisição HTTP exata em Base64. `record_id` identifica a ocorrência; `content_sha256` verifica os bytes. A ordem original é preservada dentro de cada arquivo de origem. `controle_particoes.jsonl` registra IDs e partição, mas não entra no modelo.

- Sobreposição de IDs: **0**.
- Sobreposição de conteúdo bruto: **0**.
- Requisições perdidas: **0**.
- Reconstrução do reservado validada: **True**.

## Arquivos e hashes

| Arquivo | Bytes | SHA-256 |
| --- | ---: | --- |
| `tratamento_dados/datasets/csic_experimento2_desenvolvimento.csv` | 6460777 | `6a259ca353d002ed17ab5a52099888cc859d791bdc3db95866117192d67c8fd2` |
| `tratamento_dados/datasets/csic_experimento2_reservado.jsonl` | 57407319 | `9a50b3098ea54390ebd78c033718d894fd4be378719a36fb8ff07397e7b123eb` |
| `tratamento_dados/datasets/controle_particoes.jsonl` | 13624210 | `d154d5ef91a63daa313af36406978619c1d482f2e02be8ead96ef50f59339637` |

## Principais remoções

- versão HTTP e scheme constantes no CSIC;
- GET one-hot redundante, usando GET como categoria-base;
- comprimento bruto e decodificado simultâneos;
- profundidade e número de segmentos simultâneos;
- proporção alfabética dependente das demais proporções;
- entropia e repetição máxima, pelo custo/instabilidade ou menor prioridade;
- padrões no URL completo já representados em path e query;
- médias/totais de parâmetros redundantes com comprimentos e máximos;
- headers constantes, User-Agent e Cookie com risco de memorizar o ambiente CSIC;
- medidas redundantes de Content-Length/body.

Todos os 76 motivos individuais estão em `features_removidas.csv`.

## Limitações conhecidas

- `method_is_put` permanece para que o método seja representável, mas PUT só aparece no anômalo do CSIC e não deve ser interpretado como regra universal de ataque.
- Expressões SQL/XSS/traversal são finitas e dependem da política de decodificação; podem produzir falsos positivos e negativos.
- A validade externa do esquema ainda deve ser testada em tráfego não pertencente ao CSIC.
- O reservado fica proibido para treinamento, validação, teste interno, threshold, arquitetura, hiperparâmetros, limites e seleção de modelo.

Nenhum split interno, normalização, limite, treinamento, AG, arquitetura ou threshold foi executado.
