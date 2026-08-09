from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData, UploadFile

from app.models.profiles import CandidateProfile
from app.schemas.profiles import (
    DEFAULT_ROLE_SYNONYMS,
    DEFAULT_TARGET_ROLES,
    CandidateProfileInput,
    parse_entries,
)
from app.schemas.resumes import ResumeMetadataInput
from app.services.profiles import ProfileNotFoundError, ProfileService, SuggestionNotPendingError
from app.services.resume_files import ResumeFileError, ResumeFileStorage
from app.services.resumes import ResumeNotFoundError, ResumeService
from app.web.dependencies import get_session
from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/profiles", tags=["profiles"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _base_context(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "request": request,
        "app_name": settings.app_name,
        "active_nav": "profiles",
        "resume_max_mib": settings.resume_max_bytes / (1024 * 1024),
    }


def _default_form_values() -> dict[str, Any]:
    return {
        "name": "",
        "is_active": True,
        "years_experience": "0",
        "target_roles": "\n".join(DEFAULT_TARGET_ROLES),
        "role_synonyms": "\n".join(DEFAULT_ROLE_SYNONYMS),
        "skills": "",
        "preferred_locations": "India\nRemote",
        "work_modes": ["Remote", "Hybrid", "Onsite"],
        "minimum_salary": "",
        "salary_currency": "INR",
        "excluded_keywords": "Internship",
        "notes": "",
    }


def _profile_form_values(profile: CandidateProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "is_active": profile.is_active,
        "years_experience": profile.years_experience,
        "target_roles": "\n".join(profile.target_roles_json),
        "role_synonyms": "\n".join(profile.role_synonyms_json),
        "skills": "\n".join(profile.skills_json),
        "preferred_locations": "\n".join(profile.preferred_locations_json),
        "work_modes": profile.work_modes_json,
        "minimum_salary": profile.minimum_salary if profile.minimum_salary is not None else "",
        "salary_currency": profile.salary_currency,
        "excluded_keywords": "\n".join(profile.excluded_keywords_json),
        "notes": profile.notes,
    }


def _raw_form_values(form: FormData) -> dict[str, Any]:
    return {
        "name": str(form.get("name", "")),
        "is_active": form.get("is_active") == "on",
        "years_experience": str(form.get("years_experience", "0")),
        "target_roles": str(form.get("target_roles", "")),
        "role_synonyms": str(form.get("role_synonyms", "")),
        "skills": str(form.get("skills", "")),
        "preferred_locations": str(form.get("preferred_locations", "")),
        "work_modes": [str(value) for value in form.getlist("work_modes")],
        "minimum_salary": str(form.get("minimum_salary", "")),
        "salary_currency": str(form.get("salary_currency", "INR")),
        "excluded_keywords": str(form.get("excluded_keywords", "")),
        "notes": str(form.get("notes", "")),
    }


def _validated_profile(form_values: dict[str, Any]) -> CandidateProfileInput:
    salary_value = str(form_values["minimum_salary"]).strip()
    minimum_salary: Decimal | None
    try:
        minimum_salary = Decimal(salary_value) if salary_value else None
    except InvalidOperation:
        minimum_salary = None
        form_values["minimum_salary"] = salary_value
        raise ValueError("Minimum salary must be a number") from None

    return CandidateProfileInput(
        name=form_values["name"],
        is_active=form_values["is_active"],
        years_experience=form_values["years_experience"],
        target_roles=parse_entries(form_values["target_roles"]),
        role_synonyms=parse_entries(form_values["role_synonyms"]),
        skills=parse_entries(form_values["skills"]),
        preferred_locations=parse_entries(form_values["preferred_locations"]),
        work_modes=form_values["work_modes"],
        minimum_salary=minimum_salary,
        salary_currency=form_values["salary_currency"],
        excluded_keywords=parse_entries(form_values["excluded_keywords"]),
        notes=form_values["notes"],
    )


def _validation_messages(error: ValidationError | ValueError) -> list[str]:
    if isinstance(error, ValidationError):
        return [str(item["msg"]).removeprefix("Value error, ") for item in error.errors()]
    return [str(error)]


