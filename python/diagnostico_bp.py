import csv
import numpy as np


class DiagnosticoBP:

    def __init__(
        self,
        tol_melhoria=1e-6,
        limite_saturacao_inferior=0.05,
        limite_saturacao_superior=0.95,
        arquivo_csv="diagnostico_bp.csv"
    ):
        self.tol_melhoria = tol_melhoria
        self.limite_saturacao_inferior = (
            limite_saturacao_inferior
        )
        self.limite_saturacao_superior = (
            limite_saturacao_superior
        )
        self.arquivo_csv = arquivo_csv

        self.historico = []
        self.mse_anterior = None
        self.epocas_sem_melhoria = 0
        self.ultima_melhoria = None
        self.resumo_final = None

        # ALTERADO PARA METRICA COMPUTACIONAL
        self.tempo_total = None
        self.tempo_cpu_total = None

    def iniciar_epoca(self, quantidade_neuronios_ocultos):
        self.soma_ativacoes = np.zeros(
            quantidade_neuronios_ocultos
        )
        self.soma_quadrados_ativacoes = np.zeros(
            quantidade_neuronios_ocultos
        )
        self.ativacoes_baixas = np.zeros(
            quantidade_neuronios_ocultos,
            dtype=int
        )
        self.ativacoes_altas = np.zeros(
            quantidade_neuronios_ocultos,
            dtype=int
        )
        self.quantidade_ativacoes = 0

        self.soma_abs_delta = None
        self.max_abs_delta = None
        self.quantidade_delta = None

    def registrar_amostra(self, deltas_w, ativacoes_ocultas):
        ativacoes = np.asarray(
            ativacoes_ocultas,
            dtype=float
        )

        self.soma_ativacoes += ativacoes
        self.soma_quadrados_ativacoes += ativacoes ** 2
        self.ativacoes_baixas += (
            ativacoes < self.limite_saturacao_inferior
        )
        self.ativacoes_altas += (
            ativacoes > self.limite_saturacao_superior
        )
        self.quantidade_ativacoes += 1

        if self.soma_abs_delta is None:
            quantidade_camadas = len(deltas_w)
            self.soma_abs_delta = np.zeros(quantidade_camadas)
            self.max_abs_delta = np.zeros(quantidade_camadas)
            self.quantidade_delta = np.zeros(
                quantidade_camadas,
                dtype=int
            )

        for camada, delta_w in enumerate(deltas_w):
            valores = np.abs(delta_w)
            self.soma_abs_delta[camada] += np.sum(valores)
            self.max_abs_delta[camada] = max(
                self.max_abs_delta[camada],
                np.max(valores)
            )
            self.quantidade_delta[camada] += valores.size

    def registrar_epoca(
        self,
        epoca,
        mse_treino,
        mse_validacao,
        mlp,
        tempo_epoca,
        tempo_cpu_epoca
    ):
        if self.mse_anterior is None:
            melhoria = 0.0
            self.epocas_sem_melhoria = 0
            self.ultima_melhoria = epoca
        else:
            melhoria = self.mse_anterior - mse_treino

            if melhoria > self.tol_melhoria:
                self.epocas_sem_melhoria = 0
                self.ultima_melhoria = epoca
            else:
                self.epocas_sem_melhoria += 1

        self.mse_anterior = mse_treino

        medias_ativacoes = (
            self.soma_ativacoes / self.quantidade_ativacoes
        )
        variancias_ativacoes = (
            self.soma_quadrados_ativacoes
            / self.quantidade_ativacoes
            - medias_ativacoes ** 2
        )
        desvios_ativacoes = np.sqrt(
            np.maximum(variancias_ativacoes, 0.0)
        )
        percentuais_baixos = (
            self.ativacoes_baixas
            / self.quantidade_ativacoes
            * 100.0
        )
        percentuais_altos = (
            self.ativacoes_altas
            / self.quantidade_ativacoes
            * 100.0
        )

        registro = {
            "epoca": epoca,
            "mse_treino": mse_treino,
            "mse_validacao": mse_validacao,
            "gap_treino_validacao": (
                mse_validacao - mse_treino
            ),
            "melhoria": melhoria,
            "epocas_sem_melhoria": self.epocas_sem_melhoria,
            # ALTERADO PARA METRICA COMPUTACIONAL
            "tempo_parede_epoca_segundos": tempo_epoca,
            "tempo_cpu_epoca_segundos": tempo_cpu_epoca,
            "percentual_saturacao_oculta": (
                np.sum(self.ativacoes_baixas + self.ativacoes_altas)
                / (
                    self.quantidade_ativacoes
                    * len(self.soma_ativacoes)
                )
                * 100.0
            )
        }

        estatisticas_pesos = []

        for camada in range(mlp.n_camadas - 1):
            n_anterior = mlp.rede[camada]
            n_atual = mlp.rede[camada + 1]
            pesos = mlp.w[
                :n_anterior + 1,
                :n_atual,
                camada
            ]

            estatisticas = {
                "magnitude_media": np.mean(np.abs(pesos)),
                "media": np.mean(pesos),
                "desvio": np.std(pesos),
                "menor": np.min(pesos),
                "maior": np.max(pesos),
                "delta_magnitude_media": (
                    self.soma_abs_delta[camada]
                    / self.quantidade_delta[camada]
                ),
                "delta_magnitude_maxima": (
                    self.max_abs_delta[camada]
                )
            }
            estatisticas_pesos.append(estatisticas)

            numero = camada + 1
            for nome, valor in estatisticas.items():
                registro[
                    f"camada_{numero}_{nome}"
                ] = valor

        self.historico.append(registro)
        self.resumo_final = {
            **registro,
            "estatisticas_pesos": estatisticas_pesos,
            "medias_ativacoes": medias_ativacoes,
            "desvios_ativacoes": desvios_ativacoes,
            "percentuais_baixos": percentuais_baixos,
            "percentuais_altos": percentuais_altos
        }

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

        # O historico representa somente a execucao atual.
        with open(
            self.arquivo_csv,
            "w",
            newline="",
            encoding="utf-8"
        ) as arquivo:
            escritor = csv.DictWriter(
                arquivo,
                fieldnames=list(self.historico[0].keys())
            )
            escritor.writeheader()
            escritor.writerows(self.historico)

    def imprimir_resumo(self):
        if self.resumo_final is None:
            return

        resumo = self.resumo_final

        print()
        print("========================================")
        print("DIAGNOSTICO DO BACKPROPAGATION")
        print("========================================")
        print()
        print(f"MSE treino: {resumo['mse_treino']:.8f}")
        print(f"MSE validacao: {resumo['mse_validacao']:.8f}")
        print(
            "Diferenca treino-validacao: "
            f"{resumo['gap_treino_validacao']:.8f}"
        )
        print(f"Epocas executadas: {len(self.historico)}")
        print(
            "Ultima melhoria relevante: "
            f"epoca {self.ultima_melhoria}"
        )
        print(
            "Epocas consecutivas sem melhoria: "
            f"{resumo['epocas_sem_melhoria']}"
        )
        print(
            "Ativacoes ocultas proximas da saturacao: "
            f"{resumo['percentual_saturacao_oculta']:.2f}%"
        )
        # ALTERADO PARA METRICA COMPUTACIONAL
        print()
        print(f"Tempo total de treinamento: {self.tempo_total:.6f} s")
        print(
            "Tempo medio por epoca: "
            f"{self.tempo_total / len(self.historico):.6f} s"
        )
        print(f"Tempo total de CPU: {self.tempo_cpu_total:.6f} s")
        print(
            "Tempo medio de CPU por epoca: "
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

        for indice, estatisticas in enumerate(
            resumo["estatisticas_pesos"],
            start=1
        ):
            print()
            print(f"Camada de pesos {indice}:")
            print(
                "  Magnitude media: "
                f"{estatisticas['magnitude_media']:.8f}"
            )
            print(f"  Media: {estatisticas['media']:.8f}")
            print(f"  Desvio: {estatisticas['desvio']:.8f}")
            print(f"  Menor: {estatisticas['menor']:.8f}")
            print(f"  Maior: {estatisticas['maior']:.8f}")
            print(
                "  Magnitude media de delta W: "
                f"{estatisticas['delta_magnitude_media']:.8f}"
            )
            print(
                "  Magnitude maxima de delta W: "
                f"{estatisticas['delta_magnitude_maxima']:.8f}"
            )

        print()
        print("Ativacoes por neuronio oculto:")

        for indice in range(len(resumo["medias_ativacoes"])):
            print(
                f"  Neuronio {indice + 1:2d} | "
                f"Media: {resumo['medias_ativacoes'][indice]:.8f} | "
                f"Desvio: {resumo['desvios_ativacoes'][indice]:.8f} | "
                f"< 0.05: {resumo['percentuais_baixos'][indice]:.2f}% | "
                f"> 0.95: {resumo['percentuais_altos'][indice]:.2f}%"
            )

        print("========================================")
