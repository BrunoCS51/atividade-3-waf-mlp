# Análise de features candidatas — Experimento 2

> Catálogo exploratório. Nenhuma candidata foi aprovada, normalizada ou selecionada, e nenhum modelo foi treinado.

## Escopo e implementação reutilizável

Foram propostas e calculadas **152 features candidatas** para **36000 requisições normais** e **25065 anômalas**. A função `extrair_features_candidatas` em `features_http.py` recebe uma requisição bruta ou um objeto HTTP canônico e não recebe label, dataset ou estado temporal. Ela poderá ser chamada sem duplicação tanto pela futura montagem do dataset quanto pelo WAF.

`request_rate` e outras informações de replay/tempo não fazem parte deste catálogo.

## Famílias estudadas

| Origem | Quantidade | Conteúdo |
| --- | --- | --- |
| method | 4 | one-hot GET/POST/PUT/outros |
| url | 36 | versão, forma, scheme, host, porta e composição |
| path | 28 | segmentos, profundidade, extensões e composição |
| query | 27 | presença, parâmetros, comprimentos, composição e padrões |
| body | 27 | presença, parâmetros, comprimentos, composição e padrões |
| headers | 30 | presença, cardinalidade, Content-Length, UA, Host e Cookie |

Cada cálculo, aplicabilidade e limitação está documentado em `features_candidatas.csv`. As estatísticas completas, com ausentes, mínimo, máximo, média, mediana, desvio padrão, percentis, valores distintos e frequências binárias, estão em `estatisticas_features.csv`.

## Comportamento observado — prevalência

| Feature | Normal: valores válidos | Normal: % igual a 1 | Anômalo: valores válidos | Anômalo: % igual a 1 |
| --- | --- | --- | --- | --- |
| `method_is_get` | 36000 | 77,78% | 25065 | 60,20% |
| `method_is_post` | 36000 | 22,22% | 25065 | 38,22% |
| `method_is_put` | 36000 | 0,00% | 25065 | 1,58% |
| `query_present` | 36000 | 22,22% | 25065 | 38,34% |
| `body_present` | 36000 | 22,22% | 25065 | 39,80% |
| `url_parse_error` | 36000 | 0,00% | 25065 | 0,00% |
| `path_nested_extension_transition` | 36000 | 0,00% | 25065 | 4,49% |
| `content_length_matches_body` | 8000 | 100,00% | 9977 | 100,00% |

A diferença de prevalência descreve estes dois arquivos; ela não constitui seleção automática nem evidência de causalidade.

## Comportamento observado — medidas numéricas

| Feature | Dataset | Válidos | Ausentes | Média | Mediana | P95 | Máximo | % não zero |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `url_length_raw` | normal | 36000 | 0 | 69.986 | 49.5 | 288 | 358 | 100,00% |
| `url_length_raw` | anomalo | 25065 | 0 | 97.612 | 55 | 314 | 886 | 100,00% |
| `path_length_raw` | normal | 36000 | 0 | 28.417 | 27 | 37 | 37 | 100,00% |
| `path_length_raw` | anomalo | 25065 | 0 | 29.067 | 28 | 42 | 66 | 100,00% |
| `path_segment_count` | normal | 36000 | 0 | 3.056 | 3 | 4 | 4 | 100,00% |
| `path_segment_count` | anomalo | 25065 | 0 | 2.928 | 3 | 4 | 6 | 98,94% |
| `path_extension_like_segment_count` | normal | 36000 | 0 | 1 | 1 | 1 | 1 | 100,00% |
| `path_extension_like_segment_count` | anomalo | 25065 | 0 | 1.015 | 1 | 1 | 3 | 96,49% |
| `query_parameter_count` | normal | 8000 | 28000 | 5.25 | 4 | 13 | 13 | 100,00% |
| `query_parameter_count` | anomalo | 9609 | 15456 | 5.825 | 5 | 13 | 13 | 100,00% |
| `query_max_value_length` | normal | 8000 | 28000 | 16.637 | 16 | 33 | 64 | 100,00% |
| `query_max_value_length` | anomalo | 9609 | 15456 | 29.038 | 21 | 68 | 370 | 99,88% |
| `body_parameter_count` | normal | 8000 | 28000 | 5.25 | 4 | 13 | 13 | 100,00% |
| `body_parameter_count` | anomalo | 9977 | 15088 | 5.827 | 5 | 13 | 13 | 100,00% |
| `body_max_value_length` | normal | 8000 | 28000 | 16.637 | 16 | 33 | 64 | 100,00% |
| `body_max_value_length` | anomalo | 9977 | 15088 | 28.485 | 21 | 67 | 370 | 100,00% |
| `header_unique_count` | normal | 36000 | 0 | 10.444 | 10 | 12 | 12 | 100,00% |
| `header_unique_count` | anomalo | 25065 | 0 | 10.796 | 10 | 12 | 12 | 100,00% |
| `url_percent_encoding_count` | normal | 36000 | 0 | 0.266 | 0 | 3 | 12 | 8,88% |
| `url_percent_encoding_count` | anomalo | 25065 | 0 | 1.903 | 0 | 10 | 114 | 29,58% |
| `query_sql_pattern_count` | normal | 8000 | 28000 | 0 | 0 | 0 | 1 | 0,03% |
| `query_sql_pattern_count` | anomalo | 9609 | 15456 | 0.206 | 0 | 1 | 4 | 13,65% |
| `query_xss_pattern_count` | normal | 8000 | 28000 | 0 | 0 | 0 | 0 | 0,00% |
| `query_xss_pattern_count` | anomalo | 9609 | 15456 | 0.068 | 0 | 0 | 2 | 3,83% |
| `query_traversal_pattern_count` | normal | 8000 | 28000 | 0 | 0 | 0 | 0 | 0,00% |
| `query_traversal_pattern_count` | anomalo | 9609 | 15456 | 0 | 0 | 0 | 0 | 0,00% |
| `body_sql_pattern_count` | normal | 8000 | 28000 | 0 | 0 | 0 | 1 | 0,03% |
| `body_sql_pattern_count` | anomalo | 9977 | 15088 | 0.198 | 0 | 1 | 4 | 13,15% |
| `body_xss_pattern_count` | normal | 8000 | 28000 | 0 | 0 | 0 | 0 | 0,00% |
| `body_xss_pattern_count` | anomalo | 9977 | 15088 | 0.066 | 0 | 0 | 2 | 3,69% |

