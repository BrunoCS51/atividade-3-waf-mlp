import numpy as np
import json


# ========== FUNCOES ==============

def sigmoid(x):
    x = np.clip(x, -709, 709)
    return 1 / (1 + np.exp(-x))


def derivada_sigmoid(y):
    return y * (1 - y)


# ========== CLASSE MLP ==============

class MLP:

    def __init__(
        self,
        input_size=None,
        hidden_size=None,
        output_size=None,
        architecture=None
    ):

        # A assinatura historica MLP(entrada, oculta, saida) permanece
        # inalterada. Novos experimentos podem fornecer qualquer sequencia
        # [entrada, ocultas..., saida] por meio de architecture.
        if architecture is None:
            if (
                input_size is None
                or hidden_size is None
                or output_size is None
            ):
                raise ValueError(
                    "Informe input_size, hidden_size e output_size "
                    "ou uma architecture completa."
                )
            architecture = [
                input_size,
                hidden_size,
                output_size
            ]

        self.rede = np.array(architecture, dtype=int)

        if self.rede.ndim != 1 or self.rede.size < 3:
            raise ValueError(
                "A arquitetura deve conter entrada, ao menos uma "
                "camada oculta e saida."
            )

        if np.any(self.rede <= 0):
            raise ValueError(
                "Todas as camadas devem possuir tamanho positivo."
            )

        self.input_size = int(self.rede[0])
        # Mantido para compatibilidade com o Experimento 1 e diagnosticos.
        self.hidden_size = int(self.rede[1])
        self.output_size = int(self.rede[-1])

        self.bias = -1

        self.n_camadas = self.rede.size
        self.max_neuronios = np.max(self.rede)

        # Matriz 3D de pesos
        linhas = self.max_neuronios + 1
        colunas = self.max_neuronios
        profundidade = self.n_camadas - 1

        self.w = np.zeros(
            (linhas, colunas, profundidade)
        )

        # Inicializacao aleatoria dos pesos
        for camada in range(profundidade):

            n_anterior = self.rede[camada]
            n_atual = self.rede[camada + 1]

            self.w[
                :n_anterior + 1,
                :n_atual,
                camada
            ] = np.random.uniform(
                -1,
                1,
                (n_anterior + 1, n_atual)
            )


    # ========== FEEDFORWARD ==============

    def forward(self, x):

        x = np.array(x, dtype=float)

        if x.size != self.rede[0]:
            raise ValueError(
                "Quantidade de entradas diferente da camada de entrada!"
            )

        saida_camadas = np.zeros(
            (self.n_camadas, self.max_neuronios)
        )

        # Primeira camada = entrada
        saida_camadas[0, :self.rede[0]] = x

        for camada in range(1, self.n_camadas):

            entrada_camada = saida_camadas[
                camada - 1,
                :self.rede[camada - 1]
            ]

            # Adiciona o bias
            entrada_bias = np.concatenate(
                ([self.bias], entrada_camada)
            )

            n_anterior = self.rede[camada - 1]
            n_atual = self.rede[camada]

            indice_w = camada - 1

            pesos_camada = self.w[
                :n_anterior + 1,
                :n_atual,
                indice_w
            ]

            net = entrada_bias @ pesos_camada

            saida = sigmoid(net)

            saida_camadas[
                camada,
                :n_atual
            ] = saida

        return saida_camadas[
            -1,
            :self.rede[-1]
        ]

    def forward_batch(self, X):

        X = np.asarray(X, dtype=float)

        if X.ndim != 2 or X.shape[1] != self.rede[0]:
            raise ValueError(
                "Matriz de entrada incompatível com a camada de entrada!"
            )

        saida = X

        for camada in range(self.n_camadas - 1):

            bias = np.full(
                (saida.shape[0], 1),
                self.bias
            )

            entrada_bias = np.concatenate(
                (bias, saida),
                axis=1
            )

            n_anterior = self.rede[camada]
            n_atual = self.rede[camada + 1]

            pesos_camada = self.w[
                :n_anterior + 1,
                :n_atual,
                camada
            ]

            saida = sigmoid(
                entrada_bias @ pesos_camada
            )

        return saida

    # ========== BACKPROPAGATION ==============

    def backward(self, x, yd, taxa=0.01):

        x = np.array(x, dtype=float)
        yd = np.array(yd, dtype=float)

        if x.size != self.rede[0]:
            raise ValueError(
                "Quantidade de entradas diferente da camada de entrada!"
            )

        if yd.size != self.rede[-1]:
            raise ValueError(
                "Quantidade de saidas diferente da camada de saida!"
            )

        # ========== MEMORIA DAS CAMADAS ==============

        saida_camadas = np.zeros(
            (self.n_camadas, self.max_neuronios)
        )

        erro_camadas = np.zeros(
            (self.n_camadas, self.max_neuronios)
        )

        # ========== FEEDFORWARD ==============

        saida_camadas[0, :self.rede[0]] = x

        for camada in range(1, self.n_camadas):

            entrada_camada = saida_camadas[
                camada - 1,
                :self.rede[camada - 1]
            ]

            entrada_bias = np.concatenate(
                ([self.bias], entrada_camada)
            )

            n_anterior = self.rede[camada - 1]
            n_atual = self.rede[camada]

            indice_w = camada - 1

            pesos_camada = self.w[
                :n_anterior + 1,
                :n_atual,
                indice_w
            ]

            net = entrada_bias @ pesos_camada

            saida = sigmoid(net)

            saida_camadas[
                camada,
                :n_atual
            ] = saida

        # ========== ERRO DA SAIDA ==============

        y_s = saida_camadas[
            -1,
            :self.rede[-1]
        ]

        erro_saida = yd - y_s

        erro_camadas[
            -1,
            :self.rede[-1]
        ] = erro_saida

        # ========== MSE ==============

        mse = np.mean(erro_saida ** 2)

        # ALTERADO PARA DIAGNOSTICO
        # Apenas expoe dados ja calculados neste backward.
        self.ultimas_ativacoes_ocultas = saida_camadas[
            1,
            :self.rede[1]
        ].copy()
        self.ultimos_delta_w = [
            None
            for _ in range(self.n_camadas - 1)
        ]

        # ========== BACKPROPAGATION ==============

        for camada in range(
            self.n_camadas - 1,
            0,
            -1
        ):

            n_atual = self.rede[camada]
            n_anterior = self.rede[camada - 1]

            erro_atual = erro_camadas[
                camada,
                :n_atual
            ]

            entrada_atual = saida_camadas[
                camada - 1,
                :n_anterior
            ]

            entrada_bias = np.concatenate(
                ([self.bias], entrada_atual)
            )

            saida_atual = saida_camadas[
                camada,
                :n_atual
            ]

            indice_w = camada - 1

            # ========== CORRECAO DOS PESOS ==============

            delta_w = (
                taxa * entrada_bias[:, np.newaxis]
            ) * (
                derivada_sigmoid(saida_atual)
                * erro_atual
            )

            # ALTERADO PARA DIAGNOSTICO
            self.ultimos_delta_w[indice_w] = delta_w.copy()

            # ========== PROPAGA ERRO ==============

            if camada > 1:

                pesos_sem_bias = self.w[
                    1:n_anterior + 1,
                    :n_atual,
                    indice_w
                ]

                erro_camadas[
                    camada - 1,
                    :n_anterior
                ] = (
                    erro_atual
                    @ pesos_sem_bias.T
                )

            # ========== ATUALIZA PESOS ==============

            self.w[
                :n_anterior + 1,
                :n_atual,
                indice_w
            ] += delta_w

        return mse

    # ========== PESOS ==============

    def get_pesos(self):
        return self.w.copy()


    def set_pesos(self, pesos):
        self.w = np.array(
            pesos,
            dtype=float
        ).copy()

    # ========== CROMOSSOMO ==============

    def get_cromossomo(self):

        cromossomo = []

        for camada in range(self.n_camadas - 1):

            n_anterior = self.rede[camada]
            n_atual = self.rede[camada + 1]

            pesos_camada = self.w[
                :n_anterior + 1,
                :n_atual,
                camada
            ]

            cromossomo.extend(
                pesos_camada.flatten()
            )

        return np.array(
            cromossomo,
            dtype=float
        )


    def set_cromossomo(self, cromossomo):

        cromossomo = np.array(
            cromossomo,
            dtype=float
        )

        posicao = 0

        for camada in range(self.n_camadas - 1):

            n_anterior = self.rede[camada]
            n_atual = self.rede[camada + 1]

            quantidade = (
                (n_anterior + 1)
                * n_atual
            )

            pesos_camada = cromossomo[
                posicao:
                posicao + quantidade
            ].reshape(
                n_anterior + 1,
                n_atual
            )

            self.w[
                :n_anterior + 1,
                :n_atual,
                camada
            ] = pesos_camada

            posicao += quantidade

    # ========== SALVAR ==============

    def save(self, filename):

        dados = {
            "rede": self.rede.tolist(),
            "bias": self.bias,
            "pesos": self.w.tolist()
        }

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as arquivo:

            json.dump(
                dados,
                arquivo,
                indent=4
            )


    # ========== CARREGAR ==============

    def load(self, filename):

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as arquivo:

            dados = json.load(arquivo)

        self.rede = np.array(
            dados["rede"],
            dtype=int
        )

        if self.rede.ndim != 1 or self.rede.size < 3:
            raise ValueError(
                "Arquitetura invalida no arquivo de pesos."
            )

        self.input_size = int(self.rede[0])
        self.hidden_size = int(self.rede[1])
        self.output_size = int(self.rede[-1])
        self.n_camadas = self.rede.size
        self.max_neuronios = int(np.max(self.rede))

        self.bias = dados["bias"]

        self.w = np.array(
            dados["pesos"],
            dtype=float
        )
