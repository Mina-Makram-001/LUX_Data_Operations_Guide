import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Suppress non-critical Google GenAI logs
logging.getLogger("google_genai").setLevel(logging.ERROR)

from langchain_chroma import Chroma
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

load_dotenv()

# Resolve path to ChromaDB
ROOT_DIR = Path(__file__).resolve().parents[2]
CHROMA_PATH = ROOT_DIR / "RAG_src" / "vectorDB" / "chroma_db"

# Initialize vector store & embeddings
embedding_function = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
vectorstore = Chroma(
    persist_directory=str(CHROMA_PATH), 
    embedding_function=embedding_function
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# Initialize Gemini model
llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=os.getenv("GEMINI_API_KEY")
)

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

prompt = ChatPromptTemplate.from_messages([
    ("system", 
     "You are an expert assistant for the LUX Data Operations Guide. "
     "Answer the user's question accurately using only the retrieved documentation context below. "
     "If you do not know the answer based on the context, state that clearly.\n\n"
     "Context:\n{context}"),
    ("human", "{question}")
])

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

def get_rag_response(question: str) -> str:
    try:
        return rag_chain.invoke(question)
    except Exception as e:
        return f"Error executing RAG chain: {str(e)}"