"""Validation P06 sans PostgreSQL ; données entièrement fictives."""

import pytest
from pydantic import ValidationError

from backend.app.auth_schemas import DreamUpdate
from backend.app.text_rules import normalize_text
from backend.app.transcript_schemas import TranscriptUpdate


@pytest.mark.parametrize("text", ["", " ", "\t\r\n", "\u2003\u00a0", None,
                                "a" * 20001, "a\x00b", "a\ud800b"])
def test_invalid_text_is_refused(text):
    with pytest.raises(ValueError):
        normalize_text(text)
    with pytest.raises(ValidationError):
        TranscriptUpdate(transcript=text, expected_version=0)


def test_limit_unicode_and_line_endings():
    assert normalize_text("🌙" * 20000) == "🌙" * 20000
    assert normalize_text("  Récit fictif\r\nseconde ligne.  ") == "Récit fictif\nseconde ligne."
    with pytest.raises(ValueError):
        normalize_text(" " * 20000 + "a")
    html = '</textarea><script>alert("fictitious")</script>'
    assert normalize_text(html) == html  # le rendu HTML, pas le texte, sera échappé


@pytest.mark.parametrize("version", [-1, True, "0", None])
def test_expected_version_is_strict(version):
    with pytest.raises(ValidationError):
        TranscriptUpdate(transcript="Récit fictif", expected_version=version)


def test_legacy_payload_cannot_set_version_directly():
    with pytest.raises(ValidationError):
        DreamUpdate(transcript="Récit fictif", text_version=42)
    assert DreamUpdate(transcript="  Récit fictif  ").transcript == "Récit fictif"
