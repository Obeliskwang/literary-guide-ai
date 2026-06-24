import streamlit as st
import html
import json
import uuid
from pathlib import Path
from datetime import datetime
from character_service import generate_mermaid_graph, generate_mermaid_graph_family

DATA_DIR = Path(__file__).resolve().parent / "data"
BOOKS_METADATA_FILE = DATA_DIR / "books.json"

def load_books_metadata():
    """加载书籍元数据索引"""
    if not BOOKS_METADATA_FILE.exists():
        return []
    
    try:
        with open(BOOKS_METADATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load books metadata: {e}")
        return []

def save_books_metadata(books):
    """保存书籍元数据索引"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(BOOKS_METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)

def create_new_book(book_name):
    """创建新书籍"""
    books = load_books_metadata()
    book_id = str(uuid.uuid4())[:8]
    
    new_book = {
        "id": book_id,
        "name": book_name,
        "created_at": datetime.now().isoformat(),
        "files": []
    }
    
    books.append(new_book)
    save_books_metadata(books)
    return book_id

def add_file_to_book(book_id, file_name, chunk_count=0):
    """向书籍添加文件记录"""
    books = load_books_metadata()
    for book in books:
        if book["id"] == book_id:
            file_id = str(uuid.uuid4())[:8]
            book["files"].append({
                "id": file_id,
                "name": file_name,
                "uploaded_at": datetime.now().isoformat(),
                "chunk_count": chunk_count
            })
            save_books_metadata(books)
            return file_id
    return None

def remove_file_from_book(book_id, file_id):
    """从书籍中移除文件记录"""
    books = load_books_metadata()
    for book in books:
        if book["id"] == book_id:
            book["files"] = [f for f in book["files"] if f["id"] != file_id]
            save_books_metadata(books)
            return True
    return False

def get_book_by_id(book_id):
    """根据ID获取书籍信息"""
    books = load_books_metadata()
    for book in books:
        if book["id"] == book_id:
            return book
    return None

def delete_book(book_id):
    """删除书籍"""
    books = load_books_metadata()
    books = [b for b in books if b["id"] != book_id]
    save_books_metadata(books)

def get_total_chunk_count(book):
    """获取书籍总分块数"""
    return sum(f.get("chunk_count", 0) for f in book.get("files", []))


def render_mermaid(code, height="600px"):
    """使用 HTML + Mermaid.js 渲染图表"""

    # 转义代码中的特殊字符
    escaped_code = html.escape(code)

    html_string = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js">
        </script>
        <style>
            body {{ margin: 0; padding: 20px; background: white; }}
            #mermaid-container {{
                width: 100%;
                height: {height};
                overflow: auto;
            }}
            .mermaid {{
                text-align: center;
                width: 100%;
            }}
        </style>
    </head>
    <body>
        <div id="mermaid-container">
            <pre class="mermaid">
{escaped_code}
            </pre>
        </div>
        <script>
            mermaid.initialize({{
                startOnLoad: true,
                theme: 'default',
                flowchart: {{
                    useMaxWidth: true,
                    htmlLabels: true,
                    curve: 'basis'
                }},
                themeVariables: {{
                    fontFamily: 'sans-serif'
                }}
            }});
            
            document.addEventListener('DOMContentLoaded', function() {{
                mermaid.run({{nodes: document.querySelectorAll('.mermaid')}});
            }});
        </script>
    </body>
    </html>
    """

    height_int = int(height.replace("px", "")) if "px" in height else 600
    st.components.v1.html(html_string, height=height_int)
