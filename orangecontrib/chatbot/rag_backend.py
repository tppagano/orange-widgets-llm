import os
import hashlib
from typing import List, Tuple

# =====================
# Configuration
# =====================

VECTOR_DB_DIR = "./vector_store"
LLM_MODEL = "llama3.1:8b"
EMBEDDING_MODEL = "znbang/bge:small-en-v1.5-f32"

# =====================
# Lazy Model Initialization
# =====================

_llm = None
_embeddings = None
_vector_store = None
_retriever = None

def get_llm():
    """Lazy initialization of LLM"""
    from langchain_community.llms import Ollama
    
    global _llm
    if _llm is None:
        _llm = Ollama(
            model=LLM_MODEL,
            num_ctx=4096,
        )
    return _llm

def get_embeddings():
    """Lazy initialization of embeddings"""
    from langchain_community.embeddings import OllamaEmbeddings
    
    global _embeddings
    if _embeddings is None:
        _embeddings = OllamaEmbeddings(
            model=EMBEDDING_MODEL
        )
    return _embeddings

def get_vector_store():
    """Lazy initialization of vector store"""
    from langchain_community.vectorstores import Chroma
    
    global _vector_store
    if _vector_store is None:
        # Ensure directory exists
        os.makedirs(VECTOR_DB_DIR, exist_ok=True)
        _vector_store = Chroma(
            persist_directory=VECTOR_DB_DIR,
            embedding_function=get_embeddings(),
        )
    return _vector_store

def get_retriever():
    """Lazy initialization of retriever"""
    global _retriever
    if _retriever is None:
        _retriever = get_vector_store().as_retriever(search_kwargs={"k": 2})
    return _retriever

def persist_vector_store():
    """Explicitly persist the vector store to disk"""
    vector_store = get_vector_store()
    if hasattr(vector_store, 'persist'):
        vector_store.persist()

def get_vector_store_doc_count():
    """Get the number of documents in the vector store"""
    try:
        vector_store = get_vector_store()
        # Get collection and count
        collection = vector_store._collection
        return collection.count()
    except Exception:
        return 0

def check_vector_store_exists():
    """Check if vector store has any documents"""
    return get_vector_store_doc_count() > 0

def clear_vector_store():
    """Clear all documents from the vector store"""
    global _vector_store, _retriever
    try:
        vector_store = get_vector_store()
        # Get all document IDs and delete them
        collection = vector_store._collection
        ids = collection.get()['ids']
        if ids:
            collection.delete(ids=ids)
        # Reset cached instances
        _retriever = None
        return True
    except Exception as e:
        print(f"Error clearing vector store: {e}")
        return False

def generate_doc_hash(text: str, doc_id: str = "") -> str:
    """Generate a hash for chunk deduplication, scoped to a source document"""
    return hashlib.md5(f"{doc_id}:{text}".encode('utf-8')).hexdigest()

def get_existing_doc_hashes() -> set:
    """Get all document hashes currently in the vector store"""
    try:
        vector_store = get_vector_store()
        collection = vector_store._collection
        results = collection.get(include=['metadatas'])
        hashes = set()
        if results and 'metadatas' in results:
            for metadata in results['metadatas']:
                if metadata and 'doc_hash' in metadata:
                    hashes.add(metadata['doc_hash'])
        return hashes
    except Exception as e:
        print(f"Error getting document hashes: {e}")
        return set()

def get_indexed_documents() -> List[Tuple[str, str]]:
    """Return unique (doc_id, doc_label) pairs for all indexed source documents, sorted by label"""
    try:
        vector_store = get_vector_store()
        collection = vector_store._collection
        results = collection.get(include=['metadatas'])
        seen = {}
        if results and 'metadatas' in results:
            for metadata in results['metadatas']:
                if metadata and 'doc_id' in metadata and 'doc_label' in metadata:
                    doc_id = metadata['doc_id']
                    if doc_id not in seen:
                        seen[doc_id] = metadata['doc_label']
        return sorted(seen.items(), key=lambda x: x[1])
    except Exception as e:
        print(f"Error getting indexed documents: {e}")
        return []

def add_documents_with_tracking(documents_with_metadata):
    """
    Add documents to vector store with hash tracking to avoid duplicates
    
    Args:
        documents_with_metadata: List of tuples (text, metadata_dict)
    
    Returns:
        Tuple of (added_count, skipped_count)
    """
    from langchain.schema import Document
    
    vector_store = get_vector_store()
    existing_hashes = get_existing_doc_hashes()
    
    docs_to_add = []
    added_count = 0
    skipped_count = 0
    
    for text, metadata in documents_with_metadata:
        doc_hash = generate_doc_hash(text, metadata.get("doc_id", ""))
        
        if doc_hash in existing_hashes:
            skipped_count += 1
            continue
        
        # Add hash to metadata
        metadata['doc_hash'] = doc_hash
        docs_to_add.append(Document(page_content=text, metadata=metadata))
        added_count += 1
    
    if docs_to_add:
        vector_store.add_documents(docs_to_add)
        persist_vector_store()
    
    return added_count, skipped_count

