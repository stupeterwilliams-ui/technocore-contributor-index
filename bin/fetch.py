#!/usr/bin/env python3
"""Fetching with three outcomes instead of two.

Every collector here used to ask a question and accept two answers: a value, or nothing. A 404
and a rate-limited 403 and a TLS handshake failure all arrived as the same `None`, and `None`
meant "there is nothing here". So a minute of GitHub being unhappy was recorded, permanently and
silently, as evidence that a person's work does not exist.

That is not a hypothetical. On 2026-09-15 at 22:53 UTC a README fetch for
`AMCONSEIL/technocore-local-signer` failed with `x509: certificate signed by unknown authority`.
The collector wrote `""` — "no evidence this repo is about Technocore" — into its on-disk cache,
where it still sits. That repository's README says "Technocore Local Signer" and mentions both
`technocore.chat` and `did:key`. It qualifies. It has been invisible to the board ever since, and
nothing in the pipeline would ever have looked again.

So: three outcomes, named.

    FOUND        the server answered and here is the answer
    MISSING      the server answered and the answer is "there is nothing here" (404)
    Unavailable  the server did not answer, and we know nothing (raised, never returned)

`MISSING` is a finding. `Unavailable` is the absence of a finding, and a caller that treats it as
one is the bug this module exists to make impossible to write by accident.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time

# Sentinel for a definite negative. Distinct from None, because None is a perfectly good JSON
# value and several endpoints return it; conflating the two is how we got here.
MISSING = object()

# Transport and server failures worth trying again. Deliberately a list of *observed* strings
# rather than a clever regex: every entry here has appeared in state/refresh.log.
_RETRYABLE = (
    "rate limit exceeded",
    "secondary rate limit",
    "was submitted too quickly",
    "abuse detection",
    "connection reset",
    "read tcp",
    "tls:",
    "x509:",
    "timeout",
    "timed out",
    "eof",
    "connection refused",
    "no such host",
    "temporary failure",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "http 500", "http 502", "http 503", "http 504",
)

_NOT_FOUND = re.compile(r"\(HTTP 404\)|HTTP 404\b", re.IGNORECASE)


class Unavailable(Exception):
    """The fetch did not answer. Never catch this to substitute an empty result.

    If you find yourself writing `except Unavailable: return []`, you have just reintroduced the
    bug: an empty list is a claim about the world, and this exception means we have no claim to
    make. Record it as an incident and let the run be judged degraded.
    """

    def __init__(self, what: str, detail: str, retryable: bool = True) -> None:
        super().__init__(f"{what}: {detail}")
        self.what = what
        self.detail = detail
        self.retryable = retryable

    def as_incident(self) -> dict:
        return {"what": self.what, "detail": self.detail[:300]}


class Incidents:
    """Every fetch this run could not complete.

    Carried into `data/raw/incidents.json` and into the corpus manifest, so that "we looked and
    found nothing" and "we could not look" are different published facts rather than the same
    silence. A reader can tell which one they are holding; so can the guard that decides whether
    this run is fit to overwrite the last one.
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, exc: Unavailable) -> None:
        self.rows.append(exc.as_incident())
        print(f"  ! UNAVAILABLE {exc.what}: {exc.detail[:120]}", file=sys.stderr)

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return bool(self.rows)

    def summary(self) -> dict:
        return {"count": len(self.rows), "fetches_that_did_not_answer": self.rows}


def _retryable(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _RETRYABLE)


def _sleep_for_rate_limit() -> float:
    """How long until the limit that just refused us resets.

    The rate_limit endpoint does not itself count against any limit, which is the only reason
    asking is cheaper than guessing. Guessing is what a fixed backoff does, and a fixed backoff
    that is shorter than the window just burns the remaining budget faster.
    """
    probe = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True,
                           timeout=30, check=False)
    if probe.returncode != 0:
        return 20.0
    try:
        resources = json.loads(probe.stdout)["resources"]
    except (ValueError, KeyError):
        return 20.0
    waits = [r["reset"] - time.time() + 2 for r in resources.values() if r.get("remaining") == 0]
    if not waits:
        return 5.0
    return max(2.0, min(70.0, max(waits)))


def gh_json(*args: str, what: str | None = None, attempts: int = 4) -> object:
    """One `gh` call. Returns parsed JSON, returns MISSING on a definite 404, or raises.

    The retry loop exists because the failure it is retrying is the documented behaviour of the
    API rather than an anomaly: GitHub's search endpoints allow 30 requests a minute, code search
    allows 10, and this collector pages four repository queries to exhaustion and a code query on
    top of that. Reproduced on 2026-09-16: six code-search calls in a row and the seventh returns
    `API rate limit exceeded`. Before this module, `search_all` read that refusal as a short final
    page and stopped, silently publishing a corpus missing every page after it.
    """
    label = what or f"gh {' '.join(args[:3])}"
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(["gh", *args], capture_output=True, text=True,
                                    timeout=180, check=False)
        except subprocess.TimeoutExpired:
            last = "gh timed out after 180s"
            if attempt < attempts:
                time.sleep(2 ** attempt)
            continue
        if result.returncode == 0:
            if not result.stdout.strip():
                return None
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                # A 200 whose body is not JSON is the server answering something we cannot use.
                # It is not "nothing here", so it is not MISSING.
                raise Unavailable(label, f"answered with unparseable JSON: {exc}",
                                  retryable=False) from exc
        last = result.stderr.strip() or f"exit {result.returncode}"
        if _NOT_FOUND.search(last):
            return MISSING  # a definite negative, and the only one this layer recognises
        if not _retryable(last) or attempt == attempts:
            raise Unavailable(label, last, retryable=_retryable(last))
        if "rate limit" in last.lower():
            time.sleep(_sleep_for_rate_limit())
        else:
            time.sleep(2 ** attempt)
    raise Unavailable(label, last)


def http_get(url: str, what: str | None = None, attempts: int = 3,
             timeout: int = 40) -> tuple[int, str] | object:
    """Fetch a URL. Returns (200, body), returns MISSING on 404, or raises Unavailable.

    `curl -w %{http_code}` writes `000` when the transfer never happened at all — DNS failure,
    refused connection, TLS rejection, timeout. The old code compared that string against "200",
    found it unequal, and moved on as though the file had been checked and was not there.
    """
    label = what or url
    last = ""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-w", "\n%{http_code}", url],
            capture_output=True, text=True, check=False)
        body, _, status = result.stdout.rpartition("\n")
        status = status.strip()
        if result.returncode != 0 or not status or status == "000":
            last = f"curl exit {result.returncode}: {result.stderr.strip()[:160] or 'no response'}"
        elif status == "200":
            return 200, body
        elif status == "404":
            return MISSING  # the host answered: there is no such file
        else:
            last = f"HTTP {status}"
            if status in ("400", "401", "410", "451"):
                # A definite refusal that will not become a 200 by being asked again. Still
                # Unavailable rather than MISSING: we did not learn that the file is absent.
                raise Unavailable(label, last, retryable=False)
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise Unavailable(label, last)
