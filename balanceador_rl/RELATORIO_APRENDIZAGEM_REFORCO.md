# Relatório — Balanceador de Carga com Aprendizado por Reforço

- **Aluno 1:** Bruno Sousa de Castro — **RA:** 5132956
- **Aluno 2:** Dener Reis Menezes — **RA:** 5170343
**Professor:** Prof. Me. Mateus Valente

## 1. Objetivo

Foi desenvolvido um laboratório de balanceamento de carga autônomo com Q-Learning tabular. O objetivo do agente é aprender qual dos três servidores Docker deve receber uma requisição em cada estado de carga. O aprendizado não usa rótulos prontos: o próprio ambiente devolve uma recompensa a partir da latência HTTP observada.

O laboratório foi integrado ao repositório do WAF, mas permanece operacionalmente isolado. O WAF continua na porta `8080`; o proxy do experimento de reforço usa `8090`; o painel e a API do agente usam `8091`.

## 2. Arquitetura

```text
Navegador
   │
   ├── localhost:8080 ── WAF + MLP existente (inalterado)
   │
   └── localhost:8091 ── Painel/API do agente Q-Learning
                              │
                              ▼
                        rl_proxy:8080
                         ┌────┼────┐
                         ▼    ▼    ▼
                    rl_node1 node2 node3
                    1,00 CPU 0,25  0,05
```

Os serviços RL usam a rede Docker exclusiva `rl_net` e o profile `reforco`. Isso evita conflito com o Nginx, o Flask, o PHP e as portas do projeto WAF.

## 3. Formulação como aprendizado por reforço

### Estados

O espaço de estados é discreto:

- `carga_baixa`;
- `carga_media`;
- `carga_alta`.

Durante o treinamento, os estados são alternados para garantir observações nas três linhas da tabela. Cada estado representa cargas-base de 20%, 50% e 70%, respectivamente. O treinamento usa o mesmo modelo de capacidade, concorrência e atraso aplicado posteriormente na comparação e na simulação.

### Ações

O espaço de ações também é discreto:

- `node1`: servidor com 1,00 CPU;
- `node2`: servidor com 0,25 CPU;
- `node3`: servidor com 0,05 CPU.

Escolher uma ação significa enviar uma requisição HTTP real pelo proxy Nginx para aquele nó.

### Q-Table

A função ação-valor é representada por um dicionário Python 3 × 3:

```python
Q_TABLE[estado][servidor]
```

Todas as nove células começam em `0.0`. Um valor alto significa que, historicamente, aquela ação produziu melhor retorno naquele estado.

### Política ε-greedy

Antes de agir, o agente sorteia um número entre 0 e 1:

- se o número for menor que ε, explora um servidor aleatório;
- caso contrário, explota o conhecimento e escolhe `argmax Q(s,a)`;
- empates são resolvidos aleatoriamente, evitando preferência artificial pelo primeiro item.

Conforme o enunciado do kit do aluno, ε começa em `0.30`, é multiplicado por `0.995` após cada episódio e não fica abaixo de `0.02`. Assim, o agente explora bastante no começo e conserva 2% de exploração residual.

### Recompensa

Depois da resposta HTTP, a latência é transformada em recompensa:

| Observação | Recompensa |
|---|---:|
| latência `< 100 ms` | `+20` |
| latência `100 ms` até `< 250 ms` | `+2` |
| latência `≥ 250 ms` | `−15` |
| timeout em 500 ms | `−100` |

A recompensa positiva reforça servidores rápidos. Lentidão e timeout reduzem o valor da ação.

### Equação de Bellman

Depois de agir, apenas a célula realmente executada é atualizada:

```text
Q(s,a) ← Q(s,a) + α × [R + γ × max Q(s′,a′) − Q(s,a)]
```

Foram mantidos os parâmetros didáticos:

- `α = 0.25`: controla quanto a nova experiência altera a estimativa;
- `γ = 0.85`: incorpora o melhor valor esperado no próximo estado;
- `R`: recompensa da latência medida;
- `max Q(s′,a′)`: melhor valor conhecido no estado seguinte.

O termo entre colchetes é o erro de diferença temporal, ou erro TD.

## 4. Ciclo de um episódio

Cada episódio segue esta sequência:

