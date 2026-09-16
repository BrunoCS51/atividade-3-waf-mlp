import argparse
import csv
from datetime import datetime
import json
import os
import shutil

from avaliacao_modelos import (
    calcular_metricas,
    carregar_conjuntos,
    obter_probabilidades,
    salvar_resultados
)


# Parametros configuraveis deste experimento.
# Os pesos 10 e 1 nao sao valores universais de seguranca.
ALPHA_FN = 10.0
BETA_FP = 1.0

THRESHOLD_MINIMO = 0.05
THRESHOLD_MAXIMO = 0.95
PASSO_THRESHOLD = 0.01


def custo_seguranca(metricas, alpha_fn, beta_fp):
    # Formula exata: C = alpha_fn * FN + beta_fp * FP.
    return (
        alpha_fn * metricas["fn"]
        + beta_fp * metricas["fp"]
    )


def selecionar_threshold(
    probabilidades,
    Y_validacao,
    threshold_minimo,
    threshold_maximo,
    passo,
    alpha_fn,
    beta_fp
):
    melhor = None
    melhor_chave = None
    threshold = threshold_minimo

    while threshold <= threshold_maximo + 1e-12:
        threshold = float(round(threshold, 10))
        metricas = calcular_metricas(
            probabilidades,
            Y_validacao,
            threshold
        )
        metricas["custo_seguranca"] = custo_seguranca(
            metricas,
            alpha_fn,
            beta_fp
        )

        # Desempate deterministico dentro do mesmo modelo.
        chave = (
            metricas["custo_seguranca"],
            metricas["fn"],
            metricas["fp"],
            -metricas["f1"],
            -metricas["precisao"],
            -metricas["recall"],
            -metricas["acuracia"],
            threshold
        )

        if melhor_chave is None or chave < melhor_chave:
            melhor_chave = chave
            melhor = metricas

        threshold += passo

    return melhor


def carregar_tempo_treinamento(modelo):
    arquivo_csv = f"diagnostico_{modelo}.csv"
    coluna = (
        "tempo_parede_epoca_segundos"
        if modelo == "bp"
        else "tempo_parede_geracao_segundos"
    )

    try:
        with open(
            arquivo_csv,
            "r",
            encoding="utf-8"
        ) as arquivo:
            linhas = list(csv.DictReader(arquivo))

        if not linhas or coluna not in linhas[0]:
            return None

        return sum(float(linha[coluna]) for linha in linhas)
    except (OSError, ValueError, TypeError):
        return None


def comparar_candidatos(bp, ag):
    criterios = [
        ("custo_seguranca", "menor", (
            "menor custo de seguranca na validacao"
        )),
        ("fn", "menor", (
            "mesmo custo de seguranca e menor numero de falsos negativos"
        )),
        ("fp", "menor", (
            "empate nos criterios anteriores e menor numero de falsos positivos"
        )),
        ("f1", "maior", (
            "empate nos criterios anteriores e maior F1"
        )),
        ("precisao", "maior", (
            "empate nos criterios anteriores e maior precisao"
        )),
        ("recall", "maior", (
            "empate nos criterios anteriores e maior recall"
        )),
        ("acuracia", "maior", (
            "empate nos criterios anteriores e maior acuracia"
        ))
    ]

    for chave, ordem, motivo in criterios:
        if bp[chave] == ag[chave]:
            continue

        if ordem == "menor":
            selecionado = "bp" if bp[chave] < ag[chave] else "ag"
        else:
            selecionado = "bp" if bp[chave] > ag[chave] else "ag"

        return selecionado, motivo

    if (
        bp["tempo_treinamento_segundos"] is not None
        and ag["tempo_treinamento_segundos"] is not None
        and bp["tempo_treinamento_segundos"]
        != ag["tempo_treinamento_segundos"]
    ):
        selecionado = (
            "bp"
            if bp["tempo_treinamento_segundos"]
            < ag["tempo_treinamento_segundos"]
            else "ag"
        )
        return (
            selecionado,
            "empate nas metricas e menor tempo de treinamento"
        )

    return (
        "bp",
        "empate em todos os criterios disponiveis; ordem deterministica BP, AG"
    )


