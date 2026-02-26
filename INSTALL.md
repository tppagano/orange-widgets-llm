# Add-on Orange3 Chatbot - Guia de Instalação

## Escolha seu Gerenciador de Ambiente

Este add-on suporta instalação com **pip** (venv, virtualenv, pyenv) ou **Conda**. Escolha o método que você prefere:

- **[Instalação com pip](#instalação-com-pip)** - Recomendado para usuários de venv, virtualenv, pyenv
- **[Instalação com Conda](#instalação-com-conda)** - Recomendado para usuários Conda, especialmente com GPU

---

## Instalação com pip

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

---

## Instalação com Conda

### 1. Criar e Ativar Ambiente Conda

```bash
# Criar ambiente
conda create -n chatbot python=3.9
conda activate chatbot
```

### 2. Escolher Método de Instalação

#### Opção A: Híbrido Conda + Pip (Recomendado para GPU)

Instale pacotes críticos via conda, especialmente PyTorch para suporte GPU:

```bash
# Instalar Orange3 via conda-forge
conda install -c conda-forge orange3

# Instalar PyTorch via conda (melhor para GPU)
conda install pytorch -c pytorch
# OU para GPU com CUDA:
# conda install pytorch pytorch-cuda=12.1 -c pytorch -c nvidia

# Instalar dependências restantes via pip
pip install langchain-community chromadb sentence-transformers

# Instalar add-on em modo desenvolvimento
pip install -e .
```

#### Opção B: Apenas Pip dentro do Conda

Use apenas pip dentro do ambiente conda:

```bash
# Instalar tudo com pip
pip install Orange3
pip install -e .
```

⚠️ **Aviso**: PyTorch instalado via pip pode ter problemas com GPU. Use a Opção A se precisar de aceleração GPU.

### 3. Configurar Ollama

```bash
# Baixar de https://ollama.ai e instalar

# Baixar modelos necessários
ollama pull llama3.1:8b
ollama pull znbang/bge:small-en-v1.5-f32
```

### 4. Testar o Widget

```bash
# Iniciar Orange3
orange-canvas
```

Então procure a categoria "Chatbot" na caixa de ferramentas de widgets.

### 5. Verificar Instalação

```bash
# Verificar se o Orange3 reconhece o add-on
python -c "from orangecontrib.chatbot import __version__; print(f'Versão do add-on Chatbot: {__version__}')"

# Verificar PyTorch e CUDA (se aplicável)
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA disponível: {torch.cuda.is_available()}')"
```

---

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
# Reinstalar o add-on para garantir que todas as dependências estão instaladas
pip install -e . --force-reinstall

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
