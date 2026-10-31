import os
import hashlib
from typing import List, Tuple

# =====================
# Configuration
# =====================

VECTOR_DB_DIR = "./vector_store"
LLM_MODEL = "llama3.1:8b"
EMBEDDING_MODEL = "znbang/bge:small-en-v1.5-f32"

DEFAULT_PROMPT_INSTRUCTION = (
    "Responda de forma clara e objetiva. "
    "Utilize o contexto recuperado dos documentos quando ele estiver disponível."
)

# =====================
# Lazy Model Initialization
# =====================

_llm = None
_embeddings = None
_vector_store = None
_retriever = None


def get_llm():
    """Lazy initialization of LLM."""
    from langchain_ollama import OllamaLLM

    global _llm
    if _llm is None:
        _llm = OllamaLLM(
            model=LLM_MODEL,
            num_ctx=4096,
        )
    return _llm


def get_embeddings():
    """Lazy initialization of embeddings."""
    from langchain_ollama import OllamaEmbeddings

    global _embeddings
    if _embeddings is None:
        _embeddings = OllamaEmbeddings(
            model=EMBEDDING_MODEL
        )
    return _embeddings


def get_vector_store():
    """Lazy initialization of vector store."""
    from langchain_chroma import Chroma

    global _vector_store
    if _vector_store is None:
        os.makedirs(VECTOR_DB_DIR, exist_ok=True)
        _vector_store = Chroma(
            persist_directory=VECTOR_DB_DIR,
            embedding_function=get_embeddings(),
        )
    return _vector_store


def get_retriever():
    """Lazy initialization of retriever."""
    global _retriever
    if _retriever is None:
        _retriever = get_vector_store().as_retriever(
            search_kwargs={"k": 2}
        )
    return _retriever


def get_vector_store_doc_count():
    """Get the number of documents in the vector store."""
    try:
        vector_store = get_vector_store()
        collection = vector_store._collection
        return collection.count()
    except Exception:
        return 0


def check_vector_store_exists():
    """Check if vector store has any documents."""
    return get_vector_store_doc_count() > 0


def clear_vector_store():
    """Clear all documents from the vector store."""
    global _vector_store, _retriever

    try:
        vector_store = get_vector_store()
        collection = vector_store._collection
        ids = collection.get()["ids"]

        if ids:
            collection.delete(ids=ids)

        _retriever = None
        return True

    except Exception as exc:
        print(f"Error clearing vector store: {exc}")
        return False


def generate_doc_hash(text: str, doc_id: str = "") -> str:
    """Generate a hash for chunk deduplication, scoped to a source document."""
    return hashlib.md5(
        f"{doc_id}:{text}".encode("utf-8")
    ).hexdigest()


def get_existing_doc_hashes() -> set:
    """Get all document hashes currently in the vector store."""
    try:
        vector_store = get_vector_store()
        collection = vector_store._collection
        results = collection.get(include=["metadatas"])

        hashes = set()

        if results and "metadatas" in results:
            for metadata in results["metadatas"]:
                if metadata and "doc_hash" in metadata:
                    hashes.add(metadata["doc_hash"])

        return hashes

    except Exception as exc:
        print(f"Error getting document hashes: {exc}")
        return set()


def get_indexed_documents() -> List[Tuple[str, str]]:
    """
    Return unique (doc_id, doc_label) pairs for all indexed
    source documents, sorted by label.
    """
    try:
        vector_store = get_vector_store()
        collection = vector_store._collection
        results = collection.get(include=["metadatas"])

        seen = {}

        if results and "metadatas" in results:
            for metadata in results["metadatas"]:
                if (
                    metadata
                    and "doc_id" in metadata
                    and "doc_label" in metadata
                ):
                    doc_id = metadata["doc_id"]

                    if doc_id not in seen:
                        seen[doc_id] = metadata["doc_label"]

        return sorted(
            seen.items(),
            key=lambda item: item[1],
        )

    except Exception as exc:
        print(f"Error getting indexed documents: {exc}")
        return []


