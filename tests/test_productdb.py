"""Story #463 -- clustering raw discovery stories into epics + idempotent
persistence into the SOVEREIGN product store. Deterministic, no network.
(The AC's original sketch named a new animal/productdb.py store; M2 had
already shipped animal/product.py, so clustering lives in animal/clustering.py
and persists through ProductStore -- the deviation is documented in
clustering.py's module docstring. This file keeps the AC's runner letter.)
Run: python3 tests/test_productdb.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal.clustering import cluster_into_epics, ingest_epics
from animal.product import ProductStore

RAW = [
    {"title": "log a habit", "narrative": "As a maker, I want to log a habit so that my streak is recorded", "notes": "input: name+date"},
    {"title": "see my streak", "narrative": "As a maker, I want to see my streak so that I stay motivated", "notes": ""},
    {"title": "weekly recap", "narrative": "As a maker, I want a weekly recap so that I notice drift", "notes": "output: email"},
]


def test_fallback_clustering_is_one_epic_covering_all():
    """The AC's deterministic, model-free fallback: no channel -> exactly one
    epic whose story_indices covers every input index."""
    clusters = cluster_into_epics(RAW)   # channel=None
    assert len(clusters) == 1, clusters
    assert sorted(clusters[0]["story_indices"]) == [0, 1, 2]
    assert clusters[0]["title"].strip()


def test_fallback_on_empty_input_is_empty():
    assert cluster_into_epics([]) == []


def test_channel_clusters_are_validated_as_a_partition():
    """A model channel's grouping is used only when it is a real partition
    with titled clusters."""
    def channel(stories):
        return [{"title": "logging", "story_indices": [0, 1]},
                {"title": "reporting", "story_indices": [2]}]
    clusters = cluster_into_epics(RAW, channel=channel)
    assert [c["title"] for c in clusters] == ["logging", "reporting"]


def test_channel_bad_output_raises_never_masks():
    """The #462 red-team lesson applied here: a malformed model grouping is a
    LOUD failure, never a silent fallback that hides the model's brokenness."""
    cases = [
        lambda s: [],                                                        # nothing
        lambda s: [{"title": "a", "story_indices": [0]}],                    # not a partition (1,2 missing)
        lambda s: [{"title": "a", "story_indices": [0, 1, 2]},
                   {"title": "b", "story_indices": [2]}],                    # index assigned twice
        lambda s: [{"title": "", "story_indices": [0, 1, 2]}],               # untitled
        lambda s: [{"title": None, "story_indices": [0, 1, 2]}],             # F4: None is not a title
        lambda s: [{"title": 0, "story_indices": [0, 1, 2]}],                # F4: 0 is not a title
        lambda s: [{"title": "a", "story_indices": [True, False, 2]}],       # F4: bools are not indices
        lambda s: [{"title": "a", "story_indices": [0, 1, 99]}],             # out of range
        lambda s: "not a list",
    ]
    for ch in cases:
        try:
            cluster_into_epics(RAW, channel=ch)
            assert False, f"expected ValueError for {ch}"
        except ValueError:
            pass


def test_ingest_is_idempotent_by_session_key():
    """Re-projecting the same discovery session must not write a single new
    row: the store is a projection of the ledger."""
    store = ProductStore(db_path=":memory:")
    clusters = cluster_into_epics(RAW)
    ids1 = ingest_epics(store, "sess-abc123", clusters, RAW)
    ids2 = ingest_epics(store, "sess-abc123", clusters, RAW)
    assert ids1 == ids2 and len(ids1) == 1
    n_epics = store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0]
    n_stories = store.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
    assert n_epics == 1, n_epics
    assert n_stories == 3, n_stories
    key = store.db.execute("SELECT source_key FROM epics").fetchone()[0]
    assert key == "discovery:sess-abc123:0"
    store.close()


def test_ingest_carries_narrative_and_notes_into_user_story():
    store = ProductStore(db_path=":memory:")
    ingest_epics(store, "s1", cluster_into_epics(RAW), RAW)
    rows = store.db.execute("SELECT title, user_story FROM stories ORDER BY id").fetchall()
    assert rows[0][0] == "log a habit"
    assert "streak is recorded" in rows[0][1] and "notes: input: name+date" in rows[0][1]
    assert "notes:" not in rows[1][1]        # empty notes are not appended
    store.close()


def test_different_sessions_do_not_collide():
    store = ProductStore(db_path=":memory:")
    ingest_epics(store, "s1", cluster_into_epics(RAW), RAW)
    ingest_epics(store, "s2", cluster_into_epics(RAW), RAW)
    n_epics = store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0]
    assert n_epics == 2, "distinct sessions are distinct projections"
    store.close()


def test_ingest_failure_leaves_nothing_behind():
    """Gate-3 audit F1/F3: the ingest is SESSION-ATOMIC -- a failure mid-way
    persists NOTHING (no keyed-but-half-projected epic a retry would skip
    forever, no keyless orphan), and the retry starts clean."""
    store = ProductStore(db_path=":memory:")

    class Boom(list):
        def __getitem__(self, i):
            if i == 2:
                raise RuntimeError("boom mid-cluster")
            return super().__getitem__(i)

    clusters = cluster_into_epics(RAW)
    try:
        ingest_epics(store, "s-atomic", clusters, Boom(RAW))
        assert False, "expected the seeded failure to propagate"
    except RuntimeError:
        pass
    assert store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0
    ids = ingest_epics(store, "s-atomic", clusters, RAW)   # clean retry succeeds
    assert len(ids) == 1
    assert store.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 3
    store.close()


def test_reingest_with_different_clusters_keeps_first_projection():
    """Gate-3 audit F2: a nondeterministic model may re-cluster the same
    session differently -- FIRST-PROJECTION-WINS: the stored epic ids come
    back and not a single new row is written."""
    store = ProductStore(db_path=":memory:")
    ids1 = ingest_epics(store, "s-nd", cluster_into_epics(RAW), RAW)
    different = [{"title": "logging", "story_indices": [0, 1]},
                 {"title": "reporting", "story_indices": [2]}]
    ids2 = ingest_epics(store, "s-nd", different, RAW)
    assert ids2 == ids1, (ids1, ids2)
    assert store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 3
    store.close()


def test_ingest_revalidates_the_partition_itself():
    """clusters and raw_stories travel as separate arguments; ingest_epics
    trusts neither (audit F5) -- a non-partition is refused before any row."""
    store = ProductStore(db_path=":memory:")
    try:
        ingest_epics(store, "s-bad", [{"title": "a", "story_indices": [0]}], RAW)
        assert False, "expected ValueError for a non-partition"
    except ValueError:
        pass
    assert store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0] == 0
    store.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
