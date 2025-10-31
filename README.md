# Chatbot

Este repositório contém um projeto simples de chatbot em Python. Os arquivos principais incluem `chatbot.py`, `chatbot_new.py` e uma interface leve em `llm.py`. Conversas e exemplos podem estar em `conversas.csv`.

![Chatbot Screenshot](screenshots/example.png)

## Requisitos

- [Python 3.9](https://www.python.org/downloads/)
- [Ollama](https://ollama.ai/download) com os modelos:
  - `llama3.1:8b` - Modelo de linguagem
  - `znbang/bge:small-en-v1.5-f32` - Modelo de embeddings
- Dependências listadas em `requirements.txt`

É recomendado usar um ambiente virtual para isolar dependências.

## Instalação rápida

1. Criar e ativar um ambiente virtual.

- No Windows PowerShell:

```powershell
python39 -m venv chatbotenv
./chatbotenv/Scripts/Activate.ps1
```

- No Prompt de Comando (cmd.exe):

```cmd
chatbotenv\Scripts\activate.bat
```

- No Linux / macOS (bash/zsh):

```bash
python3 -m venv chatbotenv
source chatbotenv/bin/activate
```

2. Instalar dependências:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

No Linux / macOS, os mesmos comandos funcionam (use `python3`/`pip3` se necessário):

```bash
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt
```

3. Instalar e configurar Ollama:

```powershell
# Baixe o Ollama de https://ollama.ai
# Depois instale os modelos:
ollama pull llama3.1:8b
ollama pull znbang/bge:small-en-v1.5-f32
```

## Executando o chatbot

### Via VS Code (Recomendado)

O projeto inclui configurações prontas em `.vscode/launch.json`:

1. Abra o projeto no VS Code
2. **Ctrl+Shift+P** → **"Python: Select Interpreter"** → Escolha `.\chatbotenv\Scripts\python.exe`
3. **F5** ou **Run > Start Debugging**
4. Selecione uma das configurações:
   - **"Python: Chatbot (Production)"** - Executa com LLM real
   - **"Python: Chatbot (UI Only)"** - Executa com respostas mockadas (rápido para testar UI, não salva no CSV)

### Via Terminal

```powershell
# Modo produção (com LLM)
python chatbot_new.py

# Modo UI apenas (sem carregar LLM)
$env:CHATBOT_UI_ONLY="true"; python chatbot_new.py
```

No Linux/macOS:

```bash
# Modo produção
python3 chatbot_new.py

# Modo UI apenas
CHATBOT_UI_ONLY=true python3 chatbot_new.py
```

## Estrutura do Projeto

```
chatbot/
├── .vscode/
│   └── launch.json          # Configurações de debug (incluído no repositório)
├── chatbotenv/              # Ambiente virtual (não versionado)
├── chatbot_new.py           # Interface principal com PyQt5
├── llm.py                   # Integração com Llama 3.1 via Ollama
├── conversas.csv            # Histórico de conversas (não versionado)
└── requirements.txt         # Dependências Python
```

## Arquivos importantes

- `chatbot_new.py` - Interface principal do chatbot com PyQt5
- `llm.py` - Configuração e integração com Llama 3.1 via Ollama
- `conversas.csv` - Armazena histórico de conversas e avaliações (gerado automaticamente)
- `requirements.txt` - Dependências Python
- `.vscode/launch.json` - Configurações de debug do VS Code (versionado)

## Notas de desenvolvimento

- O projeto foi desenvolvido em Windows com Python 3.9
- Ambiente virtual recomendado para evitar conflitos de dependências
- As configurações de debug do VS Code (`.vscode/launch.json`) estão incluídas no repositório
- Modo UI Only é útil para testar interface sem carregar o LLM (mais rápido)

## Solução de problemas

- Ativação do venv falha no PowerShell: ajuste a política de execução para o usuário atual (executar PowerShell como Administrador se necessário):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- Erros de dependência / ImportError: reinstale os pacotes:

```powershell
pip install -r requirements.txt --force-reinstall
```
