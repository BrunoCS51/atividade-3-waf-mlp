import csv
import time  # ALTERADO PARA METRICA COMPUTACIONAL
import numpy as np

from mlp import MLP
from ga import (
    criar_populacao,
    fitness,
    selecao,
    crossover,
    mutacao
)
# ALTERADO PARA DIAGNOSTICO
from diagnostico_ag import DiagnosticoAG


# ========== CONFIGURACAO DA REDE ==============

LIMITES = np.array([
    1,
    200,
    1000,
    25,
    40,
    1,
    1,
    1,
    800
], dtype=float)

rede = [9, 10, 1]

semente = 42


# ========== CONFIGURACAO DO AG ==============

npop = 100
geracoes = 100

tipo_selecao = 1       # 1 = Torneio | 2 = Roleta
tipo_crossover = 2     # 1 = Um ponto | 2 = SBX
tipo_mutacao = 1       # 1 = Uniforme | 2 = Gaussiana | 3 = Polinomial

tamanho_torneio = 3

taxa_crossover = 0.8
taxa_mutacao = 0.02

eta_sbx = 1
eta_mutacao = 20

rmin = -5
rmax = 5


# ========== LEITURA DOS DADOS ==============

X = []
Y = []

with open(
    "requisicoes.csv",
    "r",
    encoding="utf-8"
) as arquivo:

    leitor = csv.reader(arquivo)

    for linha in leitor:

        if not linha:
            continue

        valores = [
            float(valor)
            for valor in linha
        ]

        X.append(valores[:9])
        Y.append(valores[9])


X = np.array(X, dtype=float)
Y = np.array(Y, dtype=float)


# ========== NORMALIZACAO ==============

X = X / LIMITES

X = np.clip(
    X,
    0.0,
    1.0
)


# ========== SEPARACAO ESTRATIFICADA ==============

np.random.seed(semente)

indices_normal = np.where(Y == 0)[0]
indices_ataque = np.where(Y == 1)[0]

np.random.shuffle(indices_normal)
np.random.shuffle(indices_ataque)


def dividir_classe(indices):

    n = len(indices)

    fim_treino = int(n * 0.70)
    fim_validacao = (
        fim_treino
        + int(n * 0.15)
    )

    treino = indices[:fim_treino]

    validacao = indices[
        fim_treino:fim_validacao
    ]

    teste = indices[
        fim_validacao:
    ]

    return (
        treino,
        validacao,
        teste
    )


normal_treino, normal_validacao, normal_teste = (
    dividir_classe(indices_normal)
)

ataque_treino, ataque_validacao, ataque_teste = (
    dividir_classe(indices_ataque)
)


indices_treino = np.concatenate([
    normal_treino,
    ataque_treino
])

indices_validacao = np.concatenate([
    normal_validacao,
    ataque_validacao
])

indices_teste = np.concatenate([
    normal_teste,
    ataque_teste
])


np.random.shuffle(indices_treino)
np.random.shuffle(indices_validacao)
np.random.shuffle(indices_teste)


X_treino = X[indices_treino]
Y_treino = Y[indices_treino]

X_validacao = X[indices_validacao]
Y_validacao = Y[indices_validacao]

X_teste = X[indices_teste]
Y_teste = Y[indices_teste]


# ========== REDE ==============

mlp = MLP(
    input_size=rede[0],
    hidden_size=rede[1],
    output_size=rede[2]
)

n_genes = len(
    mlp.get_cromossomo()
)


# ========== INFORMACOES ==============

print()
print("========================================")
print("       ALGORITMO GENETICO")
print("========================================")

print(f"Arquitetura: {rede}")
print(f"Numero de genes: {n_genes}")

print()

print(f"Treino:    {len(X_treino)}")
print(f"Validacao: {len(X_validacao)}")
print(f"Teste:     {len(X_teste)}")

print()

print(f"Populacao: {npop}")
print(f"Geracoes: {geracoes}")

print(f"Selecao: {tipo_selecao}")
print(f"Crossover: {tipo_crossover}")
print(f"Mutacao: {tipo_mutacao}")

print(f"Intervalo dos pesos: [{rmin}, {rmax}]")

print()


# ========== POPULACAO INICIAL ==============

populacao = criar_populacao(
    npop,
    n_genes,
    rmin,
    rmax
)


# ========== TREINAMENTO ==============

