import chromadb

# 和你查看脚本路径保持一致
client = chromadb.PersistentClient("chroma_db")
coll = client.get_or_create_collection("test")
coll.add(
    ids=["test1"],
    documents=["测试文本，用来验证持久化是否生效"],
    metadatas=[{"chapter": "测试"}]
)
print("写入完成，不要强制关闭，等程序自己结束")