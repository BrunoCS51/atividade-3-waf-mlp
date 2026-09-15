import math
import random
import json

def sigmoid(x):
    x = max(-709, min(709, x))
    return 1 / (1 + math.exp(-x))

class MLP:
    def __init__(self, input_size, hidden_size, output_size):
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.output_size = output_size
        
        # TODO: Inicializar matrizes de pesos aleatorios (W1, W2) e vieses (b1, b2)
        # Lembre-se que W1 liga as entradas a camada oculta e W2 liga a oculta a saida.
        pass

    def forward(self, X):
        # TODO: Implementar a etapa de Feed-Forward.
        # 1. Multiplicar entradas (X) pelos pesos W1 e somar b1
        # 2. Aplicar funcao de ativacao (sigmoid) para gerar a camada oculta
        # 3. Multiplicar a camada oculta pela matriz W2 e somar b2
        # 4. Aplicar funcao sigmoid para gerar a saida e retornar o resultado
        return [0.0] * self.output_size

    def backward(self, X, y, lr=0.01):
        # TODO: Implementar o algoritmo de Backpropagation
        # 1. Calcular o erro na camada de saida
        # 2. Calcular o erro propagado na camada oculta
        # 3. Atualizar pesos W2 e b2 com base no erro e na taxa de aprendizado (lr)
        # 4. Atualizar pesos W1 e b1
        pass

    def save(self, filename):
        # TODO: Salvar as matrizes W1, W2, b1 e b2 em um arquivo JSON
        pass

    def load(self, filename):
        # TODO: Carregar as matrizes de um arquivo JSON salvo
        pass
