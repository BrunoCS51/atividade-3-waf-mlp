import os
from flask import Flask, request, Response
from extractor import extract_features
from mlp import MLP

app = Flask(__name__)

mlp = MLP(input_size=9, hidden_size=10, output_size=1)
if os.path.exists("pesos.json"):
    mlp.load("pesos.json")

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def check(path):
    uri = request.headers.get("X-Original-URI", request.url)
    method = request.headers.get("X-Original-Method", request.method)
    client_ip = request.headers.get("X-Real-IP", request.remote_addr)
    body = request.get_data(as_text=True)
    
    features = extract_features(request.headers, uri, method, body, client_ip)
    risk = mlp.forward(features)[0]
    
    print(f"DEBUG [{method}]: Features: {features} | Risco: {risk:.4f}", flush=True)
    
    if risk > 0.35:  # Limiar calibrado
        return Response("Bloqueado pelo WAF", status=403)
        
    return Response(status=200, headers={"X-Accel-Redirect": f"/_php_backend{uri}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
