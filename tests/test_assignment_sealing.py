"""Behavior tests for sealing closed Gradescope assignments."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sync.completion_cache import (
    build_completion_cache,
    sealed_assignments_from_cache,
    validate_completion_cache,
)
from sync.gradescope import (
    AdapterConfig,
    AssignmentRule,
    CachePolicy,
    GradescopeSchemaError,
    MemberRef,
    SealedAssignment,
    SubmissionBatch,
    build_snapshot,
    load_config,
)

RULE = AssignmentRule(
    8603445, "lab3-q1", "lab3-q1-v1", Decimal("3"), 3, (Decimal("1"),) * 3
)
SEALING_RULE = AssignmentRule(
    8603445, "lab3-q1", "lab3-q1-v1", Decimal("3"), 3, (Decimal("1"),) * 3, False, True
)
NOW = "2026-09-22T18:00:00Z"
ROSTER = [
    MemberRef("member-1", "abc123@cornell.edu", "0"),
    MemberRef("member-2", "xy99@cornell.edu", "0"),
]


def payload(scores=(1, 1, 1), *, status="processed", error_code=None, total=None):
    tests = [
        {"score": score, "max_score": 1, "status": None, "output": "irrelevant"}
        for score in scores
    ]
    return {
        "assignment_submission": {"status": status},
        "autograder_results": {
            "error_code": error_code,
            "score": sum(scores) if total is None else total,
            "tests": tests,
            "output": "FAILED PASS",
        },
    }


def config(rule=RULE, *, seal_recheck_hours=24, enabled=True):
    return AdapterConfig(
        1379687,
        (rule,),
        frozenset({"0"}),
        frozenset({"1", "2"}),
        30.0,
        0.0,
        20000,
        10000000,
        1,
        2000,
        500,
        None,
        CachePolicy(
            enabled=enabled,
            lab_contract_canary_each_run=True,
            seal_recheck_hours=seal_recheck_hours,
        ),
    )


class FakeSource:
    """Minimal source that records every read and can report closure."""

    def __init__(self, histories, members=None, signal="accepting_submissions=false"):
        self.histories = histories
        self.members = members if members is not None else ROSTER
        self.signal = signal
        self.calls = []
        self.closure_calls = 0

    def list_members(self):
        return list(self.members)

    def submissions(self, member_id, assignment_id):
        self.calls.append((member_id, assignment_id))
        values = self.histories.get((member_id, assignment_id), [])
        return SubmissionBatch(len(values), iter(values))

    def assignment_closure(self):
        self.closure_calls += 1
        return {8603445: self.signal}


def fingerprint_for(cfg, rule=None):
    """Fingerprint via the real cache helper so seals match production."""
    from sync.completion_cache import lab_contract_fingerprint

    return lab_contract_fingerprint(cfg, rule or cfg.assignments[0])


# ---------------------------------------------------------------- sealing


def test_open_assignment_is_read_normally_and_not_sealed():
    source = FakeSource(
        {
            ("member-1", 8603445): [payload()],
            ("member-2", 8603445): [payload((0, 0, 0))],
        },
        signal="accepting_submissions=true",
    )
    cfg = config(SEALING_RULE)
    snapshot, seals = build_snapshot(
        source, cfg, generated_at=NOW, contract_fingerprint=lambda r: fingerprint_for(cfg, r)
    )
    assert seals == {}
    assert len(source.calls) == 2
    statuses = {s["netid"]: s["autograders"][0]["status"] for s in snapshot["students"]}
    assert statuses == {"abc123": "passed", "xy99": "failed"}


def test_closed_assignment_seals_after_one_full_check():
    source = FakeSource(
        {
            ("member-1", 8603445): [payload()],
            ("member-2", 8603445): [payload((0, 0, 0))],
        }
    )
    cfg = config(SEALING_RULE)
    snapshot, seals = build_snapshot(
        source, cfg, generated_at=NOW, contract_fingerprint=lambda r: fingerprint_for(cfg, r)
    )
    # First closed run still reads every member.
    assert len(source.calls) == 2
    assert set(seals) == {"lab3-q1"}
    assert seals["lab3-q1"].results == {"abc123": "passed", "xy99": "failed"}
    assert seals["lab3-q1"].closure_signal == "accepting_submissions=false"


def test_sealed_assignment_is_never_read_again():
    cfg = config(SEALING_RULE)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "failed"},
    )
    source = FakeSource({})
    snapshot, seals = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        sealed_assignments={"lab3-q1": seal},
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    # Zero Gradescope submission reads, and no closure probe was needed.
    assert source.calls == []
    assert source.closure_calls == 0
    statuses = {s["netid"]: s["autograders"][0]["status"] for s in snapshot["students"]}
    assert statuses == {"abc123": "passed", "xy99": "failed"}
    assert set(seals) == {"lab3-q1"}


def test_seal_preserves_failed_students_not_just_passes():
    """The positive-only cache cannot express this; the seal must."""
    cfg = config(SEALING_RULE)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "not_submitted"},
    )
    source = FakeSource({})
    snapshot, _ = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        sealed_assignments={"lab3-q1": seal},
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    statuses = {s["netid"]: s["autograders"][0]["status"] for s in snapshot["students"]}
    assert statuses["xy99"] == "not_submitted"


def test_changed_contract_invalidates_a_seal():
    """A score bump must not let a sealed table serve results under a new contract."""
    cfg = config(SEALING_RULE)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint="sha256:" + "0" * 64,
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "failed"},
    )
    source = FakeSource(
        {("member-1", 8603445): [payload()], ("member-2", 8603445): [payload((0, 0, 0))]}
    )
    metrics: dict[str, int] = {}
    _snapshot, seals = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        sealed_assignments={"lab3-q1": seal},
        metrics=metrics,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert metrics["lab_seals_invalidated"] == 1
    # Re-read from source rather than trusting the stale table.
    assert len(source.calls) == 2
    # The assignment is genuinely closed, so it is re-sealed immediately under
    # the NEW fingerprint rather than being left unsealed.
    assert set(seals) == {"lab3-q1"}
    assert seals["lab3-q1"].fingerprint == fingerprint_for(cfg)
    assert seals["lab3-q1"].results == {"abc123": "passed", "xy99": "failed"}


def test_seal_is_rechecked_after_the_recheck_window():
    """A stale seal is re-read once so a reopened assignment is noticed."""
    cfg = config(SEALING_RULE, seal_recheck_hours=1)
    old = (datetime.now(timezone.utc).replace(microsecond=0) - __import__("datetime").timedelta(hours=5))
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=old.isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "failed"},
    )
    source = FakeSource(
        {("member-1", 8603445): [payload()], ("member-2", 8603445): [payload((0, 0, 0))]}
    )
    metrics: dict[str, int] = {}
    _snapshot, seals = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        sealed_assignments={"lab3-q1": seal},
        metrics=metrics,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert metrics["lab_seal_checks"] == 1
    assert len(source.calls) == 2
    assert set(seals) == {"lab3-q1"}


def test_fresh_seal_is_not_reread_before_the_window():
    cfg = config(SEALING_RULE, seal_recheck_hours=24)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "failed"},
    )
    source = FakeSource({})
    metrics: dict[str, int] = {}
    build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        sealed_assignments={"lab3-q1": seal},
        metrics=metrics,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert source.calls == []
    assert metrics["lab_seal_checks"] == 0


def test_seal_without_opt_in_is_never_created():
    """seal_when_closed defaults to false, so nothing changes silently."""
    source = FakeSource(
        {("member-1", 8603445): [payload()], ("member-2", 8603445): [payload((0, 0, 0))]}
    )
    cfg = config(RULE)
    _snapshot, seals = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert seals == {}
    assert source.closure_calls == 0


def test_roster_member_missing_from_a_seal_fails_closed():
    """A late-joining student must not be silently dropped from a sealed table."""
    cfg = config(SEALING_RULE)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed"},
    )
    source = FakeSource({})
    with pytest.raises(GradescopeSchemaError, match="no result for a roster member"):
        build_snapshot(
            source,
            cfg,
            generated_at=NOW,
            sealed_assignments={"lab3-q1": seal},
            contract_fingerprint=lambda r: fingerprint_for(cfg, r),
        )


def test_canary_is_skipped_for_a_sealed_assignment():
    """Sealing supersedes the contract canary for that assignment."""
    cfg = config(SEALING_RULE)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "failed"},
    )
    source = FakeSource({})
    metrics: dict[str, int] = {}
    build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        sealed_assignments={"lab3-q1": seal},
        metrics=metrics,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert metrics["lab_canary_checks"] == 0
    assert metrics["lab_source_checks"] == 0


# ---------------------------------------------------------------- persistence


def test_seal_survives_a_cache_round_trip():
    cfg = config(SEALING_RULE)
    seal = SealedAssignment(
        opportunity_id="lab3-q1",
        fingerprint=fingerprint_for(cfg),
        sealed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        closure_signal="accepting_submissions=false",
        results={"abc123": "passed", "xy99": "failed"},
    )
    source = FakeSource(
        {("member-1", 8603445): [payload()], ("member-2", 8603445): [payload((0, 0, 0))]}
    )
    snapshot, seals = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    cache = build_completion_cache(cfg, snapshot, frozenset(), sealed=seals)
    assert validate_completion_cache(cache, config=cfg) == []
    restored = sealed_assignments_from_cache(cache)
    assert restored["lab3-q1"]["results"] == {"abc123": "passed", "xy99": "failed"}
    # And the restored table is servable with zero further reads.
    follow = FakeSource({})
    _snap, active = build_snapshot(
        follow,
        cfg,
        generated_at=NOW,
        sealed_assignments=restored,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert follow.calls == []
    assert set(active) == {"lab3-q1"}


def test_cache_rejects_a_seal_whose_fingerprint_drifted():
    cfg = config(SEALING_RULE)
    snapshot, seals = build_snapshot(
        FakeSource(
            {("member-1", 8603445): [payload()], ("member-2", 8603445): [payload((0, 0, 0))]}
        ),
        cfg,
        generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    cache = build_completion_cache(cfg, snapshot, frozenset(), sealed=seals)
    tampered = dict(cache)
    tampered["sealed_assignments"] = {
        "lab3-q1": {**cache["sealed_assignments"]["lab3-q1"],
                    "fingerprint": "sha256:" + "1" * 64}
    }
    assert any("fingerprint" in e for e in validate_completion_cache(tampered, config=cfg))


def test_cache_rejects_an_invalid_sealed_status():
    cfg = config(SEALING_RULE)
    snapshot, seals = build_snapshot(
        FakeSource(
            {("member-1", 8603445): [payload()], ("member-2", 8603445): [payload((0, 0, 0))]}
        ),
        cfg,
        generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    cache = build_completion_cache(cfg, snapshot, frozenset(), sealed=seals)
    bad = dict(cache)
    bad["sealed_assignments"] = {
        "lab3-q1": {**cache["sealed_assignments"]["lab3-q1"],
                    "results": {"abc123": "definitely-passed"}}
    }
    assert any("status" in e for e in validate_completion_cache(bad, config=cfg))


# ---------------------------------------------------------------- closure parsing


def test_closure_page_parses_the_authoritative_flag():
    import json as _json

    from sync.gradescope import PrivateWebGradescopeSource

    rows = [{
        "id": 8603445,
        "submission_window": {"accepting_submissions": False, "close": "2026-09-22T04:59:59Z"},
    }]
    html = (
        '<div data-react-class="AssignmentsTable" data-react-props=\''
        + _json.dumps({"table_data": rows})
        + "\'></div>"
    )

    class FakeSoup:
        def __init__(self, text, parser):
            from bs4 import BeautifulSoup

            self._soup = BeautifulSoup(text, parser)

        def find(self, *args, **kwargs):
            return self._soup.find(*args, **kwargs)

    class FakeResponse:
        text = html

    source = PrivateWebGradescopeSource.__new__(PrivateWebGradescopeSource)
    source._soup_type = FakeSoup
    source.config = config(SEALING_RULE)
    source._get = lambda url, *, content_type: FakeResponse()
    assert source.assignment_closure() == {8603445: "accepting_submissions=false"}


def test_closure_page_falls_back_to_window_close():
    import json as _json

    from sync.gradescope import PrivateWebGradescopeSource

    rows = [{"id": 8603445, "submission_window": {"close": "2026-01-01T00:00:00Z"}}]
    html = (
        '<div data-react-class="AssignmentsTable" data-react-props=\''
        + _json.dumps({"table_data": rows})
        + "\'></div>"
    )

    class FakeSoup:
        def __init__(self, text, parser):
            from bs4 import BeautifulSoup

            self._soup = BeautifulSoup(text, parser)

        def find(self, *args, **kwargs):
            return self._soup.find(*args, **kwargs)

    class FakeResponse:
        text = html

    source = PrivateWebGradescopeSource.__new__(PrivateWebGradescopeSource)
    source._soup_type = FakeSoup
    source.config = config(SEALING_RULE)
    source._get = lambda url, *, content_type: FakeResponse()
    signals = source.assignment_closure()
    assert signals[8603445].startswith("window_close=")


# ---------------------------------------------------------------- config


def test_config_requires_the_new_keys(tmp_path):
    import tomllib

    example = tomllib.loads(
        open("deployment/gradescope.toml.example", "rb").read().decode("utf-8")
    )
    assert "seal_recheck_hours" in example["cache"]
    for block in example["assignments"].values():
        assert "seal_when_closed" in block
        assert isinstance(block["seal_when_closed"], bool)


def test_config_rejects_a_non_boolean_seal_flag(tmp_path):
    text = open("deployment/gradescope.toml.example").read()
    text = text.replace("seal_when_closed = false", "seal_when_closed = 'yes'")
    path = tmp_path / "bad.toml"
    path.write_text(text)
    with pytest.raises(ValueError, match="seal_when_closed must be boolean"):
        load_config(path)


def test_config_rejects_a_bad_recheck_window(tmp_path):
    text = open("deployment/gradescope.toml.example").read()
    text = text.replace("seal_recheck_hours = 24", "seal_recheck_hours = 0")
    path = tmp_path / "bad.toml"
    path.write_text(text)
    with pytest.raises(ValueError, match="seal_recheck_hours"):
        load_config(path)


def test_example_config_loads_with_sealing_defaults(tmp_path):
    cfg = load_config("deployment/gradescope.toml.example")
    assert cfg.cache.seal_recheck_hours == 24
    assert all(rule.seal_when_closed is False for rule in cfg.assignments)


def test_pending_member_blocks_sealing_until_it_settles():
    """A still-grading submission is transient; sealing it would freeze it."""
    source = FakeSource(
        {
            ("member-1", 8603445): [payload()],
            ("member-2", 8603445): [payload(status="processing")],
        }
    )
    cfg = config(SEALING_RULE)
    _snapshot, seals = build_snapshot(
        source,
        cfg,
        generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert seals == {}
    # Once the submission settles, the seal is created.
    settled = FakeSource(
        {
            ("member-1", 8603445): [payload()],
            ("member-2", 8603445): [payload((0, 0, 0))],
        }
    )
    _snapshot, seals = build_snapshot(
        settled,
        cfg,
        generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert set(seals) == {"lab3-q1"}
    assert seals["lab3-q1"].results == {"abc123": "passed", "xy99": "failed"}


def test_open_assignment_with_no_seal_flag_is_unaffected_by_pending():
    cfg = config(RULE)
    source = FakeSource(
        {
            ("member-1", 8603445): [payload()],
            ("member-2", 8603445): [payload(status="processing")],
        }
    )
    snapshot, seals = build_snapshot(
        source, cfg, generated_at=NOW,
        contract_fingerprint=lambda r: fingerprint_for(cfg, r),
    )
    assert seals == {}
    statuses = {s["netid"]: s["autograders"][0]["status"] for s in snapshot["students"]}
    assert statuses["xy99"] == "pending"
