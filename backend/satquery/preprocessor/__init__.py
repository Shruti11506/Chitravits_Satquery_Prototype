"""SatQuery preprocessor package.

Bridges existing Preprocessors/ components (satquery_preprocessor.py,
geopandas_agent.py) with the LangGraph agent via typed Pydantic models.

Public surface:
    DataProfile   – physical facts about one processed raster attachment
    AOIContext    – spatial context from a vector attachment
    PreprocessorNode (make_preprocessor_node) – LangGraph node
    build_vlm_context – prompt-building step, separate from DataProfile
"""

from satquery.preprocessor.prompt_builder import build_vlm_context
from satquery.preprocessor.schemas import AOIContext, DataProfile

__all__ = ["DataProfile", "AOIContext", "build_vlm_context"]
