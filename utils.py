import streamlit as st
import html
from character_service import generate_mermaid_graph, generate_mermaid_graph_family

# ... 其他导入 ...


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
