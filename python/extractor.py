import urllib.parse
import time

request_history = {}

def extract_features(headers, uri, method, body, client_ip):
    # TODO: Passo 1 - Separe a query string da URI.
    
    # TODO: Passo 2 - Decodifique a query e o body (urllib.parse.unquote) 
    # para evitar a evasao do WAF.
    
    # TODO: Passo 3 - Calcule tamanhos, conte caracteres especiais, e 
    # faca a busca por palavras-chave de SQLi e XSS.
    
    # TODO: Passo 4 - Verifique o User-Agent e calcule a taxa de 
    # requisicoes (req_rate) do IP atual.
    
    # TODO: Passo 5 - Normalize os 9 valores (entre 0 e 1) e retorne
    # uma lista contendo exatamente esses 9 floats.
    
    return [0.0] * 9
