"""
Tests for the owner's screen.

Two things matter here and neither should ever regress: the upload box must not
accept anything it likes, and the page must be closed when a password is set.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

import app.admin as admin


def test_a_file_name_cannot_contain_a_path():
    """An uploaded name is cleaned before anything is written to disk."""
    # A path is reduced to its last part, so nothing can be written elsewhere.
    assert admin.safe_name("../../.env") == ".env"
    assert admin.safe_name("/etc/passwd") == "passwd"
    assert "/" not in admin.safe_name("a/b/c/policy.pdf")

    # Characters that could confuse a shell or a browser are replaced.
    assert admin.safe_name("policy;rm -rf.pdf") == "policy_rm -rf.pdf"
    assert admin.safe_name('quote"name.pdf') == "quote_name.pdf"

    # Ordinary names survive untouched, and an empty one still gets a name.
    assert admin.safe_name("Rental Agreement (2026).pdf") == "Rental Agreement (2026).pdf"
    assert admin.safe_name("") == "document"


def test_no_password_means_the_page_is_open():
    """Right on a personal machine; the README and handover say when it is not."""
    admin.settings.__dict__["admin_password"] = ""      # frozen dataclass, set directly
    assert admin.require_owner(None) is None


def test_a_password_closes_the_page():
    admin.settings.__dict__["admin_password"] = "yard-office"
    with pytest.raises(HTTPException) as refused:
        admin.require_owner(None)
    assert refused.value.status_code == 401

    with pytest.raises(HTTPException):
        admin.require_owner(HTTPBasicCredentials(username="owner", password="guess"))

    assert admin.require_owner(HTTPBasicCredentials(username="owner", password="yard-office")) is None
    admin.settings.__dict__["admin_password"] = ""      # leave it as we found it
