from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

PROGRESS_RE = re.compile(
    r"""
    ^\s*(?P<bytes>[\d,]+)\s+
    (?P<percent>\d+)%\s+
    (?P<rate_value>[\d.]+)(?P<rate_unit>(?:[kMGT]i?B|[kMGT]B|B))/s\s+
    (?P<eta>\d+:\d{2}:\d{2})
    (?:\s+\(xfr\#(?P<xfr>\d+),\s+to-chk=(?P<to_chk>[\d,]+)/(?P<to_chk_total>[\d,]+)\))?
    \s*$""",
    re.VERBOSE,
)

FILES_RE = re.compile(r"^Number of files:\s+(?P<total>[\d,]+)\s+\(reg:\s+(?P<regular>[\d,]+),\s+dir:\s+(?P<dirs>[\d,]+)\)$")
CREATED_RE = re.compile(r"^Number of created files:\s+(?P<total>[\d,]+)\s+\(reg:\s+(?P<regular>[\d,]+),\s+dir:\s+(?P<dirs>[\d,]+)\)$")
DELETED_RE = re.compile(r"^Number of deleted files:\s+(?P<count>[\d,]+)$")
REGULAR_TRANSFERRED_RE = re.compile(r"^Number of regular files transferred:\s+(?P<count>[\d,]+)$")
SIZE_LINE_RE = re.compile(r"^Total file size:\s+(?P<size>[\d,]+)\s+bytes$")
TRANSFERRED_SIZE_LINE_RE = re.compile(r"^Total transferred file size:\s+(?P<size>[\d,]+)\s+bytes$")
LITERAL_RE = re.compile(r"^Literal data:\s+(?P<size>[\d,]+)\s+bytes$")
MATCHED_RE = re.compile(r"^Matched data:\s+(?P<size>[\d,]+)\s+bytes$")
FILE_LIST_SIZE_RE = re.compile(r"^File list size:\s+(?P<size>[\d,]+)$")
FILE_LIST_GEN_RE = re.compile(r"^File list generation time:\s+(?P<seconds>[\d.]+)\s+seconds$")
FILE_LIST_TRANSFER_RE = re.compile(r"^File list transfer time:\s+(?P<seconds>[\d.]+)\s+seconds$")
TOTAL_SENT_RE = re.compile(r"^Total bytes sent:\s+(?P<sent>[\d,]+)$")
TOTAL_RECEIVED_RE = re.compile(r"^Total bytes received:\s+(?P<received>[\d,]+)$")
FINAL_RATE_RE = re.compile(r"^sent\s+(?P<sent>[\d,]+)\s+bytes\s+received\s+(?P<received>[\d,]+)\s+(?P<rate>[\d,.]+)\s+bytes/sec$")
SPEEDUP_RE = re.compile(r"^total size is\s+(?P<size>[\d,]+)\s+speedup is\s+(?P<speedup>[\d.]+)$")


def parse_int(value: str) -> int:
    return int(value.replace(",", ""))


def parse_float(value: str) -> float:
    return float(value.replace(",", ""))