# =====================
# Lazy Initialization Helpers
# =====================

def semantic_split(text: str) -> List[str]:
    """
    Primary split: break text into coarse semantic units before size-based splitting.
    Splits on Markdown/plain-text headings, horizontal rules, blank-line-separated
    paragraphs, and list blocks (lines starting with -, *, +, or a number).
    Empty units are discarded.
    """
    import re

    # Normalise line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Split on:
    #   - Markdown headings  (## Heading)
    #   - Setext headings    (underlined with === or ---)
    #   - Horizontal rules   (--- / *** / ===  on their own line)
    #   - Two or more blank lines (section break)
    boundary = re.compile(
        r'(?:^(?:#{1,6})[ \t].+$)'            # ATX headings
        r'|(?:^.+\n[ \t]*(?:={3,}|-{3,})[ \t]*$)'  # Setext headings
        r'|(?:^[ \t]*(?:-{3,}|\*{3,}|={3,})[ \t]*$)'  # Horizontal rules
        r'|(?:\n{2,})',                         # Paragraph / section gaps
        re.MULTILINE,
    )

    # Keep the matched boundary text attached to the unit that precedes it
    # by splitting around matches and stripping empties.
    parts = boundary.split(text)

    # Re-attach list blocks that ended up in the same part
    # (they remain intact because blank-line splitting already separated them)
    units = []
    list_block: List[str] = []
    list_re = re.compile(r'^[ \t]*(?:[-*+]|\d+[.)]) ', re.MULTILINE)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        # If every non-empty line looks like a list item, treat as one block
        non_empty = [l for l in lines if l.strip()]
        if non_empty and all(list_re.match(l) for l in non_empty):
            list_block.append(part)
        else:
            if list_block:
                units.append('\n'.join(list_block))
                list_block = []
            units.append(part)
    if list_block:
        units.append('\n'.join(list_block))

    return units if units else [text]


def get_text_splitter(chunk_size: int = 500, chunk_overlap: int = 75):
    """Secondary size-based splitter applied after semantic_split"""
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

def get_prompt():
    """Get prompt template"""
    from langchain.prompts import PromptTemplate
    
    PROMPT_TEMPLATE = """
Responda as perguntas baseado no contexto fornecido e no histórico da conversa.

Contexto:
{context}

Histórico da conversa:
{chat_history}

Pergunta:
{question}
"""
    return PromptTemplate.from_template(PROMPT_TEMPLATE)

# =====================
# Helpers
# =====================

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def format_chat_history(
    history: List[Tuple[str, str]]
) -> str:
    if not history:
        return "Nenhuma conversa anterior."

    lines = []
    for user, assistant in history:
        lines.append(f"Usuário: {user}")
        lines.append(f"Assistente: {assistant}")
    return "\n".join(lines)

# =====================
# Document Ingestion
# =====================

def ingest_pdfs(file_paths: List[str]) -> None:
    """
    Load PDFs, split them, embed them and persist to disk.
    Safe to call multiple times.
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

    splits = get_text_splitter().split_documents(documents)
    get_vector_store().add_documents(splits)
    persist_vector_store()

# =====================
# Chain Builder
# =====================


def create_chain_with_history(
    chat_history: List[Tuple[str, str]]
):
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnablePassthrough
    
    return (
        {
            "context": get_retriever() | format_docs,
            "question": RunnablePassthrough(),
            "chat_history": lambda _: format_chat_history(chat_history),
        }
        | get_prompt()
        | get_llm()
        | StrOutputParser()
    )

# =====================
# Streaming Support
# =====================

def stream_chain_with_history(chat_history: List[Tuple[str, str]], prompt_text: str, retriever=None, llm=None):
    """
    Yields tokens as they are generated by the LLM for a given prompt and chat history.
    
    Args:
        chat_history: List of (user_msg, bot_response) tuples
        prompt_text: The current user prompt
        retriever: Optional retriever object for RAG. If None, uses get_retriever()
        llm: Optional LLM instance. If None, creates default Ollama
    """
    from langchain_community.llms import Ollama
    from langchain_core.runnables import RunnablePassthrough

    if llm is None:
        llm = Ollama(model=LLM_MODEL, num_ctx=4096)
    
    if retriever is None:
        retriever = get_retriever()
    
    chain = (
        {
            "context": retriever | format_docs,
            "question": RunnablePassthrough(),
            "chat_history": lambda _: format_chat_history(chat_history),
        }
        | get_prompt()
        | llm
    )
    # Use the .stream() method for streaming
    for chunk in chain.stream(prompt_text):
        yield chunk

# =====================
# Example CLI Usage
# =====================

if __name__ == "__main__":
    # Run once to ingest PDFs
    ingest_pdfs(["3o_trimestre_2021.pdf"])

    history = []

    chain = create_chain_with_history(history)

    while True:
        question = input("\nVocê: ")
        if question.lower() in ("exit", "quit"):
            break

        answer = chain.invoke(question)
        print("\nAssistente:", answer)

        history.append((question, answer))
