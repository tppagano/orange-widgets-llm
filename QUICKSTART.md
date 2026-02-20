# Guia Rápido - Add-on Orange3 Chatbot

## Instalação Rápida

```bash
pip install -e .
orange-canvas
```

> Para instalação detalhada, veja [INSTALL.md](INSTALL.md)

## Primeiro Uso

1. No Orange3, procure a categoria **"Chatbot"** na caixa de ferramentas de widgets
2. Você encontrará três widgets: **Chatbot**, **RAG** e **LLM**
3. Arraste-os para a tela e clique duas vezes para abrir

## Widgets Disponíveis

Os três widgets trabalham juntos em sequência para fornecer o chatbot completo:

### Widget RAG
Sistema de vetorização e recuperação de documentos:
- Carrega documentos PDF/texto
- Armazenamento persistente de vetores em `./vector_store/`
- Verifica automaticamente vetores existentes na inicialização
- Detecção de duplicatas evita reprocessamento
- Opção para limpar o armazenamento de vetores
- **Saída:** Recuperador (para o Widget LLM)

### Widget LLM
Configuração do modelo de linguagem com RAG:
- Recebe o recuperador do Widget RAG
- Configura o modelo de linguagem com capacidades RAG
- **Saída:** Config LLM (para o Widget Chatbot)

### Widget Chatbot
Interface conversacional que usa a configuração LLM:
- Recebe a Config LLM do Widget LLM
- Fornece interface de chat interativa
- **Saída:** Histórico de conversação como Orange Table

## Exemplos Rápidos de Fluxos de Trabalho

### Fluxo de Trabalho Completo
Os três widgets trabalham juntos em sequência:
```
[RAG] → [LLM] → [Chatbot]
```

1. Arraste um widget **RAG** e carregue documentos
2. Clique em "Vectorize Documents"
3. Arraste um widget **LLM** e conecte RAG → LLM
4. Arraste um widget **Chatbot** e conecte LLM → Chatbot
5. Converse com seus documentos!

## Visualizar Widgets Individualmente

```bash
python orangecontrib/chatbot/widgets/owchatbot.py
python orangecontrib/chatbot/widgets/owrag.py
python orangecontrib/chatbot/widgets/owllm.py
```

## Trabalhando com Documentos

### Usando o Widget RAG

1. **Carregar Documentos**
   - Clique no botão "Load PDF/Text Files"
   - Selecione seus documentos
   - Ou conecte uma fonte de dados à entrada Documents

2. **Vetorizar**
   - Clique em "Vectorize Documents"
   - O progresso é mostrado durante o processamento
   - Vetores são salvos automaticamente em `./vector_store/`

3. **Armazenamento Persistente**
   - Vetores persistem entre sessões
   - Na reinicialização, vetores existentes são carregados automaticamente
   - Documentos duplicados são detectados e ignorados
   - Use "Clear Vector Store" para resetar

### Localização do Armazenamento de Vetores
Todos os documentos vetorizados são armazenados no diretório `./vector_store/`.
Este diretório é criado e gerenciado automaticamente.

## Solução de Problemas Rápida

### Widgets não aparecem?
```bash
pip install -e . --force-reinstall
```

### Ollama não configurado?
```bash
ollama pull llama3.1:8b
ollama pull znbang/bge:small-en-v1.5-f32
```

> Para mais detalhes, veja [INSTALL.md](INSTALL.md)

## Próximos Passos

- **[README.md](README.md)** - Documentação completa, arquitetura e uso avançado
- **[INSTALL.md](INSTALL.md)** - Instalação detalhada e solução de problemas
- **[TRANSFORMATION.md](TRANSFORMATION.md)** - Detalhes técnicos da transformação

## Recursos Principais

### Armazenamento Persistente de Vetores
- Vetores são salvos no disco automaticamente
- Recarregados na inicialização do widget
- Não é necessário re-vetorizar entre sessões

### Detecção de Duplicatas
- Documentos são rastreados por hash de conteúdo
- Previne reprocessamento do mesmo conteúdo
- Mostra estatísticas: "Added X chunks, skipped Y duplicates"

Aproveite seu chatbot Orange3 com RAG persistente! 🤖🍊
