import logging
import uuid
from pathlib import PureWindowsPath

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Project, Video
from app.db.session import get_session
from app.schemas.project import ProjectCreate, ProjectRead
from app.schemas.video import VideoRead
from app.storage import ObjectStorage, get_object_storage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])


@router.post(
    "/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    project_data: ProjectCreate,
    session: Session = Depends(get_session),
) -> Project:
    project = Project(
        name=project_data.name.strip(),
        description=project_data.description,
    )
    if not project.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project name must not be blank",
        )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.post(
    "/projects/{project_id}/videos",
    response_model=VideoRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_video(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_object_storage),
) -> Video:
    project = session.scalar(select(Project).where(Project.id == project_id))
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    original_filename = (file.filename or "").replace("\\", "/")
    original_filename = PureWindowsPath(original_filename).name
    if not original_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An upload filename is required",
        )

    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must not be empty",
        )

    object_key = f"{project_id}/{uuid.uuid4().hex}"
    try:
        storage.upload_file(file.file, object_key, file.content_type)
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage upload failed",
        ) from error

    video = Video(
        project_id=project_id,
        original_filename=original_filename,
        object_key=object_key,
        content_type=file.content_type,
        size_bytes=size_bytes,
    )
    try:
        session.add(video)
        session.commit()
        session.refresh(video)
    except SQLAlchemyError:
        session.rollback()
        try:
            storage.delete_file(object_key)
        except (BotoCoreError, ClientError):
            logger.exception("Failed to clean up uploaded object %s", object_key)
        raise

    return video
