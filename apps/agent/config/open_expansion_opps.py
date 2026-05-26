"""DQ3 input: hardcoded list of accounts with a known open expansion opp.

Source: build spec §3.1. Case-insensitive trimmed match on Account Name.
Update here (config artifact), never inline.
"""

OPEN_EXPANSION_OPP_ACCOUNTS: tuple[str, ...] = (
    "T. Rowe Price",
    "CrowdStrike",
    "Fullscript",
    "Under Armour",
    "Figma",
    "Turnitin",
    "BigCommerce",
    "Iterable",
    "Tricentis",
    "Postman",
)


def normalize_name(name: str) -> str:
    return " ".join(name.strip().casefold().split())


_NORMALIZED: frozenset[str] = frozenset(normalize_name(n) for n in OPEN_EXPANSION_OPP_ACCOUNTS)


def is_open_opp_account(account_name: str | None) -> bool:
    if not account_name:
        return False
    return normalize_name(account_name) in _NORMALIZED
