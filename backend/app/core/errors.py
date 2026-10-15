from typing import Optional


class AppError(Exception):
    """An error with a stable machine code and a user-facing message."""

    def __init__(self, code: str, message: str, status_code: int = 400, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.hint = hint

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


class JobCancelled(Exception):
    """Raised inside worker code when the user cancelled the job."""


NO_CAPTIONS_MESSAGE = (
    "Captions are not available for this video. Speech-to-text may be used if audio access is permitted."
)
LIVE_UNSUPPORTED_MESSAGE = (
    "This livestream is active, but live transcription is not available through the configured sources."
)
EXTRACTION_FAILED_MESSAGE = "Transcript extraction failed. Please retry or provide a supported media file."
