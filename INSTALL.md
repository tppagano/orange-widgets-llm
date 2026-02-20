# Add-on Orange3 Chatbot - Guia de Instalação

## Início Rápido

### 1. Instalar o Orange3 (se ainda não estiver instalado)

```bash
pip install Orange3
```

### 2. Instalar o Add-on Chatbot

Do diretório do projeto:

```bash
pip install -e .
```

Isso instala o add-on em modo de desenvolvimento, permitindo fazer mudanças e vê-las imediatamente.

### 3. Verificar Instalação

```bash
# Verificar se o Orange3 reconhece o add-on
python -c "from orangecontrib.chatbot import __version__; print(f'Versão do add-on Chatbot: {__version__}')"

# Listar todos os add-ons do Orange3
pip list | grep -i orange
```

A saída esperada deve incluir:
```
Versão do add-on Chatbot: [Versão]
```

### 4. Configurar Ollama

```bash
# Baixar de https://ollama.ai e instalar

# Baixar modelos necessários
ollama pull llama3.1:8b
ollama pull znbang/bge:small-en-v1.5-f32
```

### 5. Testar o Widget

#### Opção A: Visualizar Widget Individualmente

```bash
cd orangecontrib/chatbot/widgets
python owchatbot.py
```

#### Opção B: Iniciar Orange3

```bash
orange-canvas
```

Então procure a categoria "Chatbot" na caixa de ferramentas de widgets.

## Desinstalar

```bash
pip uninstall Orange3-Chatbot
```

## Modo de Desenvolvimento

Se você quer fazer mudanças no código:

```bash
# Instalar em modo editável (já feito no passo 2)
pip install -e .

# Faça suas mudanças no código

# Não é necessário reinstalar - as mudanças têm efeito imediatamente

# Reinicie o Orange3 para ver as mudanças
orange-canvas
```

## Solução de Problemas

### "No module named orangecontrib.chatbot"

- Certifique-se de ter instalado com `pip install -e .` da raiz do projeto
- Verifique seu ambiente Python: `which python` ou `where python`
- Certifique-se de que Orange3 e o add-on estão no mesmo ambiente

### Widget não aparece no Orange3

```bash
# Forçar reinstalação
pip install -e . --force-reinstall

# Limpar cache do Orange3 (se existir)
rm -rf ~/.orange/cache/

# Reiniciar Orange3
orange-canvas
```

### Erros de importação para rag_backend

```bash
# Certifique-se de que todas as dependências estão instaladas
pip install -r requirements.txt

# Verificar ChromaDB
pip show chromadb

# Verificar LangChain
pip show langchain-community
```

## Próximos Passos

- Visualize widgets standalone: `python orangecontrib/chatbot/widgets/owchatbot.py`
- Leia o [README.md](README.md) para arquitetura e uso completo
- Veja [QUICKSTART.md](QUICKSTART.md) para começar rapidamente

## Documentação

- Documentação dos widgets: Veja o README.md na raiz do projeto
- Documentação do Orange3: https://orange-data-mining-library.readthedocs.io/
- Documentação do LangChain: https://python.langchain.com/