def add_documents_with_tracking(documents_with_metadata):
    """
    Add documents to vector store with hash tracking to avoid duplicates.

    Args:
        documents_with_metadata:
            List of tuples in the format (text, metadata_dict).

    Returns:
        Tuple of (added_count, skipped_count).
    """
    from langchain_core.documents import Document

    vector_store = get_vector_store()
    existing_hashes = get_existing_doc_hashes()

    docs_to_add = []
    added_count = 0
    skipped_count = 0

    for text, metadata in documents_with_metadata:
        doc_hash = generate_doc_hash(
            text,
            metadata.get("doc_id", ""),
        )

        if doc_hash in existing_hashes:
            skipped_count += 1
            continue

        metadata["doc_hash"] = doc_hash

        docs_to_add.append(
            Document(
                page_content=text,
                metadata=metadata,
            )
        )

        existing_hashes.add(doc_hash)
        added_count += 1

    if docs_to_add:
        vector_store.add_documents(docs_to_add)

    return added_count, skipped_count


# =====================
# Text Splitting
# =====================

def semantic_split(text: str) -> List[str]:
    """
    Primary split: break text into coarse semantic units before
    size-based splitting.

    Splits on Markdown/plain-text headings, horizontal rules,
    blank-line-separated paragraphs, and list blocks.
    """
    import re

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    boundary = re.compile(
        r"(?:^(?:#{1,6})[ \t].+$)"
        r"|(?:^.+\n[ \t]*(?:={3,}|-{3,})[ \t]*$)"
        r"|(?:^[ \t]*(?:-{3,}|\*{3,}|={3,})[ \t]*$)"
        r"|(?:\n{2,})",
        re.MULTILINE,
    )

    parts = boundary.split(text)

    units = []
    list_block: List[str] = []

    list_re = re.compile(
        r"^[ \t]*(?:[-*+]|\d+[.)]) ",
        re.MULTILINE,
    )

    for part in parts:
        part = part.strip()

        if not part:
            continue

        lines = part.splitlines()
        non_empty = [
            line
            for line in lines
            if line.strip()
        ]

        if (
            non_empty
            and all(list_re.match(line) for line in non_empty)
        ):
            list_block.append(part)

        else:
            if list_block:
                units.append("\n".join(list_block))
                list_block = []

            units.append(part)

    if list_block:
        units.append("\n".join(list_block))

    return units if units else [text]


def get_text_splitter(
    chunk_size: int = 500,
    chunk_overlap: int = 75,
):
    """Secondary size-based splitter applied after semantic_split."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )


# =====================
# Prompt
# =====================

def get_prompt():
    """
    Return the prompt template used by the RAG conversation.

    The manual prompt instruction comes from the Prompt widget.
    The question continues to come from the Chatbot.
    """
    from langchain_core.prompts import PromptTemplate

    prompt_template = """
Siga as orientações abaixo ao produzir a resposta.

Orientações do usuário:
{prompt_instruction}

Use o contexto recuperado dos documentos e considere o histórico
da conversa. Não invente informações que não estejam sustentadas
pelo contexto quando a pergunta depender dos documentos.

Contexto recuperado pelo RAG:
{context}

Histórico da conversa:
{chat_history}

Pergunta atual:
{question}

