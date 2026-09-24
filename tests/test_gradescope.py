import json
from decimal import Decimal

import pytest

from scripts.import_gradescope import _validate_canary_mode
from sync.checkoff_mappings import opportunity_from_assignment_title

from sync.gradescope import (
    AdapterConfig,
    AssignmentRule,
    GradescopeSchemaError,
    GradescopeTransportError,
    MemberRef,
    PrivateWebGradescopeSource,
    SubmissionBatch,
    aggregate_status,
    build_snapshot,
    carry_forward_verified_passes,
    evaluate_submission,
    extract_submission_payload,
    load_config,
    netid_from_email,
    validate_snapshot,
    write_snapshot_atomic,
)


RULE = AssignmentRule(8603445, "lab3-q1", "lab3-q1-v1", Decimal("3"), 3, (Decimal("1"),) * 3)
CONFIG = AdapterConfig(1379687, (RULE,), minimum_request_interval_seconds=0)
NOW = "2026-09-22T18:00:00Z"


def payload(scores=(1, 1, 1), *, status="processed", error_code=None, total=None, output="FAILED PASS"):
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
            "output": output,
        },
    }


class FakeSource:
    def __init__(self, histories, members=None):
        self.histories = histories
        self.members = members or [MemberRef("member-1", "abc123@cornell.edu", "0")]

    def list_members(self):
        return self.members

    def submissions(self, member_id, assignment_id):
        values = self.histories.get((member_id, assignment_id), [])
        return SubmissionBatch(len(values), iter(values))


def test_full_structured_result_passes_and_output_text_is_ignored():
    assert evaluate_submission(payload(output="FAIL"), RULE) == "passed"
    assert evaluate_submission(payload((1, 0, 1), output="PASS"), RULE) == "failed"


def test_tests_cannot_be_combined_across_submissions():
    statuses = [
        evaluate_submission(payload((1, 1, 0)), RULE),
        evaluate_submission(payload((1, 0, 1)), RULE),
    ]
    assert statuses == ["failed", "failed"]
    assert aggregate_status(statuses) == "failed"


def test_any_historical_full_pass_wins_over_active_and_later_failures():
    source = FakeSource({
        ("member-1", RULE.assignment_id): [
            payload((1, 0, 1)),
            payload((1, 1, 1)),
            payload((1, 0, 0)),
        ]
    })
    snapshot = build_snapshot(source, CONFIG, generated_at=NOW)
    result = snapshot["students"][0]["autograders"][0]
    assert result == {
        "opportunity_id": "lab3-q1",
        "status": "passed",
        "pass_evidence": "current_history",
        "submissions_observed": 3,
        "submissions_checked": 2,
    }


def test_course_wide_contract_drift_aborts_snapshot():
    source = FakeSource({("member-1", RULE.assignment_id): [payload((1, 1))]})
    with pytest.raises(GradescopeSchemaError, match="matched no processed submissions"):
        build_snapshot(source, CONFIG, generated_at=NOW)


def test_legacy_submission_is_failed_when_current_contract_is_observed_elsewhere():
    source = FakeSource(
        {
            ("old", RULE.assignment_id): [payload((1, 1))],
            ("current", RULE.assignment_id): [payload((1, 0, 1))],
        },
        members=[
            MemberRef("old", "abc123@cornell.edu", "0"),
            MemberRef("current", "xy99@cornell.edu", "0"),
        ],
    )
    snapshot = build_snapshot(source, CONFIG, generated_at=NOW)
    statuses = {
        student["netid"]: student["autograders"][0]["status"]
        for student in snapshot["students"]
    }
    assert statuses == {"abc123": "failed", "xy99": "failed"}


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], "not_submitted"),
        (["failed", "error"], "failed"),
        (["failed", "pending"], "pending"),
        (["error"], "error"),
        (["failed", "passed", "pending"], "passed"),
    ],
)
def test_status_precedence(values, expected):
    assert aggregate_status(values) == expected


def test_pending_and_autograder_error_are_known_student_states():
    assert evaluate_submission(payload(status="processing"), RULE) == "pending"
    assert evaluate_submission(payload(error_code="runner_error"), RULE) == "error"
    assert evaluate_submission(payload(status="failed"), RULE) == "error"
    without_results = {"assignment_submission": {"status": "processed"}, "autograder_results": None}
    assert evaluate_submission(without_results, RULE) == "error"


@pytest.mark.parametrize(
    "bad_payload,message",
    [
        (payload((1, 1, 1), total="nan"), "finite"),
        (payload((1, 1, 2)), "invalid score range"),
        ({"assignment_submission": {}}, "status is missing"),
    ],
)
def test_schema_drift_aborts_instead_of_marking_student_failed(bad_payload, message):
    with pytest.raises(GradescopeSchemaError, match=message):
        evaluate_submission(bad_payload, RULE)