melhor_individuo = None
melhor_fitness = np.inf

# ALTERADO PARA DIAGNOSTICO
diagnostico = DiagnosticoAG(
    rmin=rmin,
    rmax=rmax
)

# ALTERADO PARA METRICA COMPUTACIONAL
inicio_treinamento = time.perf_counter()
inicio_cpu_treinamento = time.process_time()


for geracao in range(geracoes):

    # ALTERADO PARA METRICA COMPUTACIONAL
    inicio_geracao = time.perf_counter()
    inicio_cpu_geracao = time.process_time()

    custos = np.zeros(npop)


    # ---------- FITNESS ----------

    for i in range(npop):

        custos[i] = fitness(
            populacao[i],
            mlp,
            X_treino,
            Y_treino
        )


    # ---------- MELHOR INDIVIDUO ----------

    indice_melhor = np.argmin(
        custos
    )

    fitness_geracao = custos[
        indice_melhor
    ]

    if fitness_geracao < melhor_fitness:

        melhor_fitness = (
            fitness_geracao
        )

        melhor_individuo = (
            populacao[
                indice_melhor
            ].copy()
        )


    # ---------- VALIDACAO ----------

    mlp.set_cromossomo(
        melhor_individuo
    )

    erro_validacao = 0.0

    for x, yd in zip(
        X_validacao,
        Y_validacao
    ):

        y = mlp.forward(x)[0]

        erro_validacao += (
            yd - y
        ) ** 2


    mse_validacao = (
        erro_validacao
        / len(X_validacao)
    )

    # ALTERADO PARA DIAGNOSTICO
    diagnostico.registrar_geracao(
        geracao + 1,
        melhor_fitness,
        mse_validacao,
        populacao,
        melhor_individuo
    )


    print(
        f"Geracao {geracao + 1:3d}/{geracoes} | "
        f"MSE Treino: {melhor_fitness:.8f} | "
        f"MSE Validacao: {mse_validacao:.8f}"
    )


    # ---------- SELECAO ----------

    pais = selecao(
        populacao,
        custos,
        tipo_selecao,
        tamanho_torneio
    )


    # ---------- CROSSOVER + MUTACAO ----------

    nova_populacao = []

    for i in range(
        0,
        npop,
        2
    ):

        pai1 = pais[i]

        pai2 = pais[
            (i + 1) % npop
        ]

        filho1, filho2 = crossover(
            pai1,
            pai2,
            tipo_crossover,
            taxa_crossover,
            eta_sbx
        )


        filho1 = mutacao(
            filho1,
            tipo_mutacao,
            taxa_mutacao,
            rmin,
            rmax,
            eta_m=eta_mutacao
        )

        filho2 = mutacao(
            filho2,
            tipo_mutacao,
            taxa_mutacao,
            rmin,
            rmax,
            eta_m=eta_mutacao
        )


        nova_populacao.append(
            filho1
        )

        if len(nova_populacao) < npop:

            nova_populacao.append(
                filho2
            )


    populacao = np.array(
        nova_populacao
    )


    # ---------- ELITISMO ----------

    posicao = np.random.randint(
        npop
    )

    populacao[
        posicao
    ] = melhor_individuo.copy()

    # ALTERADO PARA METRICA COMPUTACIONAL
    diagnostico.registrar_tempo_geracao(
        time.perf_counter() - inicio_geracao,
        time.process_time() - inicio_cpu_geracao
    )


# ALTERADO PARA METRICA COMPUTACIONAL
tempo_total = time.perf_counter() - inicio_treinamento
tempo_cpu_total = time.process_time() - inicio_cpu_treinamento
diagnostico.registrar_custo_computacional(
    tempo_total,
    tempo_cpu_total
)


# ========== SALVAR MELHOR REDE ==============

mlp.set_cromossomo(
    melhor_individuo
)

mlp.save(
    "pesos_ag.json"
)

# ALTERADO PARA DIAGNOSTICO
diagnostico.salvar_csv()
diagnostico.imprimir_resumo()


print()
print("========================================")
print("       TREINAMENTO FINALIZADO")
print("========================================")

print(
    f"Melhor MSE Treino: "
    f"{melhor_fitness:.8f}"
)

print(
    f"MSE Validacao: "
    f"{mse_validacao:.8f}"
)

print(
    "Modelo salvo em pesos_ag.json"
)
