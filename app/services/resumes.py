from sqlalchemy.orm import Session

from app.models.resumes import Resume
from app.repositories.profiles import ProfileRepository
from app.repositories.resumes import ResumeRepository
from app.schemas.resumes import ResumeMetadataInput
from app.services.profiles import ProfileNotFoundError
from app.services.resume_files import ResumeFileStorage


class ResumeNotFoundError(LookupError):
    pass


class ResumeService:
    def __init__(self, session: Session, storage: ResumeFileStorage) -> None:
        self.session = session
        self.storage = storage
        self.profiles = ProfileRepository(session)
        self.resumes = ResumeRepository(session)

    def add_resume(
        self,
        profile_id: int,
        metadata: ResumeMetadataInput,
        original_filename: str,
        content: bytes,
        *,
        make_primary: bool = False,
    ) -> Resume:
        if self.profiles.get_profile(profile_id) is None:
            raise ProfileNotFoundError(f"Profile {profile_id} was not found")

        stored = self.storage.store(original_filename, content)
        try:
            is_first_resume = self.resumes.count_for_profile(profile_id) == 0
            should_be_primary = make_primary or is_first_resume
            if should_be_primary:
                self.resumes.clear_primary(profile_id)

            resume = Resume(
                profile_id=profile_id,
                name=metadata.name,
                file_path=stored.storage_reference,
                extracted_text=stored.extracted_text,
                is_primary=should_be_primary,
            )
            self.resumes.add(resume)
            self.session.commit()
            self.session.refresh(resume)
            return resume
        except Exception:
            self.session.rollback()
            self.storage.remove(stored.storage_reference)
            raise

    def set_primary(self, profile_id: int, resume_id: int) -> Resume:
        resume = self.resumes.get_for_profile(profile_id, resume_id)
        if resume is None:
            raise ResumeNotFoundError(f"Resume {resume_id} was not found")
        self.resumes.clear_primary(profile_id)
        self.resumes.mark_primary(profile_id, resume_id)
        self.session.commit()
        self.session.refresh(resume)
        return resume

    def get_extracted_text(self, profile_id: int, resume_id: int) -> str:
        resume = self.resumes.get_for_profile(profile_id, resume_id)
        if resume is None:
            raise ResumeNotFoundError(f"Resume {resume_id} was not found")
        return resume.extracted_text
