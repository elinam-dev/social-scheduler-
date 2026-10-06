from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class TranscriptSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    language: str = Field(min_length=1)
    language_probability: FiniteFloat = Field(ge=0, le=1)
    duration_seconds: FiniteFloat = Field(gt=0)
    segments: tuple["TranscriptSegmentSchema", ...]


class TranscriptSegmentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat
    text: str
    words: tuple["TranscriptWordSchema", ...]

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranscriptSegmentSchema":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class TranscriptWordSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat
    text: str
    probability: FiniteFloat | None = Field(default=None, ge=0, le=1)
    speaker_id: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranscriptWordSchema":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self