1. determinar o estado atual;
2. selecionar uma ação com ε-greedy;
3. calcular a telemetria correspondente ao estado e enviar HTTP real para `/simulation/node1`, `/simulation/node2` ou `/simulation/node3`;
4. medir o tempo com `time.perf_counter()`;
5. converter latência/timeout em recompensa;
6. identificar o próximo estado;
7. atualizar `Q(estado, ação)` com Bellman;
8. reduzir ε;
9. atualizar o painel e persistir o resultado ao final.

## 5. Comparação com Round-Robin

Depois do treinamento, o painel executa duas rajadas com a mesma quantidade e concorrência:

1. **Round-Robin:** distribui igualmente entre os três nós, sem observar capacidade ou resultado;
2. **Q-Learning:** mantém ε residual de 2% e combina a Q-Table com CPU e concorrência observadas em cada janela da rajada.

As duas políticas usam os mesmos três nós, as mesmas rotas, a mesma quantidade de requisições e a mesma concorrência. A comparação foi fixada explicitamente em `carga_media`, com carga inicial equivalente de 50% nos três nós; assim, a linha consultada na Q-Table corresponde ao estado informado no resultado e a concorrência padrão 6 representa o limite efetivo desse cenário.

O limite nominal conjunto continua sendo 11 requisições simultâneas (`8 + 2 + 1`), mas o painel também calcula o limite efetivo sob a carga inicial; em 50%, ele é 6. Quando a concorrência supera esse valor, a execução é identificada como sobrecarga intencional. Nesse cenário, todos os servidores podem saturar e não existe obrigação metodológica de o Q-Learning superar o Round-Robin. Diferenças menores que 2% dos timeouts e 5% da latência média são apresentadas como resultados equivalentes, evitando declarar vencedor por ruído de medição.

Para cada política são apresentados:

- quantidade enviada a cada nó;
- latência média das respostas concluídas;
- percentil 95 de latência;
- respostas abaixo de 100 ms;
- timeouts;
- erros de rede;
- tempo total da rajada.

O objetivo da comparação não é provar que Q-Learning sempre supera qualquer balanceador real. Ela mostra, no ambiente assimétrico definido pela atividade, como uma política adaptativa pode aprender a evitar servidores de baixa capacidade e reagir à condição operacional instantânea.

## 6. Visualização

O painel em `http://localhost:8091` oferece:

- estado dos três contêineres;
- progresso percentual e tempo estimado;
- ε atual;
- curva de recompensa, latência e exploração;
- Q-Table completa;
- política aprendida para cada estado;
- contagem de timeouts;
- comparação Round-Robin × Q-Learning;
- limpeza controlada do aprendizado.

Os dados são obtidos da API e não são valores inventados no HTML.

## 7. Persistência e reprodutibilidade

A seed padrão é `42`, utilizada nas decisões aleatórias do agente. A Q-Table, o último treinamento e a última comparação são persistidos em `balanceador_rl/data/`. Esses arquivos são dados de execução e estão ignorados pelo Git; uma nova máquina começa com a Q-Table zerada.

O painel somente permite a comparação depois de um treinamento concluído. Também existe uma verificação prévia da infraestrutura para evitar um “treinamento” silencioso sem os contêineres.

## 8. Testes implementados

Os testes unitários confirmam:

- os quatro intervalos da função de recompensa, inclusive fronteiras de 100 e 250 ms;
- o ramo de exploração;
- o ramo de explotação;
- a escolha da maior nota;
- o cálculo numérico da Equação de Bellman;
- que somente a célula `Q(s,a)` executada é modificada;
- a política independente para cada estado.

## 9. Como demonstrar ao professor

```powershell
docker compose --profile reforco up -d --build
```

1. abrir `http://localhost:8091`;
2. mostrar os três nós online e suas latências diferentes;
3. iniciar 500 episódios;
4. explicar a queda de ε e a diferença entre exploração e explotação;
5. acompanhar as nove notas da Q-Table;
6. executar a comparação de 60 requisições com concorrência 6;
7. comparar rotas, latência e timeouts;
8. abrir o WAF em `http://localhost:8080/dashboard/` para demonstrar que ambos funcionam em paralelo.

## 10. Limitações

- Os estados são uma discretização didática e não uma medição contínua de CPU.
- Os atrasos configurados no proxy tornam as capacidades distinguíveis e reproduzíveis.
- A política aprendida otimiza a recompensa definida; mudar os limites muda o comportamento desejado.
- O experimento compara com Round-Robin simples, não com algoritmos industriais avançados.
- O aprendizado ocorre online e pode variar levemente por latência do host, apesar da seed fixa.

