"""FIX Resend Request Handler — Gap Fill, Resend Request, sequence range management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class SequenceGap:
    """Represents a gap in the FIX message sequence."""

    start: int
    end: int

    @property
    def count(self) -> int:
        return self.end - self.start + 1

    def __str__(self) -> str:
        if self.start == self.end:
            return f"Gap(seq={self.start})"
        return f"Gap(seq={self.start}-{self.end}, count={self.count})"


@dataclass
class GapFillResult:
    """Result of a gap fill operation."""

    filled: List[int] = field(default_factory=list)
    missing: List[int] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return len(self.missing) == 0 and len(self.errors) == 0

    def __str__(self) -> str:
        if self.is_complete:
            return f"GapFill(complete, filled={len(self.filled)})"
        return f"GapFill(incomplete, filled={len(self.filled)}, missing={len(self.missing)})"


class ResendRequestHandler:
    """Manages FIX sequence numbers, gap detection, and resend request handling."""

    def __init__(
        self,
        initial_seq_num: int = 1,
        max_resend_request_size: int = 2500,
    ):
        self.next_seq_num = initial_seq_num
        self.expected_seq_num = initial_seq_num
        self.max_resend_request_size = max_resend_request_size
        self._received_seq_nums: Set[int] = set()
        self._gap_history: List[SequenceGap] = []

    def get_next_seq_num(self) -> int:
        """Get the next sequence number to send."""
        seq = self.next_seq_num
        self.next_seq_num += 1
        return seq

    def reset(self, new_seq_num: int = 1) -> None:
        """Reset sequence numbers (e.g., after logon)."""
        self.next_seq_num = new_seq_num
        self.expected_seq_num = new_seq_num
        self._received_seq_nums.clear()

    def process_incoming(self, msg_seq_num: int) -> Tuple[bool, Optional[SequenceGap]]:
        """Process an incoming message sequence number.

        Returns:
            Tuple of (is_valid, gap_if_any)
        """
        if msg_seq_num < 1:
            return False, None

        if msg_seq_num in self._received_seq_nums:
            return False, None

        self._received_seq_nums.add(msg_seq_num)

        if msg_seq_num == self.expected_seq_num:
            self.expected_seq_num += 1
            return True, None

        if msg_seq_num < self.expected_seq_num:
            return True, None

        gap = SequenceGap(self.expected_seq_num, msg_seq_num - 1)
        self._gap_history.append(gap)
        self.expected_seq_num = msg_seq_num + 1
        return True, gap

    def create_resend_request(self, begin_seq_no: int, end_seq_no: int = 0) -> Dict[str, str]:
        """Create a ResendRequest message body."""
        return {
            "7": str(begin_seq_no),
            "16": str(end_seq_no),
        }

    def create_gap_fill(
        self,
        msg_seq_num: int,
        gap_fill_flag: bool = True,
    ) -> Dict[str, str]:
        """Create a SequenceReset (GapFill) message body."""
        return {
            "36": str(msg_seq_num),
            "123": "Y" if gap_fill_flag else "N",
        }

    def handle_gap_fill(
        self,
        msg_seq_num: int,
        new_seq_no: int,
        gap_fill_flag: bool = True,
    ) -> GapFillResult:
        """Handle an incoming SequenceReset (GapFill) message."""
        result = GapFillResult()

        if gap_fill_flag:
            for seq in range(msg_seq_num, new_seq_no):
                if seq not in self._received_seq_nums:
                    self._received_seq_nums.add(seq)
                    result.filled.append(seq)
                else:
                    result.missing.append(seq)

            if new_seq_no > self.expected_seq_num:
                self.expected_seq_num = new_seq_no
        else:
            self.expected_seq_num = new_seq_no
            self.next_seq_num = new_seq_no

        return result

    def get_gap_history(self) -> List[SequenceGap]:
        return list(self._gap_history)

    def validate_sequence_range(self, begin_seq_no: int, end_seq_no: int) -> List[str]:
        """Validate a sequence range for ResendRequest."""
        errors: List[str] = []

        if begin_seq_no < 1:
            errors.append(f"BeginSeqNo must be >= 1, got {begin_seq_no}")

        if end_seq_no < 0:
            errors.append(f"EndSeqNo must be >= 0, got {end_seq_no}")

        if end_seq_no >= 0 and end_seq_no != 0 and end_seq_no < begin_seq_no:
            errors.append(
                f"EndSeqNo ({end_seq_no}) must be >= BeginSeqNo ({begin_seq_no}) "
                f"or 0 (infinity)"
            )

        if end_seq_no != 0:
            range_size = end_seq_no - begin_seq_no + 1
            if range_size > self.max_resend_request_size:
                errors.append(
                    f"Resend range too large: {range_size} messages "
                    f"(max: {self.max_resend_request_size})"
                )

        return errors
