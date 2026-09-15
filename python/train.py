import csv
from mlp import MLP

# TODO: Passo 1 - Ler o arquivo 'requisicoes.csv'
# - Dica: Use o modulo 'csv' para ler linha por linha.
# - Separe os primeiros 9 valores na matriz de features (X) e o ultimo na matriz de rotulos (y).
# - Lembre-se de normalizar as features dividindo pelos seus limites teoricos.

# TODO: Passo 2 - Instanciar a Rede Neural
# - Crie um objeto da classe MLP. Quantos neuronios de entrada e saida sao necessarios?

# TODO: Passo 3 - Loop de Treinamento (Epocas)
# - Defina a quantidade de epocas (ex: 100).
# - Para cada linha (amostra), realize o forward().
# - Use a saida do forward para chamar o backward() e atualizar a rede usando o rotulo esperado (y).

# TODO: Passo 4 - Salvar o modelo
# - Chame a funcao save() para gravar os pesos aprendidos (pesos.json).

print("Implemente a rotina de treinamento!")
