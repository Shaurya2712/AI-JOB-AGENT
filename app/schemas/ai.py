from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Score = Annotated[int, Field(ge=0, le=100)]
ShortText = Annotated[str, Field(min_length=1, max_length=120)]
ConcernText = Annotated[str, Field(min_length=1, max_length=500)]


class AIProfileSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    suggestion_type: Literal["skill", "role"]
    value: ShortText
    rationale: Annotated[str, Field(min_length=1, max_length=2000)]


class AIMatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    overall_score: Score
    role_score: Score | None
    skills_score: Score | None
    experience_score: Score | None
    location_score: Score | None
    freshness_score: Score | None
    seniority_score: Score | None
    salary_score: Score | None
    matching_skills: Annotated[list[ShortText], Field(max_length=50)]
    missing_skills: Annotated[list[ShortText], Field(max_length=50)]
    concerns: Annotated[list[ConcernText], Field(max_length=20)]
    explanation: Annotated[str, Field(min_length=1, max_length=4000)]
    suggested_resume_id: Annotated[int, Field(gt=0)] | None
    profile_suggestions: Annotated[list[AIProfileSuggestion], Field(max_length=10)]
