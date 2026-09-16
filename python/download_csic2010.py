"""Baixa localmente os dois arquivos CSIC usados na avaliacao externa."""

from pathlib import Path
import urllib.parse
import urllib.request


BASE_URL = (
    "https://raw.githubusercontent.com/Monkey-D-Groot/"
    "Machine-Learning-on-CSIC-2010/master/"
)
FILENAMES = (
    "normalTrafficTraining.txt",
    "anomalousTrafficTest.txt",
)
ALLOWED_HOST = "raw.githubusercontent.com"
DESTINATION = Path(__file__).resolve().parent.parent / "external_data" / "csic2010"
MAX_FILE_BYTES = 64 * 1024 * 1024


def download(filename):
    url = f"{BASE_URL}{filename}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise RuntimeError("Origem de download nao autorizada.")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "atividade-3-waf-mlp-csic-downloader/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != "https" or final.hostname != ALLOWED_HOST:
            raise RuntimeError("Redirect de download para host nao autorizado.")
        content = response.read(MAX_FILE_BYTES + 1)

    if len(content) > MAX_FILE_BYTES:
        raise RuntimeError(f"Arquivo excede o limite: {filename}")
    if not content.lstrip().startswith((b"GET ", b"POST ")):
        raise RuntimeError(f"Conteudo HTTP CSIC invalido: {filename}")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    temporary = DESTINATION / f".{filename}.download"
    temporary.write_bytes(content)
    temporary.replace(DESTINATION / filename)
    print(f"Baixado: {DESTINATION / filename}")


if __name__ == "__main__":
    for dataset_filename in FILENAMES:
        download(dataset_filename)

