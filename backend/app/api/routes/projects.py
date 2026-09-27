"""Project endpoints -- workspaces grouping chats, knowledge files and custom instructions.

Thin: all logic, ownership checks and counts live in project_service.
"""
from uuid import UUID

from fastapi import APIRouter, File, UploadFile, status

from app.schemas.common import ApiResponse
from app.schemas.projects import (
    ProjectCreate,
    ProjectDeleteResponse,
    ProjectDetail,
    ProjectFileOut,
    ProjectOut,
    ProjectUpdate,
)
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=ApiResponse[list[ProjectOut]], summary="List projects with their real chat/file counts")
def list_projects() -> ApiResponse[list[ProjectOut]]:
    return ApiResponse.ok([ProjectOut(**row) for row in project_service.list_projects()])


@router.post(
    "",
    response_model=ApiResponse[ProjectOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
def create_project(payload: ProjectCreate) -> ApiResponse[ProjectOut]:
    return ApiResponse.ok(ProjectOut(**project_service.create_project(payload)))


@router.get(
    "/{project_id}",
    response_model=ApiResponse[ProjectDetail],
    summary="Get a project with its chats, knowledge files and chat uploads",
)
def get_project(project_id: UUID) -> ApiResponse[ProjectDetail]:
    return ApiResponse.ok(ProjectDetail(**project_service.get_project_detail(str(project_id))))


@router.patch("/{project_id}", response_model=ApiResponse[ProjectOut], summary="Update a project (only the fields sent)")
def update_project(project_id: UUID, payload: ProjectUpdate) -> ApiResponse[ProjectOut]:
    return ApiResponse.ok(ProjectOut(**project_service.update_project(str(project_id), payload)))


@router.delete(
    "/{project_id}",
    response_model=ApiResponse[ProjectDeleteResponse],
    summary="Delete a project and its knowledge files (its chats are kept)",
)
def delete_project(project_id: UUID) -> ApiResponse[ProjectDeleteResponse]:
    project_service.delete_project(str(project_id))
    return ApiResponse.ok(ProjectDeleteResponse(id=project_id))


@router.post(
    "/{project_id}/files",
    response_model=ApiResponse[ProjectFileOut],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a knowledge file to a project (stored in the Satquery bucket)",
)
def upload_project_file(project_id: UUID, file: UploadFile = File(...)) -> ApiResponse[ProjectFileOut]:
    content = file.file.read()
    row = project_service.add_file(str(project_id), (file.filename or "").strip(), content)
    return ApiResponse.ok(ProjectFileOut(**row))


@router.delete(
    "/{project_id}/files/{file_id}",
    response_model=ApiResponse[ProjectDeleteResponse],
    summary="Delete a project knowledge file (row + Storage object)",
)
def delete_project_file(project_id: UUID, file_id: UUID) -> ApiResponse[ProjectDeleteResponse]:
    project_service.delete_file(str(project_id), str(file_id))
    return ApiResponse.ok(ProjectDeleteResponse(id=file_id))
