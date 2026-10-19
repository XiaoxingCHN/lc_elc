"""Catalog identity helpers.

The contract fixes one canonical rule:

    catalog_or_bound -> "lcsc:C123"
    unbound_local    -> "lab:42"

Binding state must NEVER change a catalog item's identity, so there is no
"lab:42+lcsc:C123" form here. Normalisation is NFKC + trim + uppercase, and a
code is valid when it is ``C`` followed by positive decimal digits - with NO
minimum digit count (the real data contains short codes such as ``C1``).

Anything null / empty / malformed is INVALID and must never merge.
"""

import re
import unicodedata

# C + one or more digits. Deliberately not 4+ digits: the mall uses short codes.
_CATALOG_RE = re.compile(r"^C([0-9]+)$")


def normalize_catalog_code(value):
    """Return the canonical code ('C123') or None when the value is unusable.

    Never raises: callers treat None as "unbound", which is the safe direction -
    a bad code must not merge two unrelated materials.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", "ignore")
        except Exception:
            return None
    text = unicodedata.normalize("NFKC", str(value))
    # strip everything that is not part of a code: spaces, BOM, zero-width, full-width
    text = text.strip().strip("\ufeff").replace("\u200b", "")
    text = "".join(text.split())
    text = text.upper()
    if not text:
        return None
    m = _CATALOG_RE.match(text)
    if not m:
        return None
    digits = m.group(1)
    # "C0" / "C000" are not real codes; require a positive value
    if int(digits) <= 0:
        return None
    return "C" + digits


def is_valid_catalog_code(value):
    return normalize_catalog_code(value) is not None


def catalog_item_key(code):
    return "lcsc:%s" % code if code else None


def local_item_key(template_id):
    return "lab:%s" % template_id if template_id else None


def parse_item_key(item_key):
    """('lcsc', 'C123') / ('lab', 42) / (None, None)."""
    if not item_key or not isinstance(item_key, str):
        return (None, None)
    if item_key.startswith("lcsc:"):
        code = normalize_catalog_code(item_key[5:])
        return ("lcsc", code) if code else (None, None)
    if item_key.startswith("lab:"):
        raw = item_key[4:].strip()
        return ("lab", int(raw)) if raw.isdigit() else (None, None)
    return (None, None)