def imprimir_candidato(nome, candidato):
    print()
    print(nome)
    print(f"Threshold selecionado: {candidato['threshold']:.2f}")
    print(f"FN: {candidato['fn']}")
    print(f"FP: {candidato['fp']}")
    print(f"Precisao: {candidato['precisao']:.6f}")
    print(f"Recall: {candidato['recall']:.6f}")
    print(f"F1: {candidato['f1']:.6f}")
    print(
        "Custo de seguranca: "
        f"{candidato['custo_seguranca']:.6f}"
    )

    tempo = candidato["tempo_treinamento_segundos"]
    if tempo is None:
        print("Tempo de treinamento: nao disponivel")
    else:
        print(f"Tempo de treinamento: {tempo:.6f} s")


def salvar_implantacao(
    modelo,
    candidato,
    candidatos,
    motivo,
    alpha_fn,
    beta_fp
):
    arquivo_origem = f"pesos_{modelo}.json"
    arquivo_implantacao = "pesos.json"
    arquivo_temporario = "pesos.json.tmp"

    shutil.copyfile(arquivo_origem, arquivo_temporario)
    os.replace(arquivo_temporario, arquivo_implantacao)

    dados = {
        "data_hora_selecao": datetime.now().astimezone().isoformat(),
        "modelo": modelo,
        "arquivo_origem": arquivo_origem,
        "arquivo_implantacao": arquivo_implantacao,
        "threshold": candidato["threshold"],
        "custo_seguranca_validacao": (
            candidato["custo_seguranca"]
        ),
        "metricas_validacao": candidato,
        "criterio": motivo,
        "formula_custo": "C = alpha_fn * FN + beta_fp * FP",
        "alpha_fn": alpha_fn,
        "beta_fp": beta_fp,
        "candidatos": candidatos
    }

    arquivo_configuracao = "modelo_selecionado.json"
    configuracao_temporaria = "modelo_selecionado.json.tmp"

    with open(
        configuracao_temporaria,
        "w",
        encoding="utf-8"
    ) as arquivo:
        json.dump(dados, arquivo, indent=4)

    os.replace(configuracao_temporaria, arquivo_configuracao)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Seleciona modelo e threshold usando somente validacao."
        )
    )
    parser.add_argument("--alpha-fn", type=float, default=ALPHA_FN)
    parser.add_argument("--beta-fp", type=float, default=BETA_FP)
    parser.add_argument(
        "--threshold-minimo",
        type=float,
        default=THRESHOLD_MINIMO
    )
    parser.add_argument(
        "--threshold-maximo",
        type=float,
        default=THRESHOLD_MAXIMO
    )
    parser.add_argument(
        "--passo-threshold",
        type=float,
        default=PASSO_THRESHOLD
    )
    argumentos = parser.parse_args()

    if argumentos.alpha_fn < 0 or argumentos.beta_fp < 0:
        parser.error("Os custos alpha_fn e beta_fp devem ser nao negativos.")

    if not (
        0.0 <= argumentos.threshold_minimo
        <= argumentos.threshold_maximo <= 1.0
    ):
        parser.error("A faixa de threshold deve estar entre 0 e 1.")

    if argumentos.passo_threshold <= 0:
        parser.error("O passo do threshold deve ser positivo.")

    conjuntos = carregar_conjuntos()
    X_validacao, Y_validacao = conjuntos["validacao"]

    candidatos = {}

    for modelo in ("bp", "ag"):
        probabilidades = obter_probabilidades(
            f"pesos_{modelo}.json",
            X_validacao
        )
        candidato = selecionar_threshold(
            probabilidades,
            Y_validacao,
            argumentos.threshold_minimo,
            argumentos.threshold_maximo,
            argumentos.passo_threshold,
            argumentos.alpha_fn,
            argumentos.beta_fp
        )
        candidato["tempo_treinamento_segundos"] = (
            carregar_tempo_treinamento(modelo)
        )
        candidatos[modelo] = candidato

    modelo, motivo = comparar_candidatos(
        candidatos["bp"],
        candidatos["ag"]
    )
    selecionado = candidatos[modelo]

    # Registra as metricas otimizadas somente com validacao.
    salvar_resultados("validacao", candidatos)
    salvar_implantacao(
        modelo,
        selecionado,
        candidatos,
        motivo,
        argumentos.alpha_fn,
        argumentos.beta_fp
    )

    print()
    print("========================================")
    print("SELECAO DO MODELO PARA O WAF")
    print("========================================")
    imprimir_candidato("BACKPROPAGATION", candidatos["bp"])
    imprimir_candidato("ALGORITMO GENETICO", candidatos["ag"])
    print()
    print(f"Modelo selecionado: {modelo.upper()}")
    print(f"Threshold selecionado: {selecionado['threshold']:.2f}")
    print(f"Motivo da selecao: {motivo}")
    print("========================================")


if __name__ == "__main__":
    main()
