# Add-on Orange3 Chatbot - Guia de Instalação

Este guia descreve como configurar o ambiente, instalar o add-on, configurar o Ollama e verificar se tudo está funcionando.

## Requisitos

- Python 3.13 (versão utilizada no desenvolvimento e nos testes atuais).
- Orange3 3.40.0 ou compatível.
- Ollama instalado e em execução.
- Git, caso o projeto tenha sido obtido por meio de um repositório.

> **Importante:** o Ollama é instalado separadamente do ambiente Python. Os modelos são baixados e executados pelo próprio Ollama.

---

## 1. Instalação com pip e ambiente virtual

Este é o método recomendado para instalações com `venv`, `virtualenv` ou `pyenv`.

### 1.1. Criar e ativar o ambiente

Na raiz do projeto, execute:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

Se estiver usando pyenv, selecione primeiro a versão desejada:

```bash
pyenv local 3.13
python -m venv .venv
source .venv/bin/activate
```

### 1.2. Instalar as dependências

Atualize o pip e instale as dependências declaradas no projeto:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 1.3. Instalar o add-on em modo de desenvolvimento

Ainda na raiz do projeto:

```bash
python -m pip install -e .
```

A instalação editável permite alterar o código do add-on sem precisar reinstalá-lo a cada mudança.

### 1.4. Verificar a instalação

```bash
# Verificar se o pacote pode ser importado
python -c "from orangecontrib.chatbot import __version__; print(f'Versão do add-on Chatbot: {__version__}')"

# Verificar dependências
python -m pip check

# Listar os pacotes relacionados ao Orange
python -m pip list | grep -i orange
```

O comando `pip check` deve informar que não há dependências quebradas.

---

## 2. Instalação com Conda

Se você prefere gerenciar ambientes com Conda, crie um ambiente Python e instale as dependências do projeto com pip dentro dele.

### 2.1. Criar e ativar o ambiente

```bash
conda create -n chatbot python=3.13
conda activate chatbot
```

### 2.2. Instalar as dependências e o add-on

Na raiz do projeto:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

O `requirements.txt` contém as dependências Python utilizadas pelo projeto. Não é necessário instalar `langchain-community`, PyTorch ou `sentence-transformers` separadamente para o fluxo atual baseado em Ollama.

### 2.3. Verificar a instalação

```bash
python -m pip check
python -c "from orangecontrib.chatbot import __version__; print(f'Versão do add-on Chatbot: {__version__}')"
```

---

## 3. Configurar o Ollama

O Ollama precisa estar instalado e em execução antes de utilizar as funções que consultam os modelos.

Instale o Ollama seguindo as instruções do site oficial:

https://ollama.com/

Depois, baixe os modelos utilizados pelo projeto:

```bash
ollama pull llama3.1:8b
ollama pull znbang/bge:small-en-v1.5-f32
```

Confirme que os modelos estão disponíveis:

```bash
ollama list
```

Se o Ollama não estiver sendo executado como serviço no seu sistema, inicie-o em outro terminal:

```bash
ollama serve
```

Os nomes dos modelos devem corresponder aos configurados em `rag_backend.py`.

---

## 4. Executar o Orange3 e testar o widget

### Opção A: executar o widget individualmente

A partir da raiz do projeto:

```bash
python orangecontrib/chatbot/widgets/owchatbot.py
```

Essa opção é útil para testar a interface do widget durante o desenvolvimento. Dependendo de como o widget importa os módulos do pacote, a execução pelo Orange Canvas pode ser necessária para testar o fluxo completo.

### Opção B: iniciar o Orange Canvas

```bash
orange-canvas
```

Procure a categoria **Chatbot** na caixa de ferramentas de widgets.

### 4.1. Testar o funcionamento

Depois de abrir o widget:

1. Envie uma pergunta e confirme que o modelo do Ollama responde.
2. Carregue um PDF e verifique se o documento é processado e indexado.
3. Faça uma pergunta relacionada ao conteúdo do PDF e confira se o contexto recuperado é relevante.
4. Feche e abra novamente o Orange e verifique se os documentos continuam disponíveis no banco vetorial.

---

## 5. Executar os testes automatizados

Com o ambiente virtual ativado e as dependências instaladas:

```bash
python -m pip install pytest
python -m pytest
```

Os testes automatizados usam mocks para testar componentes sem precisar consultar modelos reais do Ollama ou modificar o banco vetorial utilizado normalmente pela aplicação.

---

## 6. Desinstalar

Para remover o add-on do ambiente Python:

```bash
python -m pip uninstall Orange3-Chatbot
```

Para remover também o ambiente virtual criado na raiz do projeto:

```bash
rm -rf .venv
```

A remoção do ambiente virtual não apaga os arquivos do projeto nem os dados do banco vetorial armazenados fora dele.

---

## 7. Modo de Desenvolvimento

Para trabalhar no código do add-on:

```bash
# Ativar o ambiente virtual
source .venv/bin/activate

# Instalar em modo editável (se ainda não tiver feito)
python -m pip install -e .
```

Faça as alterações nos arquivos do projeto. Como o pacote está instalado em modo editável, não é necessário reinstalá-lo a cada mudança.

Reinicie o Orange Canvas para carregar as alterações:

```bash
orange-canvas
```

---

## 8. Solução de Problemas

### `No module named orangecontrib.chatbot`

- Confirme que o ambiente virtual está ativado.
- Execute `python -m pip install -e .` na raiz do projeto.
- Verifique se o Python usado para instalar o add-on é o mesmo usado para iniciar o Orange:

```bash
which python
python -m pip show Orange3-Chatbot
```

### O widget não aparece no Orange Canvas

Reinstale o add-on no ambiente ativo:

```bash
python -m pip install -e . --force-reinstall
```

Depois, feche e abra novamente o Orange Canvas:

```bash
orange-canvas
```

### Erros de importação ou dependências ausentes

Verifique se há dependências incompatíveis:

```bash
python -m pip check
```

Confira as dependências principais:

```bash
python -m pip show Orange3 langchain-core langchain-ollama langchain-chroma langchain-text-splitters chromadb pypdf
```

Se alguma dependência estiver ausente, reinstale a lista declarada no projeto:

```bash
python -m pip install -r requirements.txt
```

### O Ollama não responde

- Confirme que o Ollama está instalado.
- Verifique se o serviço está em execução.
- Confira se os modelos necessários aparecem em `ollama list`.
- Verifique se os nomes configurados em `rag_backend.py` correspondem aos modelos baixados.

---

## 9. Próximos Passos

- Consulte o [README.md](README.md) para conhecer a arquitetura e o uso do add-on.
- Consulte o [QUICKSTART.md](QUICKSTART.md) para um guia rápido de utilização.

## Documentação

- [Documentação do Orange3](https://orange-data-mining-library.readthedocs.io/)
- [Documentação do LangChain](https://python.langchain.com/)
- [Documentação do Ollama](https://docs.ollama.com/)
