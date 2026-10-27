from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sync.gradescope import Exam2Rule, GradescopeSchemaError, PrivateWebGradescopeSource, load_config
from scripts.refresh_combined_dashboard import _collect_exam2, _validate_exam2_preview


def test_exam2_config_collects_and_old_config_still_loads(tmp_path):
    config = load_config("deployment/gradescope.toml.example")
    assert config.exam2 is not None
    assert len(config.exam2.sources) == 8
    assert config.exam.assignment_id == 8667062
    text = Path("deployment/gradescope.toml.example").read_text()
    start = text.index("# Configured sources are collected")
    end = text.index('[assignments."8532407"]', start)
    path = tmp_path / "old.toml"
    path.write_text(text[:start] + text[end:])
    assert load_config(path).exam2 is None


def test_configured_exam2_is_always_collected():
    config = load_config("deployment/gradescope.toml.example")
    assert _collect_exam2(config, False)
    assert _collect_exam2(config, True)
    assert not _collect_exam2(replace(config, exam2=None), False)
    with pytest.raises(ValueError):
        _collect_exam2(replace(config, exam2=None), True)


def test_preview_rejects_served_paths_and_cache(tmp_path):
    local = Path(__file__).resolve().parents[1] / "local_notes" / "exam2-preview-test"
    args = SimpleNamespace(exam2_preview=True, disable_completion_cache=True,
        output=local / "students", snapshot=local / "state.json", copy_assets_to=None,
        completion_cache=None, lock_file=None, exam2_state=local / "exam2.json")
    _validate_exam2_preview(args)
    args.output = Path(__file__).resolve().parents[1] / "static" / "students"
    with pytest.raises(ValueError, match="local_notes"):
        _validate_exam2_preview(args)
    args.output = local / "students"
    args.disable_completion_cache = False
    with pytest.raises(ValueError, match="disable-completion-cache"):
        _validate_exam2_preview(args)


def source_with_assignments():
    source = object.__new__(PrivateWebGradescopeSource)
    source.config = load_config("deployment/gradescope.toml.example")
    source._available_assignments = {
        aid: SimpleNamespace(title=title, url=f"/courses/1379687/assignments/{aid}",
            get_grades_url=lambda aid=aid: f"https://www.gradescope.com/courses/1379687/assignments/{aid}/scores.csv")
        for aid,title in source.config.exam2.sources
    }
    source._available_assignments[422404] = SimpleNamespace(title="Exam 2",url="/courses/1379687/assignment_containers/422404")
    source._get = lambda url, content_type: SimpleNamespace(content=b"Email\n")
    return source


def test_transport_excludes_parent_and_fetches_only_reviewed_leaves():
    source=source_with_assignments()
    assert set(source.exam2_scores_csvs()) == dict(source.config.exam2.sources).keys()


@pytest.mark.parametrize("change", ["missing", "new", "rename"])
def test_transport_drift_prevents_partial_exam2_import(change):
    source=source_with_assignments()
    aid=source.config.exam2.sources[0][0]
    if change == "missing":
        del source._available_assignments[aid]
    elif change == "new":
        source._available_assignments[999] = SimpleNamespace(title="Exam 2, Version 8",url="/courses/1379687/assignments/999")
    else:
        source._available_assignments[aid].title="Exam 2, Version 99"
    with pytest.raises(GradescopeSchemaError):
        source.exam2_scores_csvs()


def test_hidden_exam2_is_collected_but_not_emitted(monkeypatch, tmp_path):
    import sys
    import scripts.refresh_combined_dashboard as refresh
    from sync.gradescope_exam import ExamImport
    from sync.gradescope_exam2 import EXAM2_OPPORTUNITIES
    from sync.standards import STANDARDS
    from sync.exam2_publication import load_publication_state
    config=load_config("deployment/gradescope.toml.example")
    config=replace(config,cache=replace(config.cache,enabled=False))
    record={"schema_version":6,"updated_at":"2026-10-27T00:00:00Z","worksheet":"fake","student":{"netid":"abc123"},"unmapped_columns":[],"standards":[{"id":sid,"name":name,"checkmarks":[]} for sid,name in STANDARDS.items()]}
    state=tmp_path / "exam2.json"
    monkeypatch.setattr(sys,"argv",["refresh", "unused.toml",str(tmp_path/"students"),str(tmp_path/"snapshot.json"),"--exam2-state",str(state),"--lock-file",str(tmp_path/"refresh.lock"),"--worksheet-id","1","--spreadsheet-id","fake","--all-students","--disable-completion-cache"])
    monkeypatch.setattr(refresh,"load_config",lambda path:config)
    monkeypatch.setattr(refresh,"_secret",lambda key:"fake")
    monkeypatch.setattr(refresh,"fetch_first_worksheet_rows",lambda *a:("fake",[{"NetID":"abc123"}]))
    monkeypatch.setattr(refresh,"rows_to_simple_records",lambda *a,**k:[record])
    monkeypatch.setattr(refresh,"PrivateWebGradescopeSource",lambda *a:object())
    def snapshot(*a,**kwargs):
        kwargs["metrics"].update({key:0 for key in ("lab_cache_candidates","lab_cache_hits","lab_source_checks","lab_canary_checks","lab_sealed_assignments","lab_seals_created","lab_seals_invalidated","lab_seal_checks")})
        return {"students":[{"netid":"abc123"}]},{}
    monkeypatch.setattr(refresh,"build_snapshot",snapshot)
    monkeypatch.setattr(refresh,"merge_checkoffs_with_autograders",lambda *a,**k:[record])
    monkeypatch.setattr(refresh,"import_exam_soft",lambda *a,**k:ExamImport({},False,"fake"))
    real_merge=refresh.merge_exam_checkmarks
    def merge(records,result,**kwargs):
        return real_merge(records,result,**kwargs) if kwargs else records
    monkeypatch.setattr(refresh,"merge_exam_checkmarks",merge)
    fetched=[]
    def fetch(*args,**kwargs):
        fetched.append(True)
        outcomes=[{**{k:v for k,v in item.items() if k != "allowed_kinds"},"status":"complete"} for item in EXAM2_OPPORTUNITIES]
        return ExamImport({"abc123":outcomes},True,"Exam 2 scores loaded")
    monkeypatch.setattr(refresh,"import_exam2_soft",fetch)
    captured=[]
    monkeypatch.setattr(refresh,"write_simple_release",lambda records,*a,**k:captured.extend(records) or ["fake"])
    monkeypatch.setattr(refresh,"write_snapshot_atomic",lambda *a:None)
    refresh.main()
    assert fetched == [True]
    assert "exam2-q" not in str(captured)
    private=load_publication_state(state)
    assert private["visible"] is False
    assert "exam2-q" in str(private["records"])
    from sync.exam2_publication import write_publication_state
    private["visible"] = True
    write_publication_state(state, private)
    captured.clear()
    refresh.main()
    assert "exam2-q" in str(captured)
    assert load_publication_state(state)["visible"] is True
    private = load_publication_state(state)
    private["visible"] = False
    write_publication_state(state, private)
    captured.clear()
    refresh.main()
    assert "exam2-q" not in str(captured)
    assert load_publication_state(state)["visible"] is False


@pytest.mark.parametrize("bad", ["path", "export"])
def test_exam2_metadata_drift_raises_optional_source_error(bad):
    source=source_with_assignments()
    assignment=source._available_assignments[source.config.exam2.sources[0][0]]
    if bad == "path":
        assignment.url=None
    else:
        assignment.get_grades_url=lambda: None
    with pytest.raises(GradescopeSchemaError):
        source.exam2_scores_csvs()
