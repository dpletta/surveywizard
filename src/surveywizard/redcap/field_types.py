"""Constants and enum re-exports for REDCap field / validation types."""

from __future__ import annotations

from surveywizard.models.redcap import RedcapFieldType, RedcapValidationType

ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
REDCAP_NS = "https://projectredcap.org"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"

NAMESPACES = {"odm": ODM_NS, "redcap": REDCAP_NS, "xsi": XSI_NS, "ds": DS_NS}

ODM_VERSION = "1.3.1"


def rc_attr(name: str) -> str:
    """Build a Clark-notation attribute name in the redcap: namespace."""
    return f"{{{REDCAP_NS}}}{name}"


__all__ = [
    "DS_NS",
    "NAMESPACES",
    "ODM_NS",
    "ODM_VERSION",
    "REDCAP_NS",
    "XSI_NS",
    "RedcapFieldType",
    "RedcapValidationType",
    "rc_attr",
]
