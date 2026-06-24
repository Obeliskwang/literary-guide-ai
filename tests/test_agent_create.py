"""Smoke test: agent graph builds with mocked LangChain create_agent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


@patch("agent.lc_create_agent")
@patch("agent.get_llm")
def test_create_agent_passes_tools_and_prompt(mock_get_llm, mock_lc_create):
    mock_get_llm.return_value = MagicMock(name="llm")
    mock_graph = MagicMock(name="graph")
    mock_lc_create.return_value = mock_graph

    from agent import create_agent

    g = create_agent(vectordb=None)
    assert g is mock_graph
    mock_lc_create.assert_called_once()
    kwargs = mock_lc_create.call_args[1]
    assert "tools" in kwargs
    assert len(kwargs["tools"]) == 2
    assert "system_prompt" in kwargs


@patch("agent.lc_create_agent")
@patch("agent.get_llm")
@patch("agent.build_search_documents_tool")
def test_create_agent_adds_search_when_vectordb(mock_build_search, mock_get_llm, mock_lc_create):
    mock_get_llm.return_value = MagicMock()
    mock_lc_create.return_value = MagicMock()
    mock_vs = MagicMock(name="vectordb")
    search_tool = MagicMock(name="search_tool")
    mock_build_search.return_value = search_tool

    from agent import create_agent

    create_agent(vectordb=mock_vs)
    kwargs = mock_lc_create.call_args[1]
    tools = kwargs["tools"]
    assert search_tool in tools
