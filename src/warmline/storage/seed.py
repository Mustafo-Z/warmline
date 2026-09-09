"""Fictional seed data. SPEC 2.1, SPEC 6.2.

Every person and company below is invented. None of these numbers belongs to a
real subscriber: the UAE numbers are made up, and nothing in this build dials
anything in any case.

The set is chosen so that five different pre-dial block reasons are visible in
the UI on first run, rather than living only in the test suite. Someone
reviewing this project should be able to open the page and see the policy layer
refusing to place calls, with a different reason on each row.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from warmline.storage import repository
from warmline.storage.db import connect, migrate

CONSENT_TERM = timedelta(days=180)

# (id, name, company, role, number, what this row demonstrates)
SEED_PROSPECTS = [
    (
        "psp_0001",
        "Farah Idrissi",
        "Northwind Robotics",
        "Head of Communications",
        "+971501234567",
        "callable",
    ),
    (
        "psp_0002",
        "Omar Farouk",
        "Cedarpoint Analytics",
        "Founder",
        "+971501234568",
        "consent expired",
    ),
    (
        "psp_0003",
        "Priya Raman",
        "Blue Harbour Foods",
        "Marketing Director",
        "+971501234569",
        "consent withdrawn",
    ),
    (
        "psp_0004",
        "Tomas Vlk",
        "Lantern Bio",
        "Chief of Staff",
        "+971501234570",
        "number suppressed",
    ),
    (
        "psp_0005",
        "Aisha Noor",
        "Kestrel Freight",
        "Head of Brand",
        "+971501234571",
        "no consent record",
    ),
    (
        "psp_0006",
        "Daniel Or",
        "Silverpine Energy",
        "Communications Lead",
        "+971505550000",
        "number not on the verified allowlist",
    ),
]


def seed(connection: sqlite3.Connection, now: datetime) -> None:
    """Populate an empty database. Deterministic given `now`."""
    existing = connection.execute("SELECT COUNT(*) AS n FROM prospect").fetchone()["n"]
    if existing:
        raise RuntimeError("database already contains prospects; refusing to seed over them")

    for identifier, name, company, role, number, _demonstrates in SEED_PROSPECTS:
        repository.insert_prospect(
            connection,
            prospect_id=identifier,
            full_name=name,
            company=company,
            role=role,
            phone_e164=number,
            timezone="Asia/Dubai",
            region_profile="AE",
            now=now,
            is_fixture=True,
        )

    evidence = "fictional seed record — no real person, no real agreement"

    # Callable: consent captured a month ago, well inside its 180-day term.
    fresh = now - timedelta(days=30)
    for identifier in ("psp_0001", "psp_0004", "psp_0006"):
        repository.insert_consent(
            connection,
            prospect_id=identifier,
            lawful_basis="test_number_owner_agreement",
            captured_at=fresh,
            expires_at=fresh + CONSENT_TERM,
            evidence=evidence,
            now=now,
        )

    # Expired: captured 200 days ago, so its 180-day term ran out 20 days ago.
    stale = now - timedelta(days=200)
    repository.insert_consent(
        connection,
        prospect_id="psp_0002",
        lawful_basis="explicit_opt_in",
        captured_at=stale,
        expires_at=stale + CONSENT_TERM,
        evidence=evidence,
        now=now,
    )

    # Withdrawn: consent that would otherwise be valid, withdrawn five days ago.
    repository.insert_consent(
        connection,
        prospect_id="psp_0003",
        lawful_basis="explicit_opt_in",
        captured_at=fresh,
        expires_at=fresh + CONSENT_TERM,
        withdrawn_at=now - timedelta(days=5),
        evidence=evidence,
        now=now,
    )

    # psp_0005 gets no consent row at all. That is the point of it.

    repository.add_suppression(
        connection,
        phone_e164="+971501234570",
        reason="do_not_call",
        source="seed",
        note="fictional — seeded so NUMBER_SUPPRESSED is visible on first run",
        now=now,
    )


def main() -> None:
    database = Path("warmline.sqlite3")
    connection = connect(database)
    migrate(connection)
    seed(connection, datetime.now(UTC))

    print(f"seeded {database}")
    for identifier, name, company, _role, number, demonstrates in SEED_PROSPECTS:
        print(f"  {identifier}  {name:<14} {company:<22} {number:<15} {demonstrates}")


if __name__ == "__main__":
    main()
