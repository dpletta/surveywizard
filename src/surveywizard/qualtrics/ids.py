"""Mint new Qualtrics ID strings.

QSF files contain several ID namespaces with fixed prefixes + length + charset:

| Prefix | Total length | Charset   | Example                   |
|--------|--------------|-----------|---------------------------|
| SV_    | 19 (3 + 16)  | alnum     | SV_abcd1234EFGH5678       |
| QID    | variable     | digits    | QID1, QID17               |
| BL_    | 25 (3 + 22)  | alnum     | BL_0TVPZiEAiZBfCdfABC     |
| FL_    | variable     | digits    | FL_1, FL_14               |
| RS_    | 19 (3 + 16)  | alnum     | RS_...                    |
| UR_    | 19 (3 + 16)  | alnum     | UR_...                    |
| MS_    | 19 (3 + 16)  | alnum     | MS_...                    |
| VE_    | 19 (3 + 16)  | alnum     | VE_...                    |

``IdMinter`` provides a deterministic-with-seed allocator so round-trips
produce reproducible IDs in tests. Seeds are optional for normal use.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field

ALNUM = string.ascii_letters + string.digits


@dataclass
class IdMinter:
    """Stateful allocator for the seven QSF ID namespaces."""

    seed: int | None = None
    _next_qid: int = field(default=1, init=False)
    _next_flow: int = field(default=1, init=False)
    _rng: random.Random = field(default_factory=random.Random, init=False)

    def __post_init__(self) -> None:
        if self.seed is not None:
            self._rng = random.Random(self.seed)

    # ----- integer-suffix IDs

    def qid(self) -> str:
        n = self._next_qid
        self._next_qid += 1
        return f"QID{n}"

    def flow(self) -> str:
        n = self._next_flow
        self._next_flow += 1
        return f"FL_{n}"

    # ----- random-suffix IDs

    def _rand(self, length: int) -> str:
        return "".join(self._rng.choices(ALNUM, k=length))

    def survey(self) -> str:
        return f"SV_{self._rand(16)}"

    def block(self) -> str:
        return f"BL_{self._rand(22)}"

    def response_set(self) -> str:
        return f"RS_{self._rand(16)}"

    def user(self) -> str:
        return f"UR_{self._rand(16)}"

    def message(self) -> str:
        return f"MS_{self._rand(16)}"

    def version(self) -> str:
        return f"VE_{self._rand(16)}"

    def reserve_qid(self, qid: str) -> None:
        """Prevent future ``qid()`` calls from colliding with an existing ID."""
        if not qid.startswith("QID"):
            return
        try:
            n = int(qid[3:])
        except ValueError:
            return
        if n >= self._next_qid:
            self._next_qid = n + 1

    def reserve_flow(self, flow_id: str) -> None:
        if not flow_id.startswith("FL_"):
            return
        try:
            n = int(flow_id[3:])
        except ValueError:
            return
        if n >= self._next_flow:
            self._next_flow = n + 1


__all__ = ["ALNUM", "IdMinter"]
