import json
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from clipper_worker.candidates import CandidateWindow
from clipper_worker.llm import LLMClient
from clipper_worker.prompts import (
    CANDIDATE_REVIEW_SYSTEM_PROMPT,
    build_candidate_review_prompt,
)

DEFAULT_MAX_REVIEW_ATTEMPTS = 3
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class CandidateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_strength: FiniteFloat = Field(
        ge=0,
        le=1,
        description="How strongly the opening creates a reason to keep watching.",
    )
    standalone_coherence: FiniteFloat = Field(
        ge=0,
        le=1,
        description="How well the excerpt is understood without earlier context.",
    )
    payoff: FiniteFloat = Field(
        ge=0,
        le=1,
        description="How completely the excerpt delivers its insight or story beat.",
    )
    pacing: FiniteFloat = Field(
        ge=0,
        le=1,
        description=(
            "How efficiently the excerpt progresses without dead air or repetition."
        ),
    )
    standalone: bool
    rationale: str = Field(min_length=1, max_length=500)


class CandidateReviewError(RuntimeError):
    pass


def review_candidate(
    candidate: CandidateWindow,
    llm_client: LLMClient,
    *,
    max_attempts: int = DEFAULT_MAX_REVIEW_ATTEMPTS,
) -> CandidateEvaluation:
    return generate_validated_response(
        llm_client,
        prompt=build_candidate_review_prompt(candidate),
        system_prompt=CANDIDATE_REVIEW_SYSTEM_PROMPT,
        response_model=CandidateEvaluation,
        max_attempts=max_attempts,
    )


def generate_validated_response(
    llm_client: LLMClient,
    *,
    prompt: str,
    system_prompt: str,
    response_model: type[ResponseModel],
    max_attempts: int = DEFAULT_MAX_REVIEW_ATTEMPTS,
) -> ResponseModel:
    if max_attempts <= 0:
        raise ValueError("Maximum validation attempts must be positive")

    schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    current_prompt = (
        f"{prompt}\n\nReturn only a JSON object matching the following schema:\n"
        f"{schema}"
    )
    last_error: ValidationError | None = None
    for attempt in range(max_attempts):
        raw_response = llm_client.generate(
            current_prompt,
            system_prompt=system_prompt,
            temperature=0,
            json_mode=True,
        )
        try:
            return response_model.model_validate_json(raw_response)
        except ValidationError as error:
            last_error = error
            if attempt + 1 < max_attempts:
                current_prompt = (
                    f"{prompt}\n\n"
                    "Your previous response did not validate. Correct the response "
                    "and return only a JSON object matching the following schema:\n"
                    f"{schema}\n"
                    f"Validation issue: {_validation_summary(error)}"
                )

    raise CandidateReviewError(
        f"LLM response failed schema validation after {max_attempts} attempts"
    ) from last_error


def _validation_summary(error: ValidationError) -> str:
    issues = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors(include_input=False)
    ]
    return "; ".join(issues)