def test_aggregate_score_must_equal_sum_of_test_scores():
    with pytest.raises(GradescopeSchemaError, match="test-score sum"):
        evaluate_submission(payload((1, 0, 1), total=3), RULE)


def test_legacy_submission_contract_is_not_a_pass():
    assert evaluate_submission(payload((1, 1)), RULE) == "contract_mismatch"
    changed = payload()
    changed["autograder_results"]["tests"][0]["max_score"] = 2
    assert evaluate_submission(changed, RULE) == "contract_mismatch"
    assert aggregate_status(["contract_mismatch"]) == "failed"


def test_netid_identity_is_exact_and_duplicates_abort():
    assert netid_from_email("ABC123@CORNELL.EDU") == "abc123"
    assert netid_from_email("abc123@example.com") is None
    source = FakeSource({}, members=[
        MemberRef("1", "abc123@cornell.edu", "0"),
        MemberRef("2", "ABC123@cornell.edu", "0"),
    ])
    with pytest.raises(GradescopeSchemaError, match="duplicate Cornell NetID"):
        build_snapshot(source, CONFIG, generated_at=NOW)


def test_snapshot_reports_aggregate_progress_without_identity_values():
    events = []
    source = FakeSource({}, members=[
        MemberRef("1", "abc123@cornell.edu", "0"),
        MemberRef("2", "xy99@cornell.edu", "0"),
    ])
    build_snapshot(source, CONFIG, generated_at=NOW, progress=lambda done, total: events.append((done, total)))
    assert events == [(1, 2), (2, 2)]


def test_unmatched_members_are_counted_but_not_emitted():
    source = FakeSource({}, members=[
        MemberRef("1", "abc123@cornell.edu", "0"),
        MemberRef("staff", "person@example.com", "0"),
    ])
    snapshot = build_snapshot(source, CONFIG, generated_at=NOW)
    assert snapshot["unmatched_members"] == 1
    assert [student["netid"] for student in snapshot["students"]] == ["abc123"]
    assert snapshot["students"][0]["autograders"][0]["status"] == "not_submitted"


def test_previous_verified_pass_is_monotone_for_same_contract():
    prior = build_snapshot(
        FakeSource({("member-1", RULE.assignment_id): [payload()]}),
        CONFIG,
        generated_at=NOW,
    )
    current = build_snapshot(
        FakeSource({("member-1", RULE.assignment_id): [payload((1, 0, 0))]}),
        CONFIG,
        generated_at="2026-09-23T18:00:00Z",
    )
    merged = carry_forward_verified_passes(current, prior)
    result = merged["students"][0]["autograders"][0]
    assert result["status"] == "passed"
    assert result["pass_evidence"] == "previous_snapshot"


def test_pass_evidence_is_not_carried_across_changed_contract():
    prior = build_snapshot(FakeSource({("member-1", RULE.assignment_id): [payload()]}), CONFIG, generated_at=NOW)
    changed_rule = AssignmentRule(RULE.assignment_id, RULE.opportunity_id, "lab3-q1-v2", Decimal("4"), 4, (Decimal("1"),) * 4)
    changed = AdapterConfig(CONFIG.course_id, (changed_rule,), minimum_request_interval_seconds=0)
    current = build_snapshot(FakeSource({}), changed, generated_at=NOW)
    with pytest.raises(ValueError, match="changed course or assignment contract"):
        carry_forward_verified_passes(current, prior)


def test_assignment_title_mapping_matches_sheet_opportunities():
    assert opportunity_from_assignment_title("Lab 1, Q1-2") == "lab1-q1-2"
    assert opportunity_from_assignment_title("Lab 1, Q3") == "lab1-q3"
    assert opportunity_from_assignment_title("Lab 3 - Q2") == "lab3-q2"
    assert opportunity_from_assignment_title("Prelim 1") is None
    with pytest.raises(ValueError, match="required convention"):
        opportunity_from_assignment_title("Lab One Question Three")
    with pytest.raises(ValueError, match="no Google Sheet opportunity"):
        opportunity_from_assignment_title("Lab 9, Q9")


def test_roles_filter_staff_and_unknown_roles_fail_closed():
    source = FakeSource({}, members=[
        MemberRef("1", "abc123@cornell.edu", "0"),
        MemberRef("2", "ta99@cornell.edu", "2"),
    ])
    snapshot = build_snapshot(source, CONFIG, generated_at=NOW)
    assert [student["netid"] for student in snapshot["students"]] == ["abc123"]

    unknown = FakeSource({}, members=[MemberRef("1", "abc123@cornell.edu", "new-role")])
    with pytest.raises(GradescopeSchemaError, match="unknown Gradescope roster role"):
        build_snapshot(unknown, CONFIG, generated_at=NOW)


