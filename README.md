# Orquestrador — Gemma 2 (HF/CPU) com Pré-carregamento + Fallback SLM

Este projeto usa **google/gemma-2-2b-it** (Hugging Face, CPU) para classificar a intenção em **JSON**
e faz **fallback automático** para um SLM leve (TF-IDF + LinearSVC) caso o LLM falhe.
Inclui **pré-carregamento e warm-up** na inicialização.

## Requisitos
- Python 3.9+
- RAM ~7–8 GB livres para Gemma 2 2B em CPU FP32
- Internet na primeira execução para baixar o modelo (depois cache local).
- Você pode precisar aceitar a licença do Gemma 2 no Hugging Face e fazer login:
  ```bash
  pip install huggingface_hub
  huggingface-cli login
  ```

## Instalação
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Executar
```bash
python orchestrator_hf_json.py
```
Você verá:
```
Modelo HF: google/gemma-2-2b-it
🔧 Pré-carregando modelo HF: google/gemma-2-2b-it ...
✅ Warm-up concluído.
```

## Teste rápido (no prompt)
- `vai chover hoje à noite em sjc?` → PREVISAO  
- `qual o acumulado das últimas 2 horas na estação centro?` → ESTACOES_RT  
- `o que é um slm?` → GENERICO  

## Variáveis úteis (opcionais)
- `HF_MODEL_ID` — trocar o modelo (ex.: TinyLlama para máquinas com menos RAM)  
  - PowerShell: `$env:HF_MODEL_ID="TinyLlama/TinyLlama-1.1B-Chat-v1.0"`  
  - macOS/Linux: `export HF_MODEL_ID=TinyLlama/TinyLlama-1.1B-Chat-v1.0`
- `HF_NUM_THREADS` — limitar threads de CPU (ex.: `export HF_NUM_THREADS=4`)
- `TRANSFORMERS_OFFLINE=1` — rodar offline após baixar o modelo.
- **Debug / Forçar fallback:**
  - `ORCH_VERBOSE=1` — imprime mensagens de debug
  - `ORCH_USE_LLM=0` — desliga o uso do LLM (usa só SVM)
  - `ORCH_FORCE_FALLBACK=1` — força cair no SVM mesmo com LLM disponível

Logs em `audit_log.jsonl`.
