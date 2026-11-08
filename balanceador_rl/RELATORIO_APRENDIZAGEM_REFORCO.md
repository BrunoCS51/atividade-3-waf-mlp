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

Durante o treinamento, os estados são alternados para garantir observações nas três linhas da tabela.

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
3. enviar HTTP para `/node1`, `/node2` ou `/node3`;
4. medir o tempo com `time.perf_counter()`;
5. converter latência/timeout em recompensa;
6. identificar o próximo estado;
7. atualizar `Q(estado, ação)` com Bellman;
8. reduzir ε;
9. atualizar o painel e persistir o resultado ao final.

## 5. Comparação com Round-Robin

Depois do treinamento, o painel executa duas rajadas com a mesma quantidade e concorrência:

1. **Round-Robin:** distribui igualmente entre os três nós, sem observar capacidade ou resultado;
2. **Q-Learning:** usa a melhor ação aprendida para `carga_alta`, mantendo ε residual de 2%.

Para cada política são apresentados:

- quantidade enviada a cada nó;
- latência média das respostas concluídas;
- percentil 95 de latência;
- respostas abaixo de 100 ms;
- timeouts;
- erros de rede;
- tempo total da rajada.

O objetivo da comparação não é provar que Q-Learning sempre supera qualquer balanceador real. Ela mostra, neste ambiente didático assimétrico, que uma política adaptativa consegue aprender a evitar ações associadas a recompensas ruins.

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

## 13. Validação funcional executada

Em uma execução real de 500 episódios com seed 42, o agente apresentou:

- 55 ações de exploração e 445 de explotação;
- distribuição: node1 = 467, node2 = 17 e node3 = 16;
- 16 timeouts, todos absorvidos como experiências de recompensa negativa;
- política final `node1` nos três estados;
- ε final de aproximadamente `0.0245`.

As notas finais confirmaram a preferência aprendida. Para `carga_alta`, por exemplo, foram aproximadamente `133.10` para node1, `70.06` para node2 e `−14.11` para node3.

Na comparação de 60 requisições com concorrência 6:

| Resultado | Round-Robin | Q-Learning |
|---|---:|---:|
| Rotas node1/node2/node3 | 20 / 20 / 20 | 60 / 0 / 0 |
| Timeouts | 20 | 0 |
| Respostas abaixo de 100 ms | 20 | 60 |
| Latência média das respostas OK | 73,1 ms | 5,3 ms |
| P95 | 144,5 ms | 8,3 ms |
| Tempo total da rajada | 2,45 s | 0,07 s |

Os números dependem do computador, mas a execução comprovou o ciclo completo: infraestrutura real, exploração, recompensa, Bellman, persistência, política aprendida e avaliação comparativa. O WAF continuou respondendo em paralelo durante o teste.