## 11. Arquivos principais

- `qlearning.py`: ε-greedy, recompensa, Bellman, Q-Table e política;
- `app.py`: treinamento, chamadas HTTP, persistência, comparação e API;
- `agente.py`: comando de terminal para iniciar e acompanhar o treinamento;
- `simulador_trafego.py`: comando de terminal para executar a comparação;
- `nginx/default.conf`: roteamento para os três nós;
- `static/`: painel visual;
- `tests/test_qlearning.py`: testes do algoritmo;
- `docker-compose.yml` na raiz: profile isolado `reforco`.

## 12. Material de referência

A implementação segue o enunciado e o kit disponibilizados em [“Ensine um Balanceador de Carga a rotear tráfego entre contêineres Docker”](https://machine-learning.mateusvalente.dev/pages/aprendizagem-por-reforco/balanceador.html), do Prof. Me. Mateus Valente.

## 13. Validação funcional

A configuração do ambiente possui uma versão própria. Resultados persistidos pela configuração antiga, que tinha capacidades muito diferentes, são descartados automaticamente; por isso é necessário executar um novo treinamento após esta atualização. Isso impede que uma política aprendida no cenário anterior contamine a demonstração atual.

Foram validados por testes automatizados: recompensa original nas quatro faixas, exploração e explotação, Bellman atualizando somente a ação executada, cálculo de CPU por capacidade e concorrência, detecção de saturação, penalidades operacionais e desvio de um nó saturado mesmo quando ele possui o maior Q. A validação integrada usa requisições HTTP reais e deve ser repetida no computador da apresentação, pois latências e números finais dependem do host.

## 14. Simulação interativa e adaptação online

Foi acrescentada uma terceira etapa para demonstrar adaptação depois do treinamento. O usuário define cargas de 0% a 100% para node1, node2 e node3 e pode substituí-las enquanto as requisições estão sendo processadas.

### Como a carga afeta o ambiente real

O agente combina a carga-base definida pelo usuário, a capacidade do nó e a quantidade de requisições em voo. O resultado é uma utilização de CPU efetiva. Em seguida envia uma requisição HTTP real para uma rota específica do Nginx. A resposta continua sendo produzida pelo contêiner `traefik/whoami`; o parâmetro `wait` representa o trabalho pendente naquele servidor.

| Nó | CPU | Latência-base | Fator da CPU | Limite simultâneo |
|---|---:|---:|---:|---:|
| node1 | `1,00` | `8 ms` | `0,72` | `8` |
| node2 | `0,25` | `35 ms` | `0,78` | `2` |
| node3 | `0,05` | `90 ms` | `0,84` | `1` |

A CPU efetiva é `carga-base + requisições_ativas × (10 / capacidade)`, limitada a 100%. O atraso inclui latência-base, parcela proporcional à CPU, crescimento quadrático da fila e uma penalidade quando a CPU chega a 90% ou o limite simultâneo do nó é alcançado. Com as capacidades do enunciado, node2 e principalmente node3 saturam muito antes do node1.

### Estado observado

O estado é calculado pela média das três utilizações efetivas de CPU:

- média abaixo de 34%: `carga_baixa`;
- média de 34% até abaixo de 67%: `carga_media`;
- média a partir de 67%: `carga_alta`.

Quando uma requisição chega, o nó escolhido recebe `1,5 / √capacidade` ponto de trabalho residual. A raiz mantém o impacto maior nos nós menores sem provocar saltos artificiais de 30 pontos no node3. Paralelamente, todos os servidores liberam carga continuamente à taxa de 6 pontos percentuais por segundo transcorrido. As requisições em voo são contabilizadas separadamente e desaparecem quando a resposta chega. Com isso, receber tráfego aumenta a pressão, mas processar e aguardar reduz a carga naturalmente; não existe saldo positivo obrigatório a cada conclusão. Uma alteração manual substitui imediatamente a carga-base e reinicia a referência temporal; a próxima decisão já observa a nova telemetria.

### Decisão e recompensa operacional

O método original `select_action` permanece como a implementação pura de ε-greedy usada no treinamento exigido pelo professor. Na execução interativa foi acrescentada uma camada operacional: nós saturados são retirados temporariamente das alternativas quando existe algum nó saudável, e o valor Q é ajustado por CPU e número de requisições ativas. Explorações também escolhem somente entre alternativas saudáveis, salvo quando todas estão saturadas.

Para comparar grandezas compatíveis, os valores Q do estado atual são normalizados entre 0 e 10 sem alterar sua ordem. A nota operacional é:

```text
nota = Q_normalizado − 0,20 × CPU% − 3 × requisições_ativas − 40 (se saturado)
```

Na explotação vence a maior nota entre os nós saudáveis. Na exploração continua existindo escolha aleatória, conforme o requisito original, porém limitada a nós saudáveis quando possível.

A recompensa original por latência continua sendo o componente principal (`+20`, `+2`, `−15` ou `−100`). Na sessão interativa são subtraídas penalidades transparentes por CPU acima de 70%, concorrência e saturação. O histórico mostra a recompensa total, e o detalhamento permite explicar cada componente. Bellman continua atualizando somente `Q(s,a)` da ação executada.

```text
R_total = R_latência
          − 0,25 × max(0, CPU% − 70)
          − 1,5 × max(0, requisições_ativas − 1)
          − 25 (se saturado)
```

### Aprendizado preservado

No início da simulação, a Q-Table treinada é sempre copiada. No modo **Q-Table fixa**, essa cópia é somente consultada e Bellman não é executado. No modo **Contínuo**, Bellman atualiza apenas a cópia da sessão. Assim, os dois modos preservam integralmente a Q-Table principal usada na comparação oficial.

O usuário também escolhe o ε da sessão. Um ε maior facilita a descoberta de alternativas quando o servidor anteriormente preferido passa a ficar sobrecarregado.

### Informações apresentadas

- gráfico temporal da CPU efetiva dos três nós;
- CPU, requisições ativas, saturação, última latência e escolhas por nó;
- última decisão e motivo: exploração ou explotação;
- estado atual e próximo estado;
- recompensa recebida;
- valor Q antes e depois de Bellman;
- timeout e erros de rede;
- histórico das 30 decisões mais recentes;
- progresso e possibilidade de interrupção.

### Como demonstrar a adaptação

Inicie uma sessão com concorrência 6 e cargas moderadas. Durante a execução, eleve a carga de um servidor para 95% e aplique. O cartão fica marcado como **Saturado**, e as próximas decisões priorizam alternativas saudáveis. Depois reduza sua carga: o nó volta a participar conforme a Q-Table e a telemetria. A Q-Table usada nessa adaptação é uma cópia de sessão; ao final, a tabela treinada principal permanece inalterada.

Na validação integrada final foram executados 500 episódios com a configuração original `1,00/0,25/0,05` e com o modelo unificado de carga. A política final escolheu node1 nos três estados. As explorações ainda observaram node2 e node3, mas suas recompensas inferiores reduziram seus valores relativos na Q-Table. Não houve erro de rede nem timeout nessa execução; as respostas lentas foram classificadas nas faixas negativas normais da recompensa.

Na comparação de 60 requisições com concorrência 6, exatamente no limite efetivo do cenário médio, o Round-Robin distribuiu `20/20/20` e o Q-Learning `40/10/10`. Ambos terminaram sem timeout. Em três repetições com seeds e ordens distintas, as latências médias permaneceram próximas de 269 ms para Round-Robin e 258 ms para Q-Learning; o P95 ficou próximo de 498 ms e 358 ms, respectivamente. Como a diferença média foi de aproximadamente 4%, abaixo da margem declarada de 5%, o painel classificou conservadoramente os resultados como equivalentes, embora exponha a melhora de cauda.

Em uma segunda comparação, concorrência 20 — acima tanto do limite efetivo 6 quanto do nominal 11 — produziu 54 timeouts em cada política. As latências médias diferiram menos de 1%, e o painel classificou corretamente os resultados como equivalentes e marcou a sobrecarga intencional. Esse caso confirma que o sistema não força uma vitória do agente.

Por fim, sessões de 30 requisições foram executadas com intervalos de 50 e 250 ms. Com 50 ms, node1 acumulou carga por receber a maior parte do tráfego; com 250 ms, os nós tiveram tempo para se recuperar entre chegadas. Depois da suavização do impacto residual, node3 variou apenas alguns pontos de carga-base, embora sua CPU efetiva ainda possa atingir saturação durante uma requisição — comportamento esperado para apenas 0,05 CPU. O modo fixo fez zero atualizações, o contínuo fez 30, e a Q-Table principal permaneceu byte a byte idêntica.
