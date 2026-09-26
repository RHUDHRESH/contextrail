"""Deterministic policy engine (CLAUDE.md §9). Rules are YAML; evaluation is plain code over records.

No model output is read here, and no retrieved text: rule paths may only reference the subject record, the
action target, the role catalogue entry, run metadata and (for separation of duties) the decision.
"""
