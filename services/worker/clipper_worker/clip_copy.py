from pydantic import BaseModel, ConfigDict, Field, field_validator

from clipper_worker.candidate_review import generate_validated_response
from clipper_worker.candidates import CandidateWindow
from clipper_worker.llm import LLMClient
from clipper_worker.prompts import CLIP_COPY_SYSTEM_PROMPT, build_clip_copy_prompt


class ClipCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=80)
    hook_text: str = Field(min_length=3, max_length=120)

    @field_validator("title", "hook_text")
    @classmethod
    def trim_nonblank_text(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Text must not be blank")
        return result


def generate_clip_copy(
    candidate: CandidateWindow,
    llm_client: LLMClient,
    *,
    max_attempts: int = 3,
) -> ClipCopy:
    return generate_validated_response(
        llm_client,
        prompt=build_clip_copy_prompt(candidate),
        system_prompt=CLIP_COPY_SYSTEM_PROMPT,
        response_model=ClipCopy,
        max_attempts=max_attempts,
    )
