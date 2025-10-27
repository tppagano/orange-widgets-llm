from langchain_community.llms import Ollama
from langchain_community.document_loaders import PyPDFLoader
from langchain.prompts import PromptTemplate
from langchain_community.vectorstores import DocArrayInMemorySearch
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sys import argv

# 1. Create the model with context window configuration
llm = Ollama(
    model='llama3.1:8b',
    num_ctx=4096  # Set context window to 4096 tokens
)
embeddings = OllamaEmbeddings(model='znbang/bge:small-en-v1.5-f32')

file = '3o_trimestre_2021.pdf'

# 2. Load the PDF file and create a retriever to be used for providing context
loader = PyPDFLoader(file)
pages = loader.load()

# Split documents into smaller chunks
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,  # Smaller chunks to avoid context overflow
    chunk_overlap=50,
    length_function=len,
)
splits = text_splitter.split_documents(pages)

store = DocArrayInMemorySearch.from_documents(splits, embedding=embeddings)
# Limit retriever to return only top 2 most relevant chunks
retriever = store.as_retriever(search_kwargs={"k": 2})

# 3. Create the prompt template
template = """
Responda as perguntas baseado no contexto fornecido e no histórico da conversa.

Context: {context}

Chat History:
{chat_history}

Question: {question}
"""

prompt = PromptTemplate.from_template(template)

def format_docs(docs):
  return "\n\n".join(doc.page_content for doc in docs)

def format_chat_history(messages):
  """Format chat history from a list of (user_msg, bot_response) tuples"""
  if not messages:
    return "Nenhuma conversa anterior."
  
  formatted = []
  for user_msg, bot_response in messages:
    formatted.append(f"Usuário: {user_msg}")
    formatted.append(f"Assistente: {bot_response}")
  return "\n".join(formatted)

# 4. Build the chain of operations with chat history support
def create_chain_with_history(chat_history):
  """Create a chain that includes chat history"""
  return (
    {
      'context': retriever | format_docs,
      'question': RunnablePassthrough(),
      'chat_history': lambda x: format_chat_history(chat_history),
    }
    | prompt
    | llm
    | StrOutputParser()
  )

# Original chain without history (for backward compatibility)
chain = (
  {
    'context': retriever | format_docs,
    'question': RunnablePassthrough(),
    'chat_history': lambda x: "Nenhuma conversa anterior.",
  }
  | prompt
  | llm
  | StrOutputParser()
)

# 5. Start asking questions and getting answers in a loop
# while True:
#   question = input('O que você precisa saber sobre o documento?\n')
#   print()
#   print(chain.invoke({'question': question}))
#   print()