def test_roster_removal_is_allowed_but_old_student_results_are_not_copied():
    prior_source = FakeSource({}, members=[
        MemberRef("1", "abc123@cornell.edu", "0"),
        MemberRef("2", "xy99@cornell.edu", "0"),
    ])
    prior = build_snapshot(prior_source, CONFIG, generated_at=NOW)
    current = build_snapshot(FakeSource({}), CONFIG, generated_at="2026-09-23T18:00:00Z")
    merged = carry_forward_verified_passes(current, prior)
    assert [student["netid"] for student in merged["students"]] == ["abc123"]


def test_test_maxima_vector_is_part_of_contract():
    changed_maxima = payload()
    changed_maxima["autograder_results"]["tests"][0].update(score=2, max_score=2)
    changed_maxima["autograder_results"]["tests"][1].update(score=0, max_score=0)
    assert evaluate_submission(changed_maxima, RULE) == "contract_mismatch"


def test_unknown_submission_status_fails_closed():
    with pytest.raises(GradescopeSchemaError, match="unknown assignment submission status"):
        evaluate_submission(payload(status="new-upstream-state"), RULE)


def test_canary_requires_new_output_and_no_carry_forward(tmp_path):
    output = tmp_path / "canary.json"
    with pytest.raises(ValueError, match="requires --no-carry-forward"):
        _validate_canary_mode("abc123", False, output)
    _validate_canary_mode("abc123", True, output)
    output.write_text("existing")
    with pytest.raises(ValueError, match="already exists"):
        _validate_canary_mode("abc123", True, output)


def test_submission_urls_are_bound_to_course_and_assignment():
    source = PrivateWebGradescopeSource.__new__(PrivateWebGradescopeSource)
    source.config = CONFIG
    expected = source._submission_url(
        "/courses/1379687/assignments/8603445/submissions/123", 8603445
    )
    assert expected.endswith("/submissions/123")
    bad = [
        "/courses/999/assignments/8603445/submissions/123",
        "/courses/1379687/assignments/999/submissions/123",
        "//www.gradescope.com/courses/1379687/assignments/8603445/submissions/123",
        "/courses/1379687/assignments/8603445/submissions/123?x=1",
        "/courses/1379687/assignments/8603445/submissions/%31%32%33",
    ]
    for value in bad:
        with pytest.raises(GradescopeSchemaError):
            source._submission_url(value, 8603445)


def test_submission_html_requires_exactly_one_valid_viewer_payload():
    encoded = json.dumps(payload()).replace("&", "&amp;").replace('"', "&quot;")
    html = f'<div data-react-class="AssignmentSubmissionViewer" data-react-props="{encoded}"></div>'
    assert evaluate_submission(extract_submission_payload(html), RULE) == "passed"
    with pytest.raises(GradescopeSchemaError, match="missing or duplicated"):
        extract_submission_payload("<html></html>")


def test_load_config_is_explicit_and_decimal_exact(tmp_path):
    config_path = tmp_path / "gradescope.toml"
    config_path.write_text('''
        schema_version = 1
        course_id = 1379687
        [roles]
        student = ["0"]
        non_student = ["1", "2"]
        [network]
        timeout_seconds = 30
        minimum_request_interval_seconds = 0.1
        maximum_requests = 20000
        maximum_response_bytes = 10000000
        minimum_roster_members = 1
        maximum_roster_members = 2000
        maximum_submissions_per_student = 500
        [assignments."8603445"]
        opportunity_id = "lab3-q1"
        contract_version = "lab3-q1-v1"
        expected_score = "3.0"
        expected_test_count = 3
        expected_test_maxima = ["1", "1", "1"]
        title_mapping_override = false
    ''')
    config = load_config(config_path)
    assert config.assignments[0].expected_score == Decimal("3.0")
    assert config.maximum_submissions_per_student == 500


