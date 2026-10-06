"""``POST /api/v1/query``: the single entry point for user queries."""

from fastapi import APIRouter, Request

from satquery.api.dependencies import AgentDep, NormalizerDep, SettingsDep
from satquery.api.errors import get_request_id
from satquery.api.openapi import ERROR_RESPONSES, QUERY_OPENAPI_EXTRA
from satquery.api.schemas import QueryResponse
from satquery.api.transport import parse_query_request

router = APIRouter(tags=["query"])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Submit a text or voice query",
    description=(
        "Accepts a typed query (JSON or multipart) or a spoken query (multipart audio upload or "
        "base64 in JSON). Voice is transcribed with the configured speech-to-text provider. "
        "Both are normalised into the same `UserQuery` and handed to the agent."
    ),
    responses=ERROR_RESPONSES,
    openapi_extra=QUERY_OPENAPI_EXTRA,
)
async def submit_query(
    request: Request,
    settings: SettingsDep,
    normalizer: NormalizerDep,
    agent: AgentDep,
) -> QueryResponse:
    raw = await parse_query_request(request, max_audio_bytes=settings.max_audio_bytes)
    user_query = await normalizer.normalize(raw)
    agent_response = await agent.process(user_query)
    return QueryResponse(
        request_id=get_request_id(request),
        user_query=user_query,
        agent=agent_response,
    )
