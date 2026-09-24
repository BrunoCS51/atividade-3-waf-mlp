import numpy as np


# ========== POPULACAO ==============

def criar_populacao(npop, n_genes, rmin=-1, rmax=1):

    populacao = np.random.uniform(
        rmin,
        rmax,
        (npop, n_genes)
    )

    return populacao


# ========== FITNESS ==============

def fitness(individuo, mlp, X, Y):

    # Coloca os genes do individuo
    # como pesos da rede
    mlp.set_cromossomo(individuo)

    # O forward vetorizado usa a mesma sigmoide, bias = -1 e matrizes
    # de pesos da implementação original, mas aceita uma ou mais camadas
    # ocultas configuradas na MLP.
    saida = mlp.forward_batch(X)


    # ---------- MSE ----------

    erro = (
        Y.reshape(-1, 1)
        - saida
    )

    mse = np.mean(
        erro ** 2
    )

    return mse

# ========== SELECAO ==============

def selecao(
    populacao,
    custos,
    tipo=1,
    tamanho_torneio=3
):

    npop = len(populacao)

    # ========================================
    # TIPO 1 - TORNEIO
    # ========================================

    if tipo == 1:

        selecionados = []

        for _ in range(npop):

            participantes = np.random.choice(
                npop,
                tamanho_torneio,
                replace=False
            )

            custos_participantes = custos[
                participantes
            ]

            # Menor custo = melhor individuo
            vencedor = participantes[
                np.argmin(custos_participantes)
            ]

            selecionados.append(
                populacao[vencedor].copy()
            )

        return np.array(selecionados)


    # ========================================
    # TIPO 2 - ROLETA
    # ========================================

    elif tipo == 2:

        # Como nosso problema e de minimizacao,
        # convertemos custo em aptidao.
        aptidao = 1.0 / (
            custos + 1e-12
        )

        probabilidades = (
            aptidao / np.sum(aptidao)
        )

        indices = np.random.choice(
            npop,
            size=npop,
            replace=True,
            p=probabilidades
        )

        return populacao[
            indices
        ].copy()


    else:

        raise ValueError(
            "Tipo de selecao invalido. "
            "Use 1 = Torneio ou 2 = Roleta."
        )

# ========== CROSSOVER ==============

def crossover(
    pai1,
    pai2,
    tipo=1,
    taxa_crossover=0.8,
    eta=1
):

    # Se nao ocorrer crossover,
    # os pais passam diretamente
    if np.random.rand() > taxa_crossover:

        return (
            pai1.copy(),
            pai2.copy()
        )


    # ========================================
    # TIPO 1 - CROSSOVER DE UM PONTO
    # ========================================

    if tipo == 1:

        n_genes = len(pai1)

        ponto = np.random.randint(
            1,
            n_genes
        )

        filho1 = np.concatenate([
            pai1[:ponto],
            pai2[ponto:]
        ])

        filho2 = np.concatenate([
            pai2[:ponto],
            pai1[ponto:]
        ])

        return filho1, filho2


    # ========================================
    # TIPO 2 - SBX
    # ========================================

    elif tipo == 2:

        filho1 = np.zeros_like(pai1)
        filho2 = np.zeros_like(pai2)

        for gene in range(len(pai1)):

            u = np.random.rand()

            if u <= 0.5:

                beta = (
                    2 * u
                ) ** (
                    1 / (eta + 1)
                )

            else:

                beta = (
                    1 / (2 * (1 - u))
                ) ** (
                    1 / (eta + 1)
                )

            filho1[gene] = (
                0.5
                * (
                    (1 + beta) * pai1[gene]
                    + (1 - beta) * pai2[gene]
                )
            )

            filho2[gene] = (
                0.5
                * (
                    (1 - beta) * pai1[gene]
                    + (1 + beta) * pai2[gene]
                )
            )

        return filho1, filho2


    else:

        raise ValueError(
            "Tipo de crossover invalido. "
            "Use 1 = Um ponto ou 2 = SBX."
        )

# ========== MUTACAO ==============

def mutacao(
    individuo,
    tipo=1,
    taxa_mutacao=0.02,
    rmin=-1,
    rmax=1,
    sigma=0.1,
    eta_m=20
):

    filho = individuo.copy()


    # ========================================
    # TIPO 1 - MUTACAO UNIFORME
    # ========================================

    if tipo == 1:

        for gene in range(len(filho)):

            if np.random.rand() < taxa_mutacao:

                filho[gene] = np.random.uniform(
                    rmin,
                    rmax
                )


    # ========================================
    # TIPO 2 - MUTACAO GAUSSIANA
    # ========================================

    elif tipo == 2:

        desvio = sigma * (
            rmax - rmin
        )

        for gene in range(len(filho)):

            if np.random.rand() < taxa_mutacao:

                filho[gene] += np.random.normal(
                    0,
                    desvio
                )


    # ========================================
    # TIPO 3 - MUTACAO POLINOMIAL
    # ========================================

    elif tipo == 3:

        for gene in range(len(filho)):

            if np.random.rand() < taxa_mutacao:

                u = np.random.rand()

                if u < 0.5:

                    delta = (
                        (2 * u)
                        ** (1 / (eta_m + 1))
                        - 1
                    )

                else:

                    delta = (
                        1
                        - (
                            2 * (1 - u)
                        )
                        ** (1 / (eta_m + 1))
                    )

                filho[gene] += (
                    delta
                    * (rmax - rmin)
                )


    else:

        raise ValueError(
            "Tipo de mutacao invalido. "
            "Use 1 = Uniforme, "
            "2 = Gaussiana ou "
            "3 = Polinomial."
        )


    # Mantem os genes dentro do intervalo
    filho = np.clip(
        filho,
        rmin,
        rmax
    )

    return filho
