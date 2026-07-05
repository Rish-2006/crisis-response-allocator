"""
Agents package — exports root_agent for ADK CLI compatibility.

The root_agent is the PlannerAgent, which delegates verified incidents
to the ExecutorAgent via explicit JSON handoff (not sub-agent delegation).
"""

from agents.planner_agent import planner_agent
from agents.executor_agent import executor_agent

# ADK convention: root_agent is the entry point for `adk run` / `adk web`
# Will be None if google-adk is not installed; use orchestrator.py for
# deterministic pipeline execution instead.
root_agent = planner_agent

__all__ = ["root_agent", "planner_agent", "executor_agent"]
