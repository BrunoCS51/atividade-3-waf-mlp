import csv
import numpy as np


class DiagnosticoAG:

    def __init__(
        self,
        rmin,
        rmax,
        tol_melhoria=1e-6,
        faixa_limites=0.05,
        arquivo_csv="diagnostico_ag.csv"
    ):
        self.rmin = rmin
        self.rmax = rmax
        self.tol_melhoria = tol_melhoria
        self.faixa_limites = faixa_limites
        self.arquivo_csv = arquivo_csv

        self.historico = []
        self.melhor_anterior = None
        self.geracoes_sem_melhoria = 0
        self.ultima_melhoria = None
        self.resumo_final = None

        # ALTERADO PARA METRICA COMPUTACIONAL
        self.tempo_total = None
        self.tempo_cpu_total = None

    def registrar_geracao(
        self,
        geracao,
        mse_treino,
        mse_validacao,
        populacao,
        melhor_individuo
    ):
        populacao = np.asarray(populacao, dtype=float)
        melhor_individuo = np.asarray(
            melhor_individuo,
            dtype=float
        )

        if self.melhor_anterior is None:
            melhoria = 0.0
            self.geracoes_sem_melhoria = 0
            self.ultima_melhoria = geracao
        else:
            melhoria = self.melhor_anterior - mse_treino

            if melhoria > self.tol_melhoria:
                self.geracoes_sem_melhoria = 0
                self.ultima_melhoria = geracao
            else:
                self.geracoes_sem_melhoria += 1

        self.melhor_anterior = mse_treino

        # Media do desvio-padrao de cada gene entre os individuos.
        diversidade = np.mean(
            np.std(populacao, axis=0)
        )

        intervalo = self.rmax - self.rmin
        tolerancia_limite = self.faixa_limites * intervalo

        proximos_limites = (
            (populacao <= self.rmin + tolerancia_limite)
            | (populacao >= self.rmax - tolerancia_limite)
        )

        quantidade_limites = int(np.sum(proximos_limites))
        percentual_limites = (
            quantidade_limites / populacao.size * 100.0
        )

        registro = {
            "geracao": geracao,
            "mse_treino": mse_treino,
            "mse_validacao": mse_validacao,
            "gap_treino_validacao": (
                mse_validacao - mse_treino
            ),
            "melhoria": melhoria,
            "geracoes_sem_melhoria": (
                self.geracoes_sem_melhoria
            ),
            "diversidade": diversidade,
            "media_genes": np.mean(populacao),
            "desvio_genes": np.std(populacao),
            "menor_gene": np.min(populacao),
            "maior_gene": np.max(populacao),
            "percentual_limites": percentual_limites
        }

        self.historico.append(registro)

        self.resumo_final = {
            **registro,
            "quantidade_limites": quantidade_limites,
            "total_genes": populacao.size,
            "magnitude_melhor": np.mean(
                np.abs(melhor_individuo)
            ),
            "desvio_melhor": np.std(melhor_individuo)
        }

    # ALTERADO PARA METRICA COMPUTACIONAL
    def registrar_tempo_geracao(
        self,
        tempo_geracao,
        tempo_cpu_geracao
    ):
        self.historico[-1][
            "tempo_parede_geracao_segundos"
        ] = tempo_geracao
        self.historico[-1][
            "tempo_cpu_geracao_segundos"
        ] = tempo_cpu_geracao

        self.resumo_final.update(self.historico[-1])

    # ALTERADO PARA METRICA COMPUTACIONAL
    def registrar_custo_computacional(
        self,
        tempo_total,
        tempo_cpu_total
    ):
        self.tempo_total = tempo_total
        self.tempo_cpu_total = tempo_cpu_total

    def salvar_csv(self):
        if not self.historico:
            return

        colunas = [
            "geracao",
            "mse_treino",
            "mse_validacao",
            "gap_treino_validacao",
            "melhoria",
            "geracoes_sem_melhoria",
            "diversidade",
            "media_genes",
            "desvio_genes",
            "menor_gene",
            "maior_gene",
            "percentual_limites",
            # ALTERADO PARA METRICA COMPUTACIONAL
            "tempo_parede_geracao_segundos",
            "tempo_cpu_geracao_segundos"
        ]

        # O historico representa somente a execucao atual.
        with open(
            self.arquivo_csv,
            "w",
            newline="",
            encoding="utf-8"
        ) as arquivo:
            escritor = csv.DictWriter(
                arquivo,
                fieldnames=colunas
            )
            escritor.writeheader()
            escritor.writerows(self.historico)

    def imprimir_resumo(self):
        if self.resumo_final is None:
            return

        resumo = self.resumo_final

        print()
        print("========================================")
        print("DIAGNOSTICO DO ALGORITMO GENETICO")
        print("========================================")
        print()
        print(f"Melhor MSE treino: {resumo['mse_treino']:.8f}")
        print(f"MSE validacao: {resumo['mse_validacao']:.8f}")
        print(
            "Diferenca treino-validacao: "
            f"{resumo['gap_treino_validacao']:.8f}"
        )
        print()
        print(f"Geracoes executadas: {len(self.historico)}")
        print(
            "Ultima melhoria relevante: "
            f"geracao {self.ultima_melhoria}"
        )
        print(
            "Geracoes consecutivas sem melhoria: "
            f"{resumo['geracoes_sem_melhoria']}"
        )
        print()
        print(
            "Diversidade final da populacao: "
            f"{resumo['diversidade']:.8f}"
        )
        print(f"Media dos genes: {resumo['media_genes']:.8f}")
        print(f"Desvio dos genes: {resumo['desvio_genes']:.8f}")
        print(f"Menor gene: {resumo['menor_gene']:.8f}")
        print(f"Maior gene: {resumo['maior_gene']:.8f}")
        print()
        print(
            "Genes proximos aos limites: "
            f"{resumo['quantidade_limites']}/"
            f"{resumo['total_genes']}"
        )
        print(
            "Percentual proximo aos limites: "
            f"{resumo['percentual_limites']:.2f}%"
        )
        print()
        print(
            "Magnitude media dos pesos do melhor individuo: "
            f"{resumo['magnitude_melhor']:.8f}"
        )
        print(
            "Desvio dos pesos: "
            f"{resumo['desvio_melhor']:.8f}"
        )
        # ALTERADO PARA METRICA COMPUTACIONAL
        print()
        print(f"Tempo total de treinamento: {self.tempo_total:.6f} s")
        print(
            "Tempo medio por geracao: "
            f"{self.tempo_total / len(self.historico):.6f} s"
        )
        print(f"Tempo total de CPU: {self.tempo_cpu_total:.6f} s")
        print(
            "Tempo medio de CPU por geracao: "
            f"{self.tempo_cpu_total / len(self.historico):.6f} s"
        )
        print(
            "Pico de memoria: nao medido; a biblioteca padrao nao "
            "oferece uma medida multiplataforma confiavel do processo."
        )
        print(
            "Energia: nao medida; exige instrumentacao especifica "
            "de hardware ou do sistema operacional."
        )
        print("========================================")
