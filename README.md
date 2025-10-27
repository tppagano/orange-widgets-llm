# Chatbot

Este repositório contém um projeto simples de chatbot em Python. Os arquivos principais incluem `chatbot.py`, `chatbot_new.py` e uma interface leve em `llm.py`. Conversas e exemplos podem estar em `conversas.csv`.

## Requisitos

- Python 3.9
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
python3.9 -m venv chatbotenv
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

## Executando o chatbot

Você pode executar os scripts de entrada diretamente. Exemplos:

```powershell
python chatbot.py
```

ou

```powershell
python chatbot_new.py
```

No Linux / macOS, use `python3` se o comando `python` apontar para Python 2.x:

```bash
python3 chatbot.py
# ou
python3 chatbot_new.py
```

Verifique o conteúdo dos arquivos para saber qual script atende melhor ao seu fluxo.

## Arquivos importantes

- `chatbot.py` — script principal (ponto de entrada)
- `chatbot_new.py` — versão alternativa / em desenvolvimento
- `llm.py` — adaptação/integração com LLMs (verificar uso de chaves/variáveis de ambiente)
- `conversas.csv` — registros de conversas / dataset
- `requirements.txt` — dependências Python

## Notas de desenvolvimento

- O projeto foi desenvolvido em Windows com Python 3.9. O diretório `chatbotenv` contém um ambiente virtual de exemplo. Recomenda-se criar seu próprio venv para evitar conflitos de PATH e permissão.
- Se ocorrerem erros de importação, ative o ambiente virtual e reinstale as dependências.

## Solução de problemas

- Ativação do venv falha no PowerShell: ajuste a política de execução para o usuário atual (executar PowerShell como Administrador se necessário):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- Erros de dependência / ImportError: reinstale os pacotes:

```powershell
pip install -r requirements.txt --force-reinstall
```