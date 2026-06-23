#!/usr/bin/env python3
"""ollama-llm-streamlit-agent: terminal chat using the same agent graph as the Streamlit app.

Optional: pass a UTF-8 text file path to enable RAG (search_documents tool).

Logs go to stderr; assistant replies go to stdout.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from config import setup_logging
from ollama_check import OllamaModelsError, ensure_ollama_models

setup_logging()
logger = logging.getLogger("cli")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ollama-llm-streamlit-agent: CLI with optional RAG from a text file.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        metavar="PATH",
        help="UTF-8 text file to index for RAG (optional)",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="text encoding for PATH (default: utf-8)",
    )
    args = parser.parse_args()

    try:
        ensure_ollama_models()
    except OllamaModelsError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    from agent import create_agent
    from rag import create_vector_store

    vectordb = None
    if args.file:
        path = Path(args.file).expanduser().resolve()
        if not path.is_file():
            logger.error("Not a file: %s", path)
            sys.exit(1)
        text = path.read_text(encoding=args.encoding)
        logger.info("RAG: indexing %s (%s chars)", path, len(text))
        vectordb = create_vector_store(text)
        logger.info("RAG: vector store ready")

    logger.info("CLI starting — loading agent graph…")
    graph = create_agent(vectordb)
    thread_id = "cli_session"
    config = {"configurable": {"thread_id": thread_id}}

    rag_line = (
        "RAG: enabled (search_documents)."
        if vectordb is not None
        else "RAG: disabled (pass a text file path to enable)."
    )
    print(
        f"ollama-llm-streamlit-agent (CLI).\n{rag_line}\n"
        "Commands: exit, quit — leave; logs on stderr.\n",
        file=sys.stderr,
    )

    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            logger.info("CLI exiting (EOF or interrupt)")
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            logger.info("CLI exiting (user command)")
            break

        logger.info("User message chars=%s", len(line))
        t0 = time.perf_counter()
        result = graph.invoke(
            {"messages": [{"role": "user", "content": line}]},
            config,
        )
        elapsed = time.perf_counter() - t0

        messages = result.get("messages", [])
        last = messages[-1] if messages else None
        content = getattr(last, "content", None) if last is not None else str(result)
        if content is None:
            content = str(result)

        logger.info(
            "Reply in %.2fs (%s messages in state)",
            elapsed,
            len(messages),
        )
        print(f"\nAssistant ({elapsed:.1f}s):\n{content}\n")


if __name__ == "__main__":
    main()