def test_unknown_config_fields_fail_closed(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("schema_version=1\ncourse_id=1\nextra=true\n")
    with pytest.raises(ValueError, match="fields"):
        load_config(path)


def test_atomic_write_and_validation_preserve_previous_output(tmp_path):
    snapshot = build_snapshot(FakeSource({}), CONFIG, generated_at=NOW)
    output = tmp_path / "snapshot.json"
    write_snapshot_atomic(snapshot, output)
    assert output.stat().st_mode & 0o777 == 0o600
    original = output.read_text()
    invalid = json.loads(original)
    invalid["students"][0]["autograders"][0]["status"] = "unknown"
    with pytest.raises(ValueError, match="invalid Gradescope snapshot"):
        write_snapshot_atomic(invalid, output)
    assert output.read_text() == original


def test_snapshot_contains_no_email_member_or_submission_ids():
    snapshot = build_snapshot(
        FakeSource({("member-1", RULE.assignment_id): [payload()]}),
        CONFIG,
        generated_at=NOW,
    )
    serialized = json.dumps(snapshot)
    assert "@cornell.edu" not in serialized
    assert "member-1" not in serialized
    assert "submission_id" not in serialized
    assert validate_snapshot(snapshot) == []


def test_same_origin_validation_rejects_http_and_other_hosts():
    PrivateWebGradescopeSource._validate_same_origin("https://www.gradescope.com/courses/1")
    with pytest.raises(GradescopeTransportError):
        PrivateWebGradescopeSource._validate_same_origin("http://www.gradescope.com/courses/1")
    with pytest.raises(GradescopeTransportError):
        PrivateWebGradescopeSource._validate_same_origin("https://evil.example/courses/1")
    with pytest.raises(GradescopeTransportError):
        PrivateWebGradescopeSource._validate_same_origin("https://www.gradescope.com:444/courses/1")


def test_snapshot_validator_handles_hostile_json_types_without_raising():
    snapshot = build_snapshot(FakeSource({}), CONFIG, generated_at=NOW)
    bad_assignment = json.loads(json.dumps(snapshot))
    bad_assignment["assignments"][0]["assignment_id"] = []
    assert validate_snapshot(bad_assignment)
    bad_status = json.loads(json.dumps(snapshot))
    bad_status["students"][0]["autograders"][0]["status"] = []
    assert validate_snapshot(bad_status)


class FakeResponse:
    def __init__(self, status, url, body=b"ok", headers=None):
        self.status_code = status
        self.url = url
        self.headers = headers or {"Content-Type": "text/html"}
        self.history = []
        self._body = body
        self._content = False
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        self.closed = True

    @property
    def content(self):
        return self._content if isinstance(self._content, bytes) else self._body

    @property
    def text(self):
        return self.content.decode()


class FakeSession:
    def __init__(self):
        self.calls = []
        self.routes = {}
        self.request = self.raw_request

    def raw_request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        configured = self.routes.get(url)
        if isinstance(configured, list):
            return configured.pop(0)
        if configured is not None:
            return configured
        return FakeResponse(200, url)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


class FakeGradescopeClient:
    last = None

    def __init__(self, auto_login=False, verbose=False):
        self.session = FakeSession()
        self.username = None
        self.password = None
        self.logged_in = False
        FakeGradescopeClient.last = self

    def login(self, email, password):
        self.session.get("https://www.gradescope.com")
        self.session.post("https://www.gradescope.com/login", data={"secret": password})
        self.logged_in = True
        return True

    def get_assignments(self, course):
        return [
            type(
                "Assignment", (),
                {"assignment_id": RULE.assignment_id, "title": "Lab 3, Q1"},
            )()
        ]


def make_fake_transport(monkeypatch, **config_changes):
    import gradescope

    monkeypatch.setattr(gradescope, "Gradescope", FakeGradescopeClient)
    values = {
        "course_id": CONFIG.course_id,
        "assignments": CONFIG.assignments,
        "student_role_values": CONFIG.student_role_values,
        "non_student_role_values": CONFIG.non_student_role_values,
        "timeout_seconds": 1,
        "minimum_request_interval_seconds": 0,
        "maximum_requests": 20,
        "maximum_response_bytes": 100,
        "minimum_roster_members": 1,
        "maximum_roster_members": 10,
        "maximum_submissions_per_student": 10,
    }
    values.update(config_changes)
    config = AdapterConfig(**values)
    return PrivateWebGradescopeSource("staff@example.edu", "seeded-secret", config)


def test_transport_blocks_mutation_and_cross_origin_redirect_before_contact(monkeypatch):
    source = make_fake_transport(monkeypatch)
    session = source._client.session
    with pytest.raises(GradescopeTransportError, match="read-only"):
        session.post("https://www.gradescope.com/courses/1")

    start = "https://www.gradescope.com/start"
    session.routes[start] = FakeResponse(302, start, headers={"Location": "https://evil.example/steal"})
    before = len(session.calls)
    with pytest.raises(GradescopeTransportError, match="allowlisted origin"):
        session.get(start)
    new_calls = session.calls[before:]
    assert [url for _, url, _ in new_calls] == [start]


def test_transport_streams_response_limit_and_counts_every_retry(monkeypatch):
    source = make_fake_transport(monkeypatch, maximum_response_bytes=4)
    session = source._client.session
    large = "https://www.gradescope.com/large"
    session.routes[large] = FakeResponse(200, large, body=b"12345")
    with pytest.raises(GradescopeTransportError, match="size limit"):
        session.get(large)

    retry = "https://www.gradescope.com/retry"
    session.routes[retry] = [
        FakeResponse(500, retry),
        FakeResponse(500, retry),
        FakeResponse(500, retry),
    ]
    before_requests = source._request_count
    response = session.get(retry)
    assert response.status_code == 500
    assert source._request_count - before_requests == 3
