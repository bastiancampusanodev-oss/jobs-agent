from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


Decision = Literal["APPLY", "SKIP", "REVIEW"]


class JobInfo(BaseModel):
    title: str = ""
    company: str = ""
    client: str | None = None
    url: str | None = None
    location: str | None = None
    modality: str | None = None
    seniority: str | None = None
    contract: str | None = None


class FormAnswer(BaseModel):
    question: str
    answer: str


class JobDecision(BaseModel):
    decision: Decision
    match_score: int = Field(ge=0, le=100)
    job: JobInfo
    cv_id: str | None = None
    salary_usd_monthly: int | None = Field(default=None, ge=0)
    salary_reason: str = ""
    why: str
    hard_gaps: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    form_answers: list[FormAnswer] = Field(default_factory=list)

    # v0.6.11.8 — persisted form constraints
    #
    # Runtime repair/CUSTOM logic stores only simple,
    # JSON-serializable values here:
    # repair_step, provenance, validation counters,
    # learned language/length constraints and human reason.
    form_constraints: dict[str, str | int | bool] = Field(
        default_factory=dict
    )

    interview_defensibility: str

    @model_validator(mode="after")
    def protect_against_invention(self) -> "JobDecision":
        if self.unsupported_claims and self.decision == "APPLY":
            self.decision = "REVIEW"
        if self.decision == "APPLY" and not self.cv_id:
            self.decision = "REVIEW"
        return self
