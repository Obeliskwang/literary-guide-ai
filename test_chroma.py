from chromadb.utils import embedding_functions
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

# 创建 embedding 函数
embed_fn = embedding_functions.OllamaEmbeddingFunction(
    model_name="mxbai-embed-large",
    url="http://localhost:11434/api/embeddings"
)

# 测试文档
docs = [Document(page_content="这是一个测试文档")]

# 创建向量存储
vectordb = Chroma.from_documents(docs, embedding=embed_fn)
print("✅ 向量存储创建成功！")

# 测试查询
results = vectordb.similarity_search("测试", k=1)
print(f"查询结果: {results}")