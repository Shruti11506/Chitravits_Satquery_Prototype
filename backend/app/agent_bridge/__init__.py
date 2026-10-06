"""Bridge from the SatQuery backend job layer to the real SatQuery LangGraph agent.

The backend records analysis jobs (Supabase); this package processes a queued
job by handing it to the sibling ``satquery`` package's ``SatQueryAgent`` -- the
same LangGraph pipeline (understand_query -> preprocess -> plan_tools ->
execute_tools -> aggregate_results -> response_generation) that calls the real
EarthMind / MCD-Mamba inference services. Nothing here fabricates a model
answer: if the agent can't run, the job fails honestly.
"""
