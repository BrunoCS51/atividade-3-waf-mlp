# HTTP CSIC 2010 — dados locais

Esta pasta recebe, apenas no ambiente local, os arquivos:

- `normalTrafficTraining.txt` — ground truth `NORMAL`;
- `anomalousTrafficTest.txt` — ground truth `ATAQUE`.

Os arquivos brutos são ignorados pelo Git porque o repositório-fonte não
declara claramente uma licença de redistribuição. Para obtê-los da origem
configurada e fixa, execute:

```bash
python python/download_csic2010.py
```

Eles são usados exclusivamente pela avaliação externa controlada e não entram
no treino, validação, teste interno ou seleção do modelo.

