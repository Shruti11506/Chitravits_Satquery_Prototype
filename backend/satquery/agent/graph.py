"""Assemble the SatQuery LangGraph.

    START → understand_query → preprocess → plan_tools → execute_tools
          → aggregate_results → response_generation → END

``plan_tools`` branches: planned tools go to ``execute_tools``; unsupported /
no-image errors skip straight to ``response_generation`` with a structured error.
"""

from __future__ import annotations

import functools

from langgraph.graph import END, START, StateGraph

from satquery.agent.nodes import (
    aggregate_results,
    check_compatibility,
    make_execute_tools_node,
    plan_tools,
    response_generation,
    route_after_compatibility,
    route_after_plan,
    understand_query,
)
from satquery.agent.state import AgentState
from satquery.agent.tools.attachment_resolver import AttachmentResolver
from satquery.agent.tools.earthmind_client import EarthMindClient
from satquery.evidence.node import make_evidence_node
from satquery.preprocessor.node import make_preprocessor_node
from satquery.tools.registry import TOOL_REGISTRY


def build_graph(
    client: EarthMindClient,
    resolver: AttachmentResolver,
    *,
    mcd_mamba_client=None,
    geoground_client=None,
):
    """Build and compile the agent graph with tool collaborators bound in."""
    # Which model tools are actually wired up at runtime. A tool with no client
    # is simply not offered to the planner, so a query that needs it gets an
    # honest "not available" rather than being misrouted to another model.
    bound = {
        "earthmind": client,
        "mcd_mamba": mcd_mamba_client,
        "geoground": geoground_client,
    }
    available_tools: frozenset[str] = frozenset(
        name for name in TOOL_REGISTRY if bound.get(name) is not None
    )

    graph = StateGraph(AgentState)

    graph.add_node("understand_query", understand_query)
    graph.add_node("preprocess", make_preprocessor_node(resolver))
    graph.add_node("check_compatibility", check_compatibility)
    graph.add_node(
        "plan_tools",
        functools.partial(plan_tools, available_tools=available_tools),
    )
    graph.add_node(
        "execute_tools",
        make_execute_tools_node(client, resolver, mcd_mamba_client, geoground_client),
    )
    graph.add_node("aggregate_results", aggregate_results)
    graph.add_node("build_evidence", make_evidence_node())
    graph.add_node("response_generation", response_generation)

    graph.add_edge(START, "understand_query")
    graph.add_edge("understand_query", "preprocess")
    graph.add_edge("preprocess", "check_compatibility")
    # Incompatible task/input combinations are rejected before tool selection;
    # they skip straight to build_evidence with a structured error.
    graph.add_conditional_edges(
        "check_compatibility",
        route_after_compatibility,
        {"plan_tools": "plan_tools", "build_evidence": "build_evidence"},
    )
    # Both branches pass through build_evidence so the response always carries an
    # (possibly empty) evidence package; the error branch simply has no tools to collect.
    graph.add_conditional_edges(
        "plan_tools",
        route_after_plan,
        {"execute_tools": "execute_tools", "response_generation": "build_evidence"},
    )
    graph.add_edge("execute_tools", "aggregate_results")
    graph.add_edge("aggregate_results", "build_evidence")
    graph.add_edge("build_evidence", "response_generation")
    graph.add_edge("response_generation", END)

    return graph.compile()
