# Balanceador de carga com Q-Learning

Laboratório independente que executa em paralelo ao WAF existente. Ele reproduz a atividade proposta pelo Prof. Me. Mateus Valente: três servidores Docker com capacidades diferentes, um proxy Nginx e um agente Q-Learning tabular implementado sem bibliotecas de Machine Learning.

## Execução

Na raiz do projeto:

```powershell
docker compose --profile reforco up -d --build
```

- WAF e dashboard existentes: <http://localhost:8080/dashboard/>
- Proxy do laboratório RL: <http://localhost:8090/node1>
- Painel do balanceador: <http://localhost:8091/>

No painel, clique em **Iniciar treinamento**, aguarde os 500 episódios e depois execute **Round-Robin × Q-Learning**.

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

Os testes verificam a função de recompensa, exploração e explotação ε-greedy, política por `argmax` e atualização seletiva da Q-Table pela Equação de Bellman.

## Isolamento do WAF

O laboratório usa serviços, rede, dados e portas próprios. Não acessa nem modifica extractors, MLPs, pesos, thresholds, datasets ou histórico do WAF. Os JSON gerados durante treinamento e comparação ficam em `balanceador_rl/data/` e são ignorados pelo Git.

Leia [RELATORIO_APRENDIZAGEM_REFORCO.md](RELATORIO_APRENDIZAGEM_REFORCO.md) para a explicação completa da implementação.
