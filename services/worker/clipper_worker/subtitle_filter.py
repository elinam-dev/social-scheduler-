from pathlib import Path


def build_ass_filter(subtitle_path: str | Path) -> str:
    path = Path(subtitle_path)
    if path.suffix.lower() != ".ass":
        raise ValueError("Subtitle file must have an .ass extension")
    if not path.is_file():
        raise ValueError(f"ASS subtitle file does not exist: {path}")
    escaped_path = (
        path.resolve()
        .as_posix()
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
    return f"subtitles=filename='{escaped_path}'"
