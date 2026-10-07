import json
import logging
import sys

from app.logging_config import JsonLogFormatter, log_timing


def test_json_formatter_includes_structured_fields_but_not_arbitrary_extras() -> None:
    record = logging.LogRecord(
        "clipper",
        logging.INFO,
        __file__,
        10,
        "Pipeline operation completed for https://example.com/video?token=secret",
        (),
        None,
    )
    record.event = "pipeline_operation"
    record.operation = "transcription"
    record.duration_ms = 12.5
    record.video_id = "video-1"
    record.api_key = "must-not-be-logged"
    try:
        raise RuntimeError("Download failed at https://example.com/?token=secret")
    except RuntimeError:
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["level"] == "INFO"
    assert "[URL redacted]" in payload["message"]
    assert "token=secret" not in payload["message"]
    assert payload["event"] == "pipeline_operation"
    assert payload["operation"] == "transcription"
    assert payload["duration_ms"] == 12.5
    assert payload["video_id"] == "video-1"
    assert "[URL redacted]" in payload["exception"]
    assert "token=secret" not in payload["exception"]
    assert "api_key" not in payload


def test_timed_operation_logs_duration_and_reraises_failures(
    caplog,
) -> None:
    logger = logging.getLogger("clipper.timing-test")

    with caplog.at_level(logging.INFO, logger=logger.name):
        with log_timing(logger, "transcription", video_id="video-1"):
            pass

        try:
            with log_timing(logger, "render", clip_id="clip-1"):
                raise RuntimeError("render failed")
        except RuntimeError:
            pass

    records = [record for record in caplog.records if record.name == logger.name]
    assert records[0].operation == "transcription"
    assert records[0].duration_ms >= 0
    assert records[0].status == "succeeded"
    assert records[1].operation == "render"
    assert records[1].duration_ms >= 0
    assert records[1].status == "failed"
    assert records[1].error_type == "RuntimeError"
    assert records[1].exc_info is not None
