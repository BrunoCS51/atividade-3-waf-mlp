import csv

arquivo = "python/requisicoes.csv"

nomes = [
    "is_post_put",
    "query_length",
    "body_length",
    "special_chars_query",
    "special_chars_body",
    "has_sql_keywords",
    "has_xss_keywords",
    "is_standard_browser",
    "request_rate",
    "label"
]

with open(arquivo, "r", encoding="utf-8") as f:
    leitor = csv.reader(f)
    dados = list(leitor)

print(f"Quantidade de amostras: {len(dados)}")
print(f"Quantidade de colunas: {len(nomes)}")

print("\nMÍNIMO E MÁXIMO DAS FEATURES")
print("-" * 65)

for i in range(9):
    valores = [float(linha[i]) for linha in dados]

    print(
        f"{nomes[i]:25} "
        f"Min: {min(valores):8.2f} | "
        f"Max: {max(valores):8.2f}"
    )

labels = [int(float(linha[9])) for linha in dados]

normal = labels.count(0)
ataque = labels.count(1)

print("\nDISTRIBUIÇÃO DAS CLASSES")
print("-" * 65)
print(f"Normal (0): {normal}")
print(f"Ataque (1): {ataque}")
print(f"Total:      {len(labels)}")