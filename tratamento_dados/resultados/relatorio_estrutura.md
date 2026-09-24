# Relatório de descoberta estrutural — CSIC 2010

> Esta etapa descreve o conteúdo observado. Não seleciona features, não define limites, não normaliza dados e não treina modelos.

## Escopo e método

Os dois arquivos foram percorridos integralmente em modo binário e sequencial. As contagens representam presença por requisição; `total_valores` no JSON também registra repetições do mesmo header ou parâmetro. Os exemplos são limitados a três por campo, truncados e têm cookies, credenciais e valores de parâmetros redigidos.

## Quantidade de requisições

| Dataset | Arquivo | Requisições | Bytes lidos | SHA-256 |
| --- | --- | --- | --- | --- |
| Normal | external_data/csic2010/normalTrafficTraining.txt | 36000 | 20640988 | `d3344377d4721b03b906ca232ab44bfd81b9c1356f967ec9d348532ec420f000` |
| Anômalo | external_data/csic2010/anomalousTrafficTest.txt | 25065 | 16090299 | `ec77d784966896330869c5b596ede6a716101c14b5f139144915bb10822a03e1` |

## Métodos HTTP encontrados

| Método | Normal | % normal | Anômalo | % anômalo |
| --- | --- | --- | --- | --- |
| GET | 28000 | 77,78% | 15088 | 60,20% |
| POST | 8000 | 22,22% | 9580 | 38,22% |
| PUT | 0 | 0,00% | 397 | 1,58% |

## Informações extraíveis de uma requisição

A estrutura observada permite extrair: método; target/URL original; versão HTTP; scheme, host, porta, path e query; nomes e valores dos parâmetros da query; conjunto de headers e seus valores; corpo; tipo e comprimento declarado do corpo; e nomes e valores de parâmetros de corpos `application/x-www-form-urlencoded`. A lista completa de campos, frequência, métodos, formas de valores e exemplos sanitizados está em `resumo_estrutura.json` e `comparacao_campos.csv`.

### Headers encontrados

| Dataset | Headers |
| --- | --- |
| Normal | accept, accept-charset, accept-encoding, accept-language, cache-control, connection, content-length, content-type, cookie, host, pragma, user-agent |
| Anômalo | accept, accept-charset, accept-encoding, accept-language, cache-control, connection, content-length, content-type, cookie, host, pragma, user-agent |

### Parâmetros encontrados

| Origem | Normal | Anômalo |
| --- | --- | --- |
| Query | B1, B2, apellidos, cantidad, ciudad, cp, direccion, dni, email, errorMsg, id, login, modo, nombre, ntc, password, precio, provincia, pwd, remember | B1, B1A, B2, B2A, Open, OpenServer, apellidos, apellidosA, cantidad, cantidadA, ciudad, ciudadA, cp, cpA, direccion, direccionA, dni, dniA, email, emailA, errorMsg, errorMsgA, id, idA, login, loginA, modo, modoA, nombre, nombreA, ntc, ntcA, password, passwordA, precio, precioA, provincia, provinciaA, pwd, pwdA, remember, rememberA, xmlfile |
| Body | B1, B2, apellidos, cantidad, ciudad, cp, direccion, dni, email, errorMsg, id, login, modo, nombre, ntc, password, precio, provincia, pwd, remember | B1, B1A, B2, B2A, apellidos, apellidosA, cantidad, cantidadA, ciudad, ciudadA, cp, cpA, direccion, direccionA, dni, dniA, email, emailA, errorMsg, errorMsgA, id, idA, login, loginA, modo, modoA, nombre, nombreA, ntc, ntcA, password, passwordA, precio, precioA, provincia, provinciaA, pwd, pwdA, remember, rememberA |

## Campos comuns e variáveis

### Normal

Presentes em todas as requisições (18): `header:accept`, `header:accept-charset`, `header:accept-encoding`, `header:accept-language`, `header:cache-control`, `header:connection`, `header:cookie`, `header:host`, `header:pragma`, `header:user-agent`, `headers`, `request.http_version`, `request.method`, `request.target`, `url.host`, `url.path`, `url.port`, `url.scheme`.

