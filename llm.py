from langchain_community.llms import Ollama
from langchain_community.document_loaders import PyPDFLoader
from langchain.prompts import PromptTemplate
from langchain_community.vectorstores import DocArrayInMemorySearch
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from sys import argv

# 1. Create the model
llm = Ollama(model='llama3')
embeddings = OllamaEmbeddings(model='znbang/bge:small-en-v1.5-f32')

file = '3o_trimestre_2021.pdf'

# 2. Load the PDF file and create a retriever to be used for providing context
loader = PyPDFLoader(file)
pages = loader.load_and_split()
store = DocArrayInMemorySearch.from_documents(pages, embedding=embeddings)
retriever = store.as_retriever()

# 3. Create the prompt template
template = """
Responda as perguntas baseado no contexto fornecido.

Context: {context}

Question: {question}
"""

prompt = PromptTemplate.from_template(template)

def format_docs(docs):
  return "\n\n".join(doc.page_content for doc in docs)

# 4. Build the chain of operations
chain = (
  {
    'context': retriever | format_docs,
    'question': RunnablePassthrough(),
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
