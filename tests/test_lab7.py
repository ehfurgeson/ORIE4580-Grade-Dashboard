from sync.checkoff_mappings import MANUAL_ONLY_OPPORTUNITY_IDS, AUTOGRADER_OPPORTUNITY_IDS
from sync.combined_checkoffs import merge_checkoffs_with_autograders, validate_combined_record
from sync.simple_checkoffs import rows_to_simple_records
from sync.standards import STANDARDS


def test_lab7_manual_marks_map_to_s6_s7_without_gradescope():
    records=rows_to_simple_records([
        {"NetID":"abc123","Lab 7 - Q1":True,"Lab 7 - Q2":False},
        {"NetID":"xy99","Lab 7 - Q1":False,"Lab 7 - Q2":True},
    ],updated_at="2026-10-27T00:00:00Z",worksheet="Fake checkoffs")
    from test_gradescope_exam import lab_snapshot
    snapshot=lab_snapshot()
    snapshot["students"].append({"netid":"xy99","autograders":snapshot["students"][0]["autograders"]})
    # This known Lab contract is unrelated to the two manual-only Lab 7 questions.
    for record in records:
        extra=rows_to_simple_records([{"NetID":record["student"]["netid"],"Lab 1 - Q1.3":True,"Lab 1 - Q2.3":True,"Lab 1 - Q2.4":True}],updated_at="2026-10-27T00:00:00Z",worksheet="Fake checkoffs")[0]
        record["standards"][0]["checkmarks"]=extra["standards"][0]["checkmarks"]
    combined=merge_checkoffs_with_autograders(records,snapshot)
    assert {"lab7-q1","lab7-q2"} <= MANUAL_ONLY_OPPORTUNITY_IDS
    assert not {"lab7-q1","lab7-q2"} & AUTOGRADER_OPPORTUNITY_IDS
    for index,record in enumerate(combined):
        assert validate_combined_record(record)==[]
        assert record["unmapped_columns"]==[]
        assert len(record["standards"])==len(STANDARDS)==7
        marks={s["id"]:s["checkmarks"] for s in record["standards"]}
        for sid,opp in (("S6","lab7-q1"),("S7","lab7-q2")):
            mark=marks[sid][0]
            assert mark["id"]==opp and mark["kind"]=="green"
            assert [r["id"] for r in mark["requirements"]]==["manual"]
            assert mark["status"]==("complete" if (sid=="S6")== (index==0) else "incomplete")


def test_old_publication_state_migration_preserves_visibility_without_inventing_marks(tmp_path):
    from scripts.migrate_lab7_publication import migrate_lab7_state
    from sync.exam2_publication import write_publication_state, load_publication_state
    from sync.gradescope_exam2 import EXAM2_OPPORTUNITIES
    import copy
    marks=[{"id":o["id"],"label":o["label"],"kind":o["kind"],"status":"not_graded","requirements":[{"id":"exam_score","label":"Exam 2 question score","source":"gradescope_exam","status":"not_graded","details":[]}]} for o in EXAM2_OPPORTUNITIES]
    record={"schema_version":6,"updated_at":"2026-10-27T00:00:00Z","worksheet":"fake","student":{"netid":"abc123"},"unmapped_columns":["Lab 7 - Q1","Lab 7 - Q2","Lab 8 - Q1"],"standards":[{"id":sid,"name":name,"checkmarks":[m for m,o in zip(marks,EXAM2_OPPORTUNITIES) if o["standard_id"]==sid]} for sid,name in STANDARDS.items() if sid!="S7"]}
    state={"schema_version":1,"visible":True,"collected_at":record["updated_at"],"records":[record]}
    before=copy.deepcopy(state)
    migrated=migrate_lab7_state(state)
    assert state==before
    assert migrated["visible"] is True
    assert migrated["records"][0]["standards"][-1]=={"id":"S7","name":STANDARDS["S7"],"checkmarks":[]}
    assert migrated["records"][0]["unmapped_columns"]==["Lab 8 - Q1"]
    path=tmp_path/"migrated.json"
    write_publication_state(path,migrated)
    assert load_publication_state(path)==migrated
    placeholder=copy.deepcopy(migrated)
    placeholder["records"][0]["standards"][-1]["name"]="Standard 7"
    upgraded=migrate_lab7_state(placeholder)
    assert upgraded==migrated
    assert placeholder["records"][0]["standards"][-1]["name"]=="Standard 7"
