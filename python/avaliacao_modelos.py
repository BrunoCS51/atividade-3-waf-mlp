import argparse
import csv
import json  # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
import numpy as np

from mlp import MLP


THRESHOLD = 0.35

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

SEMENTE = 42


# ALTERADO PARA SELECAO AUTOMATICA DO MODELO
def carregar_conjuntos():
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

    X = X / LIMITES
    X = np.clip(X, 0.0, 1.0)

    # Mesma sequencia da divisao estratificada dos treinamentos.
    np.random.seed(SEMENTE)

    indices_normal = np.where(Y == 0)[0]
    indices_ataque = np.where(Y == 1)[0]

    np.random.shuffle(indices_normal)
    np.random.shuffle(indices_ataque)

    def dividir_classe(indices):
        n = len(indices)
        fim_treino = int(n * 0.70)
        fim_validacao = fim_treino + int(n * 0.15)

        treino = indices[:fim_treino]
        validacao = indices[fim_treino:fim_validacao]
        teste = indices[fim_validacao:]

        return treino, validacao, teste

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

    return {
        "validacao": (
            X[indices_validacao],
            Y[indices_validacao]
        ),
        "teste": (
            X[indices_teste],
            Y[indices_teste]
        )
    }


def divisao_segura(numerador, denominador):
    if denominador == 0:
        return 0.0

    return numerador / denominador


# ALTERADO PARA SELECAO AUTOMATICA DO MODELO
def obter_probabilidades(arquivo_pesos, X):
    mlp = MLP(input_size=9, hidden_size=10, output_size=1)
    mlp.load(arquivo_pesos)

    return np.array([
        mlp.forward(x)[0]
        for x in X
    ])


# ALTERADO PARA SELECAO AUTOMATICA DO MODELO
def calcular_metricas(probabilidades, Y, threshold):
    preditos = (probabilidades > threshold).astype(int)
    reais = Y.astype(int)

    tp = int(np.sum((reais == 1) & (preditos == 1)))
    tn = int(np.sum((reais == 0) & (preditos == 0)))
    fp = int(np.sum((reais == 0) & (preditos == 1)))
    fn = int(np.sum((reais == 1) & (preditos == 0)))

    acuracia = divisao_segura(tp + tn, tp + tn + fp + fn)
    precisao = divisao_segura(tp, tp + fp)
    recall = divisao_segura(tp, tp + fn)
    f1 = divisao_segura(
        2 * precisao * recall,
        precisao + recall
    )

    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "acuracia": acuracia,
        "precisao": precisao,
        "recall": recall,
        "f1": f1,
        "threshold": threshold
    }


def avaliar_modelo(arquivo_pesos, X, Y, threshold):
    # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
    probabilidades = obter_probabilidades(arquivo_pesos, X)
    return calcular_metricas(probabilidades, Y, threshold)


# ALTERADO PARA SELECAO AUTOMATICA DO MODELO
def salvar_resultados(conjunto, resultados):
    arquivo_saida = "avaliacao_modelos.json"

    try:
        with open(
            arquivo_saida,
            "r",
            encoding="utf-8"
        ) as arquivo:
            dados = json.load(arquivo)

        if not isinstance(dados, dict):
            dados = {}
    except (OSError, json.JSONDecodeError):
        dados = {}

    dados[conjunto] = resultados

    with open(
        arquivo_saida,
        "w",
        encoding="utf-8"
    ) as arquivo:
        json.dump(dados, arquivo, indent=4)


# ALTERADO PARA SELECAO AUTOMATICA DO MODELO
def imprimir_avaliacao(nome, metricas, threshold, conjunto):
    print()
    print("========================================")
    print(f"AVALIACAO {conjunto.upper()} - {nome}")
    print("========================================")
    print()
    print(f"Threshold: {threshold}")
    print()
    print("Matriz de Confusao:")
    print()
    print("                Pred. Normal    Pred. Ataque")
    print(
        "Real Normal     "
        f"{metricas['tn']:12d}    {metricas['fp']:12d}"
    )
    print(
        "Real Ataque     "
        f"{metricas['fn']:12d}    {metricas['tp']:12d}"
    )
    print()
    print(f"Acuracia: {metricas['acuracia']:.6f}")
    print(f"Precisao: {metricas['precisao']:.6f}")
    print(f"Recall:   {metricas['recall']:.6f}")
    print(f"F1:       {metricas['f1']:.6f}")
    print("========================================")


def imprimir_comparacao(bp, ag):
    print()
    print("========================================")
    print("COMPARACAO OBJETIVA")
    print("========================================")
    print(f"{'Metrica':<20}{'BP':>14}{'AG':>14}")

    for nome, chave in [
        ("Acuracia", "acuracia"),
        ("Precisao", "precisao"),
        ("Recall", "recall"),
        ("F1", "f1")
    ]:
        print(
            f"{nome:<20}"
            f"{bp[chave]:>14.6f}"
            f"{ag[chave]:>14.6f}"
        )

    print("========================================")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Avalia modelos usando explicitamente validacao ou teste."
        )
    )
    # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
    parser.add_argument(
        "--conjunto",
        choices=["validacao", "teste"],
        default="validacao",
        help="Conjunto usado na avaliacao (padrao: validacao)."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=THRESHOLD,
        help=(
            "Threshold fixo usado somente na validacao "
            "(padrao: 0.35)."
        )
    )
    argumentos = parser.parse_args()

    # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
    conjuntos = carregar_conjuntos()
    X, Y = conjuntos[argumentos.conjunto]

    if argumentos.conjunto == "validacao":
        resultados = {
            "bp": avaliar_modelo(
                "pesos_bp.json",
                X,
                Y,
                argumentos.threshold
            ),
            "ag": avaliar_modelo(
                "pesos_ag.json",
                X,
                Y,
                argumentos.threshold
            )
        }

        imprimir_avaliacao(
            "BACKPROPAGATION",
            resultados["bp"],
            argumentos.threshold,
            argumentos.conjunto
        )
        imprimir_avaliacao(
            "ALGORITMO GENETICO",
            resultados["ag"],
            argumentos.threshold,
            argumentos.conjunto
        )
        imprimir_comparacao(
            resultados["bp"],
            resultados["ag"]
        )
    else:
        # O teste usa somente o modelo e threshold ja congelados.
        with open(
            "modelo_selecionado.json",
            "r",
            encoding="utf-8"
        ) as arquivo:
            selecao = json.load(arquivo)

        modelo = selecao["modelo"]
        threshold = float(selecao["threshold"])
        metricas = avaliar_modelo(
            "pesos.json",
            X,
            Y,
            threshold
        )
        resultados = {modelo: metricas}

        imprimir_avaliacao(
            modelo.upper(),
            metricas,
            threshold,
            argumentos.conjunto
        )

    salvar_resultados(argumentos.conjunto, resultados)


if __name__ == "__main__":
    main()
