# Balanceador de carga com Q-Learning

Laboratório independente que executa em paralelo ao WAF existente. Ele reproduz a atividade proposta pelo Prof. Me. Mateus Valente: três servidores Docker com `1,00`, `0,25` e `0,05` CPU, um proxy Nginx e um agente Q-Learning tabular implementado sem bibliotecas de Machine Learning.

## Execução

Na raiz do projeto:

```powershell
docker compose --profile reforco up -d --build
```

- WAF e dashboard existentes: <http://localhost:8080/dashboard/>
- Proxy do laboratório RL: <http://localhost:8090/node1>
- Painel do balanceador: <http://localhost:8091/>

No painel, clique em **Iniciar treinamento**, aguarde os 500 episódios e depois execute **Round-Robin × Q-Learning**.

Treinamento, comparação e simulação usam o mesmo modelo de cargas e latências. Na comparação, diferenças pequenas são tratadas como equivalentes; o painel calcula o limite efetivo para a carga inicial e indica concorrências superiores como sobrecarga intencional, não como falha automática de uma das políticas.

Na **Etapa 3 — Simulação interativa de carga**, defina a carga inicial, a concorrência e escolha entre **Q-Table fixa** ou aprendizado **Contínuo**. Durante a execução, mova os controles e clique em **Aplicar novas cargas**. O painel mostra requisições HTTP reais simultâneas, CPU efetiva, requisições em voo, saturação, servidor escolhido, exploração/explotação, latência, recompensa e atualização de Q. Cada chegada acrescenta trabalho ao nó escolhido e a carga residual decai naturalmente com o tempo de processamento. A decisão combina o valor Q aprendido com telemetria instantânea e evita nós saturados quando existe alternativa saudável. Os dois modos usam uma cópia e nunca alteram a Q-Table principal.

O intervalo representa a cadência do tráfego: intervalos curtos podem acumular carga; intervalos longos dão tempo para os nós liberarem recursos. Essa diferença é parte do cenário, não uma aleatoriedade da interface.

Com o laboratório em execução, os mesmos passos também podem ser feitos pelo terminal:

```powershell
python balanceador_rl/agente.py --episodios 500 --seed 42
python balanceador_rl/simulador_trafego.py --requisicoes 60 --concorrencia 6
```

Para parar somente o laboratório de reforço:

```powershell
docker compose --profile reforco stop rl_agent rl_proxy rl_node1 rl_node2 rl_node3
```

## Testes sem iniciar os contêineres

```powershell
python -m unittest discover -s balanceador_rl/tests -v
```

Os testes verificam recompensa, ε-greedy, política por `argmax`, atualização seletiva de Bellman, cálculo da telemetria, penalidades operacionais e proteção contra saturação.

## Isolamento do WAF

O laboratório usa serviços, rede, dados e portas próprios. Não acessa nem modifica extractors, MLPs, pesos, thresholds, datasets ou histórico do WAF. Os JSON gerados durante treinamento e comparação ficam em `balanceador_rl/data/` e são ignorados pelo Git.

Leia [RELATORIO_APRENDIZAGEM_REFORCO.md](RELATORIO_APRENDIZAGEM_REFORCO.md) para a explicação completa da implementação.
