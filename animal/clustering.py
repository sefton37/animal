"""Story #463 -- cluster raw discovery stories into epics and persist them
into the SOVEREIGN product store (Act 1 -> Stage B handoff).

DEVIATION FROM THE STORY'S ORIGINAL AC, named not silent: the AC (authored
with the 2026-07-07 roadmap, before M2 landed) sketched a NEW module
`animal/productdb.py` with its own minimal epics/stories tables. M2
(#451-#453) has since shipped `animal/product.py` -- the sovereign store with
a richer schema -- and the roadmap itself pre-flagged exactly this drift
(docs/ROADMAP.md: "the single highest-leverage correction in this roadmap is
enforcing 'extend M2's productdb.py' at each of those milestones"). So this
module implements the AC's SUBSTANCE against ProductStore: deterministic
clustering + idempotent, session-atomic persistence. The AC's test-runner
letter is kept (tests/test_productdb.py).

The idempotency CONTRACT (Gate-3 audit fixes F1/F2/F3, precise not
absolute): ingest_epics is SESSION-atomic and FIRST-PROJECTION-WINS.
- One transaction per session: either every epic and story row lands and the
  source_key markers with them, or (on any failure) NOTHING does -- a
  key-present epic is therefore always a fully-projected epic, never a
  half-written one a retry would skip forever.
- A session that already has ANY 'discovery:<sid>:%' key is already
  projected: the call returns the STORED epic ids without writing a row --
  even if the caller passes a different clustering this time (a
  nondeterministic model may re-cluster differently; the first accepted
  projection is the durable one; project under a new session id to
  re-decide).
- "Projection of the ledger" here means: keyed by the ledger's discovery
  session id, so the mapping ledger-session -> backlog rows is 1:1 and
  re-runnable. The caller supplies the accepted clustering; a
  rebuild-FROM-the-ledger composition arrives with #466.

Fail loud, never mask (the #462 red-team lesson): a model channel that
returns a malformed or non-partitioning clustering raises ValueError -- the
DETERMINISTIC fallback is what you get when you ask for it (no channel),
never a silent recovery from a bad model answer. Titles must BE strings
(no coercion of None/0 into epic names); bools are not indices.
"""
from __future__ import annotations
from .product import ProductStore, _now


def _validate_partition(clusters: list[dict], n: int) -> None:
    """Raise ValueError unless `clusters` is a titled, exact partition of
    range(n). Shared by cluster_into_epics (channel output) and ingest_epics
    (the two arguments travel separately; trust neither)."""
    if not isinstance(clusters, list):
        raise ValueError(f"clusters must be a list, got {type(clusters).__name__}")
    if not clusters:
        raise ValueError("clustering returned no clusters")
    seen: set[int] = set()
    for c in clusters:
        if not isinstance(c, dict) or not isinstance(c.get("title"), str) or not c["title"].strip():
            raise ValueError(f"cluster missing a non-empty string title: {c!r}")
        idxs = c.get("story_indices")
        if (not isinstance(idxs, list) or not idxs
                or not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n
                           for i in idxs)):
            raise ValueError(f"cluster has invalid story_indices: {c!r}")
        dup = seen.intersection(idxs)
        if dup or len(set(idxs)) != len(idxs):
            raise ValueError(f"story index assigned twice: {sorted(dup) or idxs}")
        seen.update(idxs)
    missing = set(range(n)) - seen
    if missing:
        raise ValueError(f"clustering is not a partition; unassigned stories: {sorted(missing)}")


def cluster_into_epics(raw_stories: list[dict], channel=None) -> list[dict]:
    """Group one discovery session's raw stories (dicts with
    title/narrative/notes, #462's output shape) into epics. Returns a list of
    {"title": str, "story_indices": list[int]} covering every input index
    exactly once (a partition).

    channel=None (the deterministic, model-free fallback the milestone's hard
    DoD rests on): ONE epic containing every story, titled from the first
    story. channel: callable(raw_stories) -> candidate clusters; the result
    is VALIDATED as a partition with string titles and raises ValueError when
    malformed -- callers choose their own fallback explicitly."""
    if not raw_stories:
        return []
    if channel is None:
        title = (raw_stories[0].get("title") or "").strip() or "discovered work"
        return [{"title": f"epic: {title}", "story_indices": list(range(len(raw_stories)))}]
    clusters = channel(raw_stories)
    _validate_partition(clusters, len(raw_stories))
    return [{"title": c["title"].strip(), "story_indices": list(c["story_indices"])}
            for c in clusters]


def ingest_epics(store: ProductStore, session_id: str, clusters: list[dict],
                 raw_stories: list[dict]) -> list[int]:
    """Persist a session's clustered stories into the sovereign store under
    the contract in the module docstring: SESSION-ATOMIC (one transaction --
    key-present implies fully-projected) and FIRST-PROJECTION-WINS (an
    already-projected session returns its stored epic ids without writing a
    row, whatever clusters are passed this time). Returns the epic ids in
    cluster order (stored order for an already-projected session)."""
    prefix = f"discovery:{session_id}:"
    rows = store.db.execute("SELECT id FROM epics WHERE source_key LIKE ? ORDER BY id",
                            (prefix + "%",)).fetchall()
    if rows:
        return [r[0] for r in rows]
    _validate_partition(clusters, len(raw_stories))
    epic_ids: list[int] = []
    try:
        for i, cluster in enumerate(clusters):
            cur = store.db.execute(
                "INSERT INTO epics(name, status, priority, created, source_key)"
                " VALUES (?,?,?,?,?)",
                (cluster["title"], "backlog", 0, _now(), f"{prefix}{i}"))
            eid = cur.lastrowid
            for idx in cluster["story_indices"]:
                s = raw_stories[idx]
                narrative = (s.get("narrative") or "").strip()
                notes = (s.get("notes") or "").strip()
                user_story = narrative + (f"\n\nnotes: {notes}" if notes else "")
                store.db.execute(
                    "INSERT INTO stories(epic_id, title, user_story, priority, status, created)"
                    " VALUES (?,?,?,?,?,?)",
                    (eid, (s.get("title") or "").strip() or narrative[:60] or "untitled story",
                     user_story, 0, "backlog", _now()))
            epic_ids.append(eid)
        store.db.commit()      # the ONE commit: all rows and keys land together
    except BaseException:
        store.db.rollback()    # ...or none do -- a retry starts clean
        raise
    return epic_ids