Resposta:
"""

    return PromptTemplate.from_template(
        prompt_template
    )


# =====================
# Formatting Helpers
# =====================

def format_docs(docs):
    """Join retrieved document chunks into a single context string."""
    if not docs:
        return "Nenhum contexto relevante foi recuperado."

    return "\n\n".join(
        doc.page_content
        for doc in docs
    )


def format_chat_history(
    history: List[Tuple[str, str]]
) -> str:
    """Convert chat history tuples into readable text."""
    if not history:
        return "Nenhuma conversa anterior."

    lines = []

    for user, assistant in history:
        lines.append(f"Usuário: {user}")
        lines.append(f"Assistente: {assistant}")

    return "\n".join(lines)


def format_prompt_instruction(
    prompt_instruction: str = "",
) -> str:
    """
    Normalize the manual instruction received from the Prompt widget.
    """
    instruction = (
        prompt_instruction or ""
    ).strip()

    if instruction:
        return instruction

    return DEFAULT_PROMPT_INSTRUCTION


# =====================
# Document Ingestion
# =====================

def ingest_pdfs(file_paths: List[str]) -> None:
    """
    Load PDFs, split them, embed them and persist to disk.

    This function is kept for compatibility with the original CLI flow.
    The Orange widget currently performs its own document ingestion.
    """
    from langchain_community.document_loaders import PyPDFLoader

    documents = []

    for path in file_paths:
        if not os.path.exists(path):
            continue

        loader = PyPDFLoader(path)
        documents.extend(loader.load())

    if not documents:
        return

    splits = get_text_splitter().split_documents(
        documents
    )

    get_vector_store().add_documents(splits)


# =====================
# Chain Builder
# =====================

def create_chain_with_history(
    chat_history: List[Tuple[str, str]],
    prompt_instruction: str = "",
    retriever=None,
    llm=None,
):
    """
    Create a RAG chain using:
    - manual Prompt instruction;
    - retrieved document context;
    - chat history;
    - current question.

    The optional parameters preserve compatibility with the
    original code while allowing the Orange widgets to provide
    their configured Retriever and LLM.
    """
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnablePassthrough

    if retriever is None:
        retriever = get_retriever()

    if llm is None:
        llm = get_llm()

    instruction = format_prompt_instruction(
        prompt_instruction
    )

    return (
        {
            "prompt_instruction": lambda _: instruction,
            "context": retriever | format_docs,
            "question": RunnablePassthrough(),
            "chat_history": lambda _: format_chat_history(
                chat_history
            ),
        }
        | get_prompt()
        | llm
        | StrOutputParser()
    )


# =====================
# Streaming Support
# =====================

def stream_chain_with_history(
    chat_history: List[Tuple[str, str]],
    prompt_text: str,
    retriever=None,
    llm=None,
    prompt_instruction: str = "",
):
    """
    Yield response chunks generated by the LLM.

    Args:
        chat_history:
            List of (user_message, bot_response) tuples.

        prompt_text:
            Current question written in the Chatbot.

        retriever:
            Retriever received from the RAG widget.
            If None, the default retriever is used.

        llm:
            LLM instance configured by the LLM widget.
            If None, the default Ollama model is used.

        prompt_instruction:
            Manual orientation received from the Prompt widget.
    """
    from langchain_ollama import OllamaLLM
    from langchain_core.runnables import RunnablePassthrough

    if llm is None:
        llm = OllamaLLM(
            model=LLM_MODEL,
            num_ctx=4096,
        )

    if retriever is None:
        retriever = get_retriever()

    instruction = format_prompt_instruction(
        prompt_instruction
    )

    chain = (
        {
            "prompt_instruction": lambda _: instruction,
            "context": retriever | format_docs,
            "question": RunnablePassthrough(),
            "chat_history": lambda _: format_chat_history(
                chat_history
            ),
        }
        | get_prompt()
        | llm
    )

    for chunk in chain.stream(prompt_text):
        yield chunk


# =====================
# Example CLI Usage
# =====================

if __name__ == "__main__":
    ingest_pdfs(["3o_trimestre_2021.pdf"])

    history = []

    chain = create_chain_with_history(
        history,
        prompt_instruction=(
            "Responda de forma clara e objetiva."
        ),
    )

    while True:
        question = input("\nVocê: ")

        if question.lower() in ("exit", "quit"):
            break

        answer = chain.invoke(question)

        print("\nAssistente:", answer)

        history.append(
            (question, answer)
        )