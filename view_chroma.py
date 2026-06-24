#!/usr/bin/env python
"""
后端查看 Chroma 向量库内容的工具脚本
运行方式: python view_chroma.py
"""

import sys
sys.path.insert(0, '.')

from chromadb import PersistentClient
from llm import get_embeddings

def view_chroma_contents(persist_dir="chroma_db"):
    """查看向量库内容"""
    try:
        # 连接到持久化的向量库
        client = PersistentClient(path=persist_dir)
        
        # 获取所有集合
        collections = client.list_collections()
        
        if not collections:
            print("❌ 向量库为空或不存在")
            return
        
        print("📊 Chroma 向量库内容:")
        print("=" * 60)
        
        for collection in collections:
            print(f"\n📁 集合名称: {collection.name}")
            print(f"📝 文档数量: {collection.count()}")
            
            # 获取所有文档
            result = collection.get()
            docs = result.get('documents', [])
            metadatas = result.get('metadatas', [])
            ids = result.get('ids', [])
            
            if docs:
                print("\n--- 文档详情 ---")
                for i, (doc_id, doc, metadata) in enumerate(zip(ids, docs, metadatas)):
                    print(f"\n[{i+1}] ID: {doc_id}")
                    if metadata:
                        print(f"   章节: {metadata.get('chapter', '未知章节')}")
                        print(f"   起始行: {metadata.get('start_line', '未知')}")
                        print(f"   结束行: {metadata.get('end_line', '未知')}")
                    print(f"   内容预览: {doc[:100]}...")
                    
                    # 只显示前5个文档，避免输出过多
                    if i >= 4:
                        remaining = len(docs) - 5
                        if remaining > 0:
                            print(f"\n   ... 还有 {remaining} 个文档未显示")
                        break
                        
    except Exception as e:
        print(f"❌ 查看向量库失败: {e}")

if __name__ == "__main__":
    view_chroma_contents()