Presentes somente em parte (46): `body`, `body.parameters`, `body_param:B1`, `body_param:B2`, `body_param:apellidos`, `body_param:cantidad`, `body_param:ciudad`, `body_param:cp`, `body_param:direccion`, `body_param:dni`, `body_param:email`, `body_param:errorMsg`, `body_param:id`, `body_param:login`, `body_param:modo`, `body_param:nombre`, `body_param:ntc`, `body_param:password`, `body_param:precio`, `body_param:provincia`, `body_param:pwd`, `body_param:remember`, `header:content-length`, `header:content-type`, `query.parameters`, `query_param:B1`, `query_param:B2`, `query_param:apellidos`, `query_param:cantidad`, `query_param:ciudad`, `query_param:cp`, `query_param:direccion`, `query_param:dni`, `query_param:email`, `query_param:errorMsg`, `query_param:id`, `query_param:login`, `query_param:modo`, `query_param:nombre`, `query_param:ntc`, `query_param:password`, `query_param:precio`, `query_param:provincia`, `query_param:pwd`, `query_param:remember`, `url.query`.

### Anômalo

Presentes em todas as requisições (17): `header:accept`, `header:accept-charset`, `header:accept-encoding`, `header:accept-language`, `header:cache-control`, `header:connection`, `header:cookie`, `header:host`, `header:pragma`, `header:user-agent`, `headers`, `request.http_version`, `request.method`, `request.target`, `url.host`, `url.path`, `url.scheme`.

Presentes somente em parte (90): `body`, `body.parameters`, `body_param:B1`, `body_param:B1A`, `body_param:B2`, `body_param:B2A`, `body_param:apellidos`, `body_param:apellidosA`, `body_param:cantidad`, `body_param:cantidadA`, `body_param:ciudad`, `body_param:ciudadA`, `body_param:cp`, `body_param:cpA`, `body_param:direccion`, `body_param:direccionA`, `body_param:dni`, `body_param:dniA`, `body_param:email`, `body_param:emailA`, `body_param:errorMsg`, `body_param:errorMsgA`, `body_param:id`, `body_param:idA`, `body_param:login`, `body_param:loginA`, `body_param:modo`, `body_param:modoA`, `body_param:nombre`, `body_param:nombreA`, `body_param:ntc`, `body_param:ntcA`, `body_param:password`, `body_param:passwordA`, `body_param:precio`, `body_param:precioA`, `body_param:provincia`, `body_param:provinciaA`, `body_param:pwd`, `body_param:pwdA`, `body_param:remember`, `body_param:rememberA`, `header:content-length`, `header:content-type`, `query.parameters`, `query_param:B1`, `query_param:B1A`, `query_param:B2`, `query_param:B2A`, `query_param:Open`, `query_param:OpenServer`, `query_param:apellidos`, `query_param:apellidosA`, `query_param:cantidad`, `query_param:cantidadA`, `query_param:ciudad`, `query_param:ciudadA`, `query_param:cp`, `query_param:cpA`, `query_param:direccion`, `query_param:direccionA`, `query_param:dni`, `query_param:dniA`, `query_param:email`, `query_param:emailA`, `query_param:errorMsg`, `query_param:errorMsgA`, `query_param:id`, `query_param:idA`, `query_param:login`, `query_param:loginA`, `query_param:modo`, `query_param:modoA`, `query_param:nombre`, `query_param:nombreA`, `query_param:ntc`, `query_param:ntcA`, `query_param:password`, `query_param:passwordA`, `query_param:precio`, `query_param:precioA`, `query_param:provincia`, `query_param:provinciaA`, `query_param:pwd`, `query_param:pwdA`, `query_param:remember`, `query_param:rememberA`, `query_param:xmlfile`, `url.port`, `url.query`.

## Comparação normal × anômalo

