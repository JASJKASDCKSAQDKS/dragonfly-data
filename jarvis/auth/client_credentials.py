"""
Credential minting for client portal accounts.

Pure, side-effect-free helpers that turn a business/database name into a
username, an email address and a strong password. Kept separate from the
registry so the generation rules can be unit-tested without touching disk,
the database, or the auth service.
"""

from __future__ import annotations

import re
import secrets

# Unambiguous alphabet for generated passwords — no 0/O, 1/l/I, so a password
# read aloud or retyped by hand does not turn into a support ticket.
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PASSWORD_LENGTH = 16

# Fallback stem when a name contains no usable characters at all.
_SLUG_FALLBACK = "business"

# Usernames/addresses are capped so they stay readable and DB-safe.
_MAX_STEM = 40


def slugify(name: str) -> str:
    """Normalise a business name into a slug: "Mike's Bar & Grill" -> "mikes_bar_grill".

    Lowercases, replaces every run of non-alphanumeric characters with a
    single underscore, trims underscores, and guarantees the result starts
    with a letter (prefixing "business_" when it does not).
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        return ""
    if not slug[0].isalpha():
        slug = f"{_SLUG_FALLBACK}_{slug}"
    return slug[:_MAX_STEM].strip("_")


def username_for(slug: str, taken: set[str]) -> str:
    """Return a unique username based on the slug, appending a number if needed."""
    base = slug or _SLUG_FALLBACK
    candidate = base
    suffix = 2
    while candidate.lower() in taken:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def email_for(slug: str, domain: str, taken: set[str]) -> str:
    """Return a unique email address of the form <slug>@<domain>."""
    base = slug or _SLUG_FALLBACK
    domain = (domain or "clients.seline.example").strip().lstrip("@")
    candidate = f"{base}@{domain}"
    suffix = 2
    while candidate.lower() in taken:
        candidate = f"{base}{suffix}@{domain}"
        suffix += 1
    return candidate


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    """Generate a strong, unambiguous random password.

    Guarantees at least one lowercase letter, one uppercase letter and one
    digit so it satisfies typical composition rules.
    """
    length = max(12, int(length))
    while True:
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password


def generate_db_password() -> str:
    """A high-entropy secret for a MariaDB read-only account."""
    return secrets.token_urlsafe(24)
