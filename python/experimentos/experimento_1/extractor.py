import urllib.parse
import time

request_history = {}

LIMITES = [
    1,      # is_post_put
    200,    # query_length
    1000,   # body_length
    25,     # special_chars_query
    40,     # special_chars_body
    1,      # has_sql_keywords
    1,      # has_xss_keywords
    1,      # is_standard_browser
    800     # request_rate
]

NOMES_FEATURES = [
    "is_post_put",
    "query_length",
    "body_length",
    "special_chars_query",
    "special_chars_body",
    "has_sql_keywords",
    "has_xss_keywords",
    "is_standard_browser",
    "request_rate"
]


def extract_features(headers, uri, method, body, client_ip):

    parsed_uri = urllib.parse.urlsplit(uri)

    query = urllib.parse.unquote(parsed_uri.query)
    body = urllib.parse.unquote(body or "")

    query_lower = query.lower()
    body_lower = body.lower()
    conteudo = query_lower + " " + body_lower

    is_post_put = 1 if method.upper() in ["POST", "PUT"] else 0

    query_length = len(query)
    body_length = len(body)

    caracteres_especiais = "'\"<>;(){}[]=/\\"

    special_chars_query = sum(
        1 for caractere in query
        if caractere in caracteres_especiais
    )

    special_chars_body = sum(
        1 for caractere in body
        if caractere in caracteres_especiais
    )

    sql_keywords = [
        "select",
        "union",
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        " or ",
        " and ",
        "--",
        "/*",
        "*/"
    ]

    has_sql_keywords = 1 if any(
        termo in conteudo for termo in sql_keywords
    ) else 0

    xss_keywords = [
        "<script",
        "</script",
        "javascript:",
        "onerror=",
        "onload=",
        "onclick=",
        "<iframe",
        "<svg"
    ]

    has_xss_keywords = 1 if any(
        termo in conteudo for termo in xss_keywords
    ) else 0

    user_agent = headers.get("User-Agent", "").lower()

    navegadores = [
        "mozilla",
        "chrome",
        "safari",
        "firefox",
        "edge",
        "edg/"
    ]

    is_standard_browser = 1 if any(
        navegador in user_agent
        for navegador in navegadores
    ) else 0

    agora = time.time()

    if client_ip not in request_history:
        request_history[client_ip] = []

    request_history[client_ip] = [
        instante
        for instante in request_history[client_ip]
        if agora - instante <= 60
    ]

    request_history[client_ip].append(agora)

    request_rate = len(request_history[client_ip])

    valores_reais = [
        is_post_put,
        query_length,
        body_length,
        special_chars_query,
        special_chars_body,
        has_sql_keywords,
        has_xss_keywords,
        is_standard_browser,
        request_rate
    ]

    excedentes = []

    for nome, valor, limite in zip(
        NOMES_FEATURES,
        valores_reais,
        LIMITES
    ):
        if valor > limite:
            excedentes.append({
                "feature": nome,
                "valor_real": valor,
                "limite": limite
            })

    features_normalizadas = [
        min(max(float(valor) / limite, 0.0), 1.0)
        for valor, limite in zip(valores_reais, LIMITES)
    ]

    return features_normalizadas, excedentes