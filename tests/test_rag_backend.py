import pytest

import orangecontrib.chatbot.rag_backend as backend


@pytest.fixture(autouse=True)
def reset_backend_caches():
    """Prevent cached model/store instances from leaking between tests."""
    backend._llm = None
    backend._embeddings = None
    backend._vector_store = None
    backend._retriever = None
    yield
    backend._llm = None
    backend._embeddings = None
    backend._vector_store = None
    backend._retriever = None


def test_get_llm_uses_ollama_llm(monkeypatch):
    import langchain_ollama

    class FakeOllamaLLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(langchain_ollama, "OllamaLLM", FakeOllamaLLM)

    llm = backend.get_llm()

    assert isinstance(llm, FakeOllamaLLM)
    assert llm.kwargs == {"model": backend.LLM_MODEL, "num_ctx": 4096}
    assert backend.get_llm() is llm  # lazy cache


def test_get_embeddings_uses_ollama_embeddings(monkeypatch):
    import langchain_ollama

    class FakeOllamaEmbeddings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        langchain_ollama, "OllamaEmbeddings", FakeOllamaEmbeddings
    )

    embeddings = backend.get_embeddings()

    assert isinstance(embeddings, FakeOllamaEmbeddings)
    assert embeddings.kwargs == {"model": backend.EMBEDDING_MODEL}
    assert backend.get_embeddings() is embeddings  # lazy cache


def test_get_vector_store_uses_langchain_chroma(monkeypatch, tmp_path):
    import langchain_chroma

    class FakeChroma:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(langchain_chroma, "Chroma", FakeChroma)
    monkeypatch.setattr(backend, "VECTOR_DB_DIR", str(tmp_path / "vector_store"))

    fake_embeddings = object()
    monkeypatch.setattr(backend, "get_embeddings", lambda: fake_embeddings)

    store = backend.get_vector_store()

    assert isinstance(store, FakeChroma)
    assert store.kwargs == {
        "persist_directory": str(tmp_path / "vector_store"),
        "embedding_function": fake_embeddings,
    }
    assert (tmp_path / "vector_store").is_dir()
    assert backend.get_vector_store() is store  # lazy cache


def test_get_retriever_uses_vector_store(monkeypatch):
    class FakeVectorStore:
        def __init__(self):
            self.kwargs = None
            self.retriever = object()

        def as_retriever(self, **kwargs):
            self.kwargs = kwargs
            return self.retriever

    store = FakeVectorStore()
    monkeypatch.setattr(backend, "get_vector_store", lambda: store)

    retriever = backend.get_retriever()

    assert retriever is store.retriever
    assert store.kwargs == {"search_kwargs": {"k": 2}}
    assert backend.get_retriever() is retriever  # lazy cache


def test_create_chain_with_history_without_external_services():
    from langchain_core.documents import Document
    from langchain_core.runnables import RunnableLambda

    retriever = RunnableLambda(
        lambda question: [Document(page_content="Conteúdo recuperado.")]
    )
    fake_llm = RunnableLambda(lambda prompt_value: prompt_value.to_string())

    chain = backend.create_chain_with_history(
        chat_history=[("Oi", "Olá!")],
        prompt_instruction="Responda objetivamente.",
        retriever=retriever,
        llm=fake_llm,
    )

    result = chain.invoke("Qual é o conteúdo?")

    assert "Conteúdo recuperado." in result
    assert "Responda objetivamente." in result
    assert "Usuário: Oi" in result
    assert "Assistente: Olá!" in result
    assert "Qual é o conteúdo?" in result


def test_stream_chain_with_history_without_ollama():
    from langchain_core.documents import Document
    from langchain_core.runnables import RunnableLambda

    retriever = RunnableLambda(
        lambda question: [Document(page_content="Contexto para streaming.")]
    )
    fake_llm = RunnableLambda(lambda prompt_value: prompt_value.to_string())

    chunks = list(
        backend.stream_chain_with_history(
            chat_history=[],
            prompt_text="Pergunta de teste",
            retriever=retriever,
            llm=fake_llm,
            prompt_instruction="Seja breve.",
        )
    )

    result = "".join(chunks)

    assert "Contexto para streaming." in result
    assert "Pergunta de teste" in result
    assert "Seja breve." in result


def test_add_documents_with_tracking_skips_duplicates(monkeypatch):
    class FakeVectorStore:
        def __init__(self):
            self.added_documents = []

        def add_documents(self, documents):
            self.added_documents.extend(documents)

    store = FakeVectorStore()
    monkeypatch.setattr(backend, "get_vector_store", lambda: store)
    monkeypatch.setattr(
        backend,
        "get_existing_doc_hashes",
        lambda: {backend.generate_doc_hash("Já existe", "doc-1")},
    )

    added, skipped = backend.add_documents_with_tracking(
        [
            ("Já existe", {"doc_id": "doc-1", "doc_label": "Documento 1"}),
            ("Novo conteúdo", {"doc_id": "doc-2", "doc_label": "Documento 2"}),
        ]
    )

    assert (added, skipped) == (1, 1)
    assert len(store.added_documents) == 1
    assert store.added_documents[0].page_content == "Novo conteúdo"
    assert store.added_documents[0].metadata["doc_id"] == "doc-2"
    assert "doc_hash" in store.added_documents[0].metadata


def test_text_splitter_respects_chunk_size():
    splitter = backend.get_text_splitter(chunk_size=100, chunk_overlap=10)

    chunks = splitter.split_text("Texto de teste " * 30)

    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_prompt_can_be_formatted():
    prompt = backend.get_prompt()

    result = prompt.format(
        prompt_instruction="Responda objetivamente.",
        context="Contexto de teste.",
        chat_history="Histórico vazio.",
        question="Qual é a pergunta?",
    )

    assert "Contexto de teste." in result
    assert "Qual é a pergunta?" in result


def test_format_docs():
    from langchain_core.documents import Document

    docs = [
        Document(page_content="Documento 1"),
        Document(page_content="Documento 2"),
    ]

    result = backend.format_docs(docs)

    assert result == "Documento 1\n\nDocumento 2"


def test_format_docs_with_no_documents():
    assert backend.format_docs([]) == "Nenhum contexto relevante foi recuperado."


def test_format_chat_history():
    history = [
        ("Olá", "Olá! Como posso ajudar?"),
        ("Tudo bem?", "Tudo ótimo!"),
    ]

    result = backend.format_chat_history(history)

    assert "Usuário: Olá" in result
    assert "Assistente: Olá! Como posso ajudar?" in result
    assert "Usuário: Tudo bem?" in result
    assert "Assistente: Tudo ótimo!" in result


def test_format_empty_chat_history():
    assert backend.format_chat_history([]) == "Nenhuma conversa anterior."


def test_format_prompt_instruction():
    assert (
        backend.format_prompt_instruction("  Minha instrução  ")
        == "Minha instrução"
    )


def test_format_default_prompt_instruction():
    assert (
        backend.format_prompt_instruction("")
        == backend.DEFAULT_PROMPT_INSTRUCTION
    )


def test_generate_doc_hash_is_stable_and_scoped_to_document():
    hash1 = backend.generate_doc_hash("Conteúdo", "documento-1")
    hash2 = backend.generate_doc_hash("Conteúdo", "documento-1")
    hash3 = backend.generate_doc_hash("Conteúdo", "documento-2")

    assert hash1 == hash2
    assert hash1 != hash3