## Preservação de informação do path

A representação não reduz o path a query/body. Para o caso conhecido `/tienda1/imagenes/nuestratierra.jpg/.Inc`, ela produz, entre outras medidas:

| Medida | Valor |
| --- | --- |
| segmentos | 4 |
| segmentos com aparência de extensão | 2 |
| segmentos iniciados por ponto | 1 |
| transição extensão → nova extensão | 1 |
| maior comprimento de segmento | 17 |

Assim, a ocorrência continua distinguível sem criar uma regra específica para `jpg` ou `.Inc`.

## Redundâncias e riscos identificados

- `path_depth` e `path_segment_count` são atualmente equivalentes; manter ambos no catálogo torna a redundância explícita, mas provavelmente apenas um deve chegar ao dataset.
- Comprimentos de URL, path, query e body são parcialmente aditivos; comprimento bruto, decodificado e total de valores também podem carregar informação muito semelhante.
- `alpha_ratio`, `digit_ratio` e `special_ratio` são composicionalmente dependentes e não devem ser tratados como totalmente independentes.
- Presença de body, POST/PUT, Content-Type e Content-Length são fortemente relacionadas neste corpus.
- `body_length_bytes`, `content_length_declared`, `content_length_delta` e `content_length_matches_body` formam outra família redundante.
- Versão HTTP, scheme, vários headers, User-Agent e Cookie apresentam pouca ou nenhuma diversidade no CSIC e podem memorizar o gerador do corpus.
- PUT ocorre apenas no anômalo, mas usar essa coincidência como regra causaria vazamento estrutural da composição do dataset.
- Indicadores SQL/XSS/traversal/comando são genéricos, porém dependem de expressões finitas, decodificação e idioma; podem ter falsos positivos, falsos negativos e redundância entre URL/query/body.
- Entropia é instável em strings curtas e relativamente mais custosa em execução real.
- A porta possui três estados distintos: ausente, válida e inválida. Preencher porta inválida com zero apagaria a informação encontrada em 231 requisições anômalas.
- Valores ausentes foram mantidos como `None` nas candidatas aplicáveis apenas a query, body, porta ou header. A estratégia numérica de imputação ainda precisa ser decidida.
- Nenhum nome concreto de parâmetro (`OpenServer`, `xmlfile` etc.) virou feature; isso reduz memorização direta de particularidades do CSIC.

## Informações ainda sujeitas a perda

- Uma única decodificação percentual pode não revelar codificação em múltiplas camadas; decodificar repetidamente também pode alterar semanticamente entradas legítimas.
- O parser agrega parâmetros por `&` e `=`. Separadores alternativos, bodies não form-urlencoded e multipart exigirão tratamento futuro.
- Contagens agregadas não preservam ordem dos parâmetros, nomes exatos, valores completos nem posição exata de cada padrão.
- Headers dobrados são contabilizados, mas ordem, capitalização original e whitespace não viram candidatas.
- Targets em forma de origem, HTTP/2 e tráfego HTTPS real não têm variedade suficiente nestes arquivos para validar todas as categorias propostas.

## Decisões pendentes antes do dataset

1. Reduzir famílias redundantes com justificativa e, se necessário, análise de correlação posterior sem usar a label como único critério.
2. Definir política explícita para valores ausentes e preservar indicadores de ausência/validade.
3. Decidir profundidade de percent-decoding e política consistente para bytes/Unicode entre construção do dataset e WAF.
4. Revisar e versionar as expressões de conteúdo, considerando custo, evasões e falsos positivos.
5. Decidir se características com variância zero no CSIC serão mantidas para compatibilidade com tráfego real ou removidas do modelo.
6. Validar as candidatas em requisições externas antes de fixar o esquema, especialmente Host, User-Agent, Cookie, forms e request-target relativo.
7. Definir a lista final e sua ordem; somente depois estabelecer normalização, limites e representação final de missing values.
8. Planejar a reserva de requisições brutas antes de qualquer split, sem permitir que essas requisições participem das decisões de engenharia posteriores.

## Garantias desta etapa

Não foi criado dataset final, realizado split, reservado subconjunto, normalizado valor, treinado modelo, executado AG ou definido threshold. Os arquivos brutos foram abertos somente para leitura.
