"""Redaction must mask synthetic secrets/PII and never leak them downstream."""

from __future__ import annotations

from cer.redaction import redact, redact_text


def test_email_is_masked():
    result = redact("contact alice.admin@example.com now")
    assert "alice.admin@example.com" not in result.text
    assert "[REDACTED:EMAIL]" in result.text
    assert result.counts.get("EMAIL") == 1


def test_ipv4_is_masked():
    result = redact("source host 10.42.13.7 reached out")
    assert "10.42.13.7" not in result.text
    assert "[REDACTED:IP]" in result.text


def test_secret_assignment_value_is_masked_key_kept():
    text = "api_key=sandbox-demo-not-a-real-key-0001"
    result = redact(text)
    assert "sandbox-demo-not-a-real-key-0001" not in result.text
    # The key name survives so the reader knows a secret *was* present.
    assert "api_key" in result.text
    assert "[REDACTED:SECRET]" in result.text


def test_bearer_token_is_masked():
    result = redact("Authorization: Bearer abcdEFGH1234ijklMNOP5678")
    assert "abcdEFGH1234ijklMNOP5678" not in result.text
    assert "[REDACTED:BEARER]" in result.text


def test_aws_key_is_masked():
    result = redact("key AKIAIOSFODNN7EXAMPLE here")
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text


def test_multiple_secrets_counted():
    text = "mail a@b.com and c@d.org from 1.2.3.4 and 5.6.7.8"
    result = redact(text)
    assert result.counts.get("EMAIL") == 2
    assert result.counts.get("IP") == 2
    assert result.total == 4


def test_clean_text_unchanged():
    text = "This paragraph has an access review and reviewed logs."
    result = redact(text)
    assert result.text == text
    assert result.total == 0


def test_redact_text_wrapper_returns_string():
    out = redact_text("email x@y.com")
    assert isinstance(out, str)
    assert "x@y.com" not in out