Há **64 campos** observados nos dois conjuntos, **0 somente no normal** e **43 somente no anômalo**. Exclusivos do normal: nenhum. Exclusivos do anômalo: `body_param:B1A`, `body_param:B2A`, `body_param:apellidosA`, `body_param:cantidadA`, `body_param:ciudadA`, `body_param:cpA`, `body_param:direccionA`, `body_param:dniA`, `body_param:emailA`, `body_param:errorMsgA`, `body_param:idA`, `body_param:loginA`, `body_param:modoA`, `body_param:nombreA`, `body_param:ntcA`, `body_param:passwordA`, `body_param:precioA`, `body_param:provinciaA`, `body_param:pwdA`, `body_param:rememberA`, `query_param:B1A`, `query_param:B2A`, `query_param:Open`, `query_param:OpenServer`, `query_param:apellidosA`, `query_param:cantidadA`, `query_param:ciudadA`, `query_param:cpA`, `query_param:direccionA`, `query_param:dniA`, `query_param:emailA`, `query_param:errorMsgA`, `query_param:idA`, `query_param:loginA`, `query_param:modoA`, `query_param:nombreA`, `query_param:ntcA`, `query_param:passwordA`, `query_param:precioA`, `query_param:provinciaA`, `query_param:pwdA`, `query_param:rememberA`, `query_param:xmlfile`.

As maiores diferenças de presença (em pontos percentuais) são:

| Campo | % normal | % anômalo | Diferença anômalo − normal |
| --- | --- | --- | --- |
| `header:content-type` | 22,22% | 39,80% | +17.58 pp |
| `header:content-length` | 22,22% | 39,80% | +17.58 pp |
| `body.parameters` | 22,22% | 39,80% | +17.58 pp |
| `body` | 22,22% | 39,80% | +17.58 pp |
| `url.query` | 22,22% | 38,34% | +16.11 pp |
| `query.parameters` | 22,22% | 38,34% | +16.11 pp |
| `body_param:B1` | 13,89% | 26,57% | +12.69 pp |
| `query_param:B1` | 13,89% | 25,53% | +11.64 pp |
| `body_param:modo` | 11,11% | 21,28% | +10.17 pp |
| `query_param:modo` | 11,11% | 20,48% | +9.37 pp |
| `body_param:nombre` | 8,33% | 16,37% | +8.03 pp |
| `body_param:login` | 8,33% | 16,31% | +7.98 pp |
| `query_param:nombre` | 8,33% | 15,71% | +7.38 pp |
| `query_param:login` | 8,33% | 15,66% | +7.33 pp |
| `body_param:provincia` | 5,56% | 11,03% | +5.48 pp |

## Estrutura por método

### GET

| Dataset | Requisições | Com query | Com body | Body parametrizado | Média headers | Média params query/body |
| --- | --- | --- | --- | --- | --- | --- |
| Normal | 28000 | 28,57% | 0,00% | 0,00% | 10.0 | 1.5 / 0.0 |
| Anômalo | 15088 | 63,69% | 0,00% | 0,00% | 10.0 | 3.7096 / 0.0 |

### POST

| Dataset | Requisições | Com query | Com body | Body parametrizado | Média headers | Média params query/body |
| --- | --- | --- | --- | --- | --- | --- |
| Normal | 8000 | 0,00% | 100,00% | 100,00% | 12.0 | 0.0 / 5.25 |
| Anômalo | 9580 | 0,00% | 100,00% | 100,00% | 12.0 | 0.0 / 5.8395 |

### PUT

| Dataset | Requisições | Com query | Com body | Body parametrizado | Média headers | Média params query/body |
| --- | --- | --- | --- | --- | --- | --- |
| Normal | 0 | — | — | — | — | — |
| Anômalo | 397 | 0,00% | 100,00% | 100,00% | 12.0 | 0.0 / 5.5239 |

## Observações do parser

O arquivo normal não produziu ocorrências de parsing. No arquivo anômalo, **231 targets** continham uma representação de porta que não pôde ser convertida em número. Esses targets continuaram contabilizados, com método, URL original, path, query, headers e body preservados na análise; somente o componente numérico `url.port` ficou ausente.

## Observações metodológicas

- A comparação é estrutural entre o conjunto normal de treinamento e o conjunto anômalo de teste fornecidos; ela não demonstra, por si só, que uma diferença seja útil para classificação.
- As formas de valores no JSON são marcadores não exclusivos: um mesmo valor pode ser, por exemplo, textual, percent-encoded e conter bytes não ASCII.
- O parser usa `Content-Length` para ler corpos e Latin-1 para preservar a correspondência de um byte por caractere do corpus.
- Nenhuma requisição original foi modificada e nenhum conteúdo integral foi exportado.
