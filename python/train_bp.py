import csv
import time  # ALTERADO PARA METRICA COMPUTACIONAL
import numpy as np

from mlp import MLP
# ALTERADO PARA DIAGNOSTICO
from diagnostico_bp import DiagnosticoBP


# ========== CONFIGURACAO ==============

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

taxa = 0.01
epocas = 100

# Semente fixa para BP e AG utilizarem
# exatamente a mesma divisao dos dados
semente = 42


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

        valores = [float(valor) for valor in linha]

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
    fim_validacao = fim_treino + int(n * 0.15)

    treino = indices[:fim_treino]

    validacao = indices[
        fim_treino:fim_validacao
    ]

    teste = indices[fim_validacao:]

    return treino, validacao, teste


normal_treino, normal_validacao, normal_teste = (
    dividir_classe(indices_normal)
)

ataque_treino, ataque_validacao, ataque_teste = (
    dividir_classe(indices_ataque)
)


# Junta as duas classes

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


# Embaralha os conjuntos

np.random.shuffle(indices_treino)
np.random.shuffle(indices_validacao)
np.random.shuffle(indices_teste)


# Cria os conjuntos

X_treino = X[indices_treino]
Y_treino = Y[indices_treino]

X_validacao = X[indices_validacao]
Y_validacao = Y[indices_validacao]

X_teste = X[indices_teste]
Y_teste = Y[indices_teste]


# ========== INFORMACOES DOS DADOS ==============

print()
print("========================================")
print("       DIVISAO DO DATASET")
print("========================================")

print(f"Total:      {len(X)}")
print(f"Treino:     {len(X_treino)}")
print(f"Validacao:  {len(X_validacao)}")
print(f"Teste:      {len(X_teste)}")

print()

print(
    "Ataques no treino:",
    int(np.sum(Y_treino))
)

print(
    "Ataques na validacao:",
    int(np.sum(Y_validacao))
)

print(
    "Ataques no teste:",
    int(np.sum(Y_teste))
)


# ========== REDE NEURAL ==============

mlp = MLP(
    input_size=rede[0],
    hidden_size=rede[1],
    output_size=rede[2]
)


# ========== TREINAMENTO ==============

print()
print("========================================")
print("       TREINAMENTO BACKPROPAGATION")
print("========================================")

print(f"Arquitetura: {rede}")
print(f"Taxa: {taxa}")
print(f"Epocas: {epocas}")

print()


# ALTERADO PARA DIAGNOSTICO
diagnostico = DiagnosticoBP()

# ALTERADO PARA METRICA COMPUTACIONAL
inicio_treinamento = time.perf_counter()
inicio_cpu_treinamento = time.process_time()


for epoca in range(epocas):

    # ALTERADO PARA METRICA COMPUTACIONAL
    inicio_epoca = time.perf_counter()
    inicio_cpu_epoca = time.process_time()

    erro_treino = 0.0

    # ALTERADO PARA DIAGNOSTICO
    diagnostico.iniciar_epoca(rede[1])

    # Embaralha apenas os dados de treinamento
    indices = np.random.permutation(
        len(X_treino)
    )

    for indice in indices:

        x = X_treino[indice]

        yd = np.array([
            Y_treino[indice]
        ])

        mse = mlp.backward(
            x,
            yd,
            taxa
        )

        erro_treino += mse

        # ALTERADO PARA DIAGNOSTICO
        diagnostico.registrar_amostra(
            mlp.ultimos_delta_w,
            mlp.ultimas_ativacoes_ocultas
        )


    mse_treino = (
        erro_treino / len(X_treino)
    )


    # ========== VALIDACAO ==============

    erro_validacao = 0.0

    for x, yd in zip(
        X_validacao,
        Y_validacao
    ):

        saida = mlp.forward(x)[0]

        erro_validacao += (
            yd - saida
        ) ** 2


    mse_validacao = (
        erro_validacao
        / len(X_validacao)
    )

    # ALTERADO PARA METRICA COMPUTACIONAL
    tempo_epoca = time.perf_counter() - inicio_epoca
    tempo_cpu_epoca = time.process_time() - inicio_cpu_epoca

    # ALTERADO PARA DIAGNOSTICO
    diagnostico.registrar_epoca(
        epoca + 1,
        mse_treino,
        mse_validacao,
        mlp,
        tempo_epoca,
        tempo_cpu_epoca
    )


    print(
        f"Epoca {epoca + 1:3d}/{epocas} | "
        f"MSE Treino: {mse_treino:.8f} | "
        f"MSE Validacao: {mse_validacao:.8f}"
    )


# ALTERADO PARA METRICA COMPUTACIONAL
tempo_total = time.perf_counter() - inicio_treinamento
tempo_cpu_total = time.process_time() - inicio_cpu_treinamento
diagnostico.registrar_custo_computacional(
    tempo_total,
    tempo_cpu_total
)


# ========== SALVAR MODELO ==============

mlp.save(
    "pesos_bp.json"
)

# ALTERADO PARA DIAGNOSTICO
diagnostico.salvar_csv()
diagnostico.imprimir_resumo()


print()
print("========================================")
print("       TREINAMENTO FINALIZADO")
print("========================================")

print(
    f"MSE Treino final: "
    f"{mse_treino:.8f}"
)

print(
    f"MSE Validacao final: "
    f"{mse_validacao:.8f}"
)

print(
    "Modelo salvo em pesos_bp.json"
)
