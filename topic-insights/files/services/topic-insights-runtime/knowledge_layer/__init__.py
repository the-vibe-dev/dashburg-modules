from .client import KnowledgeClient
from .config import KnowledgeConfig
from .records import (
    MAIL_RECORD_TYPES,
    build_record,
    normalize_record_type,
    normalize_tags,
    record_fingerprint,
    redact_mail_content,
    should_write_record,
    validate_record,
)

__all__ = [
    "KnowledgeClient",
    "KnowledgeConfig",
    "MAIL_RECORD_TYPES",
    "build_record",
    "normalize_record_type",
    "normalize_tags",
    "record_fingerprint",
    "redact_mail_content",
    "should_write_record",
    "validate_record",
]