def _render_form(
    request: Request,
    *,
    values: dict[str, Any],
    profile: CandidateProfile | None = None,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    context = _base_context(request)
    context.update({"values": values, "profile": profile, "errors": errors or []})
    return templates.TemplateResponse(
        request=request,
        name="profile_form.html",
        context=context,
        status_code=status_code,
    )


def _render_profiles(
    request: Request,
    session: Session,
    *,
    resume_error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    context = _base_context(request)
    context.update(
        {
            "profiles": ProfileService(session).list_profiles(),
            "resume_error": resume_error,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="profiles.html",
        context=context,
        status_code=status_code,
    )


def _resume_service(request: Request, session: Session) -> ResumeService:
    settings = request.app.state.settings
    storage = ResumeFileStorage(settings.resume_storage_path, settings.resume_max_bytes)
    return ResumeService(session, storage)


@router.get("", response_class=HTMLResponse, name="profiles")
def profiles(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return _render_profiles(request, session)


@router.get("/new", response_class=HTMLResponse, name="new_profile")
def new_profile(request: Request) -> HTMLResponse:
    return _render_form(request, values=_default_form_values())


@router.post("", name="create_profile")
async def create_profile(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    form_values = _raw_form_values(await request.form())
    try:
        profile_data = _validated_profile(form_values)
    except (ValidationError, ValueError) as error:
        return _render_form(
            request,
            values=form_values,
            errors=_validation_messages(error),
            status_code=422,
        )

    profile = ProfileService(session).create_profile(profile_data)
    return RedirectResponse(url=f"/profiles/{profile.id}/edit", status_code=303)


@router.get("/{profile_id}/edit", response_class=HTMLResponse, name="edit_profile")
def edit_profile(
    profile_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    try:
        profile = ProfileService(session).get_profile(profile_id)
    except ProfileNotFoundError:
        return HTMLResponse("Profile not found", status_code=404)
    return _render_form(request, values=_profile_form_values(profile), profile=profile)


@router.post("/{profile_id}/edit", name="update_profile")
async def update_profile(
    profile_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    service = ProfileService(session)
    try:
        profile = service.get_profile(profile_id)
    except ProfileNotFoundError:
        return HTMLResponse("Profile not found", status_code=404)

    form_values = _raw_form_values(await request.form())
    try:
        profile_data = _validated_profile(form_values)
    except (ValidationError, ValueError) as error:
        return _render_form(
            request,
            values=form_values,
            profile=profile,
            errors=_validation_messages(error),
            status_code=422,
        )

    service.update_profile(profile_id, profile_data)
    return RedirectResponse(url="/profiles", status_code=303)


@router.post("/{profile_id}/suggestions/{suggestion_id}/{decision}", name="decide_profile_suggestion")
def decide_profile_suggestion(
    profile_id: int,
    suggestion_id: int,
    decision: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    if decision not in {"accept", "reject"}:
        return HTMLResponse("Unknown suggestion decision", status_code=404)
    try:
        ProfileService(session).decide_suggestion(profile_id, suggestion_id, decision)
    except ProfileNotFoundError:
        return HTMLResponse("Profile suggestion not found", status_code=404)
    except SuggestionNotPendingError:
        return HTMLResponse("Suggestion has already been decided", status_code=409)
    return RedirectResponse(url=f"/profiles#profile-{profile_id}", status_code=303)


@router.post("/{profile_id}/resumes", name="upload_resume")
async def upload_resume(
    profile_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    settings = request.app.state.settings
    form = await request.form(
        max_files=1,
        max_fields=3,
        max_part_size=settings.resume_max_bytes + 1,
    )
    upload = form.get("resume_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _render_profiles(
            request,
            session,
            resume_error="Choose a TXT, PDF, or DOCX resume file",
            status_code=422,
        )

    try:
        content = await upload.read(settings.resume_max_bytes + 1)
        metadata = ResumeMetadataInput(name=str(form.get("resume_name", "")))
        _resume_service(request, session).add_resume(
            profile_id,
            metadata,
            upload.filename,
            content,
            make_primary=form.get("make_primary") == "on",
        )
    except ProfileNotFoundError:
        return HTMLResponse("Profile not found", status_code=404)
    except (ResumeFileError, ValidationError) as error:
        message = (
            _validation_messages(error)[0]
            if isinstance(error, ValidationError)
            else str(error)
        )
        return _render_profiles(
            request,
            session,
            resume_error=message,
            status_code=422,
        )
    finally:
        await upload.close()

    return RedirectResponse(url=f"/profiles#resumes-{profile_id}", status_code=303)


@router.post("/{profile_id}/resumes/{resume_id}/primary", name="set_primary_resume")
def set_primary_resume(
    profile_id: int,
    resume_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    try:
        _resume_service(request, session).set_primary(profile_id, resume_id)
    except ResumeNotFoundError:
        return HTMLResponse("Resume not found", status_code=404)
    return RedirectResponse(url=f"/profiles#resumes-{profile_id}", status_code=303)
