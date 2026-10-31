"""Screen2Code UI Intermediate Representation: schema, validation, canonical serialization, migration."""
from .canonical import canonical_bytes, canonical_dumps, content_hash, derive_id, sha256_hex
from .diagnostics import Diagnostic, Report
from .migrate import MigrationError, migrate
from .schema import json_schema, schema_text
from .validate import derive_completeness, derive_status, quality_report, required_facets, validate
from .vocab import SCHEMA_VERSION

__all__ = [
    "SCHEMA_VERSION", "Diagnostic", "Report", "MigrationError", "canonical_bytes", "canonical_dumps", "content_hash", "derive_completeness",
    "derive_id", "derive_status", "json_schema", "migrate", "quality_report", "required_facets", "schema_text", "sha256_hex", "validate",
]