def parse_eta_to_seconds(eta: str) -> int:
    hours, minutes, seconds = (int(part) for part in eta.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def parse_rate_to_bps(rate_value: str, unit: str) -> float:
    exp = {"k": 1, "M": 2, "G": 3, "T": 4}.get(unit[0], 0)
    return float(rate_value) * (1024.0**exp)


def parse_progress_line(line: str, last_status: Dict[str, Optional[int]]) -> tuple[Optional[Dict], Dict[str, Optional[int]]]:
    match = PROGRESS_RE.match(line)
    if not match:
        return None, last_status

    rate_bps = parse_rate_to_bps(match.group("rate_value"), match.group("rate_unit"))
    eta_human = match.group("eta")
    xfr = int(match.group("xfr")) if match.group("xfr") else last_status["xfr"]
    to_chk = parse_int(match.group("to_chk")) if match.group("to_chk") else last_status["to_check"]
    to_chk_total = parse_int(match.group("to_chk_total")) if match.group("to_chk_total") else last_status["to_check_total"]

    last_status = {"xfr": xfr, "to_check": to_chk, "to_check_total": to_chk_total}
    parsed: Dict[str, object] = {
        "type": "progress",
        "transferred_bytes": parse_int(match.group("bytes")),
        "percent": float(match.group("percent")),
        "rate_bytes_per_sec": rate_bps,
        "rate_human": f"{match.group('rate_value')}{match.group('rate_unit')}/s",
        "eta_seconds": parse_eta_to_seconds(eta_human),
        "eta_human": eta_human,
        "xfr": xfr,
        "to_check": to_chk,
        "to_check_total": to_chk_total,
    }

    return parsed, last_status


SUMMARY_PATTERNS = [
    (
        FILES_RE,
        lambda m, s: s.update(
            number_of_files=parse_int(m.group("total")),
            number_of_files_regular=parse_int(m.group("regular")),
            number_of_files_dirs=parse_int(m.group("dirs")),
        ),
    ),
    (
        CREATED_RE,
        lambda m, s: s.update(
            number_of_created_files=parse_int(m.group("total")),
            number_of_created_files_regular=parse_int(m.group("regular")),
            number_of_created_files_dirs=parse_int(m.group("dirs")),
        ),
    ),
    (DELETED_RE, lambda m, s: s.update(number_of_deleted_files=parse_int(m.group("count")))),
    (REGULAR_TRANSFERRED_RE, lambda m, s: s.update(number_of_regular_files_transferred=parse_int(m.group("count")))),
    (SIZE_LINE_RE, lambda m, s: s.update(total_file_size=parse_int(m.group("size")))),
    (TRANSFERRED_SIZE_LINE_RE, lambda m, s: s.update(total_transferred_file_size=parse_int(m.group("size")))),
    (LITERAL_RE, lambda m, s: s.update(literal_data=parse_int(m.group("size")))),
    (MATCHED_RE, lambda m, s: s.update(matched_data=parse_int(m.group("size")))),
    (FILE_LIST_SIZE_RE, lambda m, s: s.update(file_list_size=parse_int(m.group("size")))),
    (FILE_LIST_GEN_RE, lambda m, s: s.update(file_list_generation_time_seconds=parse_float(m.group("seconds")))),
    (FILE_LIST_TRANSFER_RE, lambda m, s: s.update(file_list_transfer_time_seconds=parse_float(m.group("seconds")))),
    (TOTAL_SENT_RE, lambda m, s: s.update(total_bytes_sent=parse_int(m.group("sent")))),
    (TOTAL_RECEIVED_RE, lambda m, s: s.update(total_bytes_received=parse_int(m.group("received")))),
    (
        FINAL_RATE_RE,
        lambda m, s: s.update(
            summary_bytes_sent=parse_int(m.group("sent")),
            summary_bytes_received=parse_int(m.group("received")),
            summary_rate_bytes_per_sec=parse_float(m.group("rate")),
        ),
    ),
    (
        SPEEDUP_RE,
        lambda m, s: s.update(
            summary_total_size=parse_int(m.group("size")),
            speedup=parse_float(m.group("speedup")),
        ),
    ),
]


def parse_summary_line(line: str, summary: Dict[str, object]) -> bool:
    for regex, updater in SUMMARY_PATTERNS:
        match = regex.match(line)
        if match:
            updater(match, summary)
            return True
    return False


@dataclass
class ProgressUpdate:
    transferred_bytes: int
    percent: float
    total_bytes: Optional[int]


class RsyncOutputParser:
    """Stateful parser for `rsync --info=progress2 --stats` output."""

    def __init__(self) -> None:
        self._summary: Dict[str, object] = {}
        self._last_status: Dict[str, Optional[int]] = {
            "xfr": None,
            "to_check": None,
            "to_check_total": None,
        }

    def parse_line(self, line: str) -> Tuple[Optional[ProgressUpdate], bool]:
        progress, self._last_status = parse_progress_line(line, self._last_status)
        if progress:
            total_bytes = self.total_bytes
            if total_bytes is None and progress["percent"] > 0:
                total_bytes = int(progress["transferred_bytes"] / (progress["percent"] / 100))
            return (
                ProgressUpdate(
                    transferred_bytes=progress["transferred_bytes"],
                    percent=progress["percent"],
                    total_bytes=total_bytes,
                ),
                False,
            )

        summary_updated = parse_summary_line(line, self._summary)
        return None, summary_updated

    @property
    def total_bytes(self) -> Optional[int]:
        total = self._summary.get("total_file_size") or self._summary.get("summary_total_size")
        return int(total) if total is not None else None

    @property
    def transferred_total(self) -> Optional[int]:
        transferred = self._summary.get("total_transferred_file_size")
        return int(transferred) if transferred is not None else None
