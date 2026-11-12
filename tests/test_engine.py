"""Planner + journal + undo, end to end on a temp tree."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from crate import db, mover, planner
from crate.config import Config
from crate.scan import scan


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    } | {str(p.relative_to(root)) + "/": "" for p in root.rglob("*") if p.is_dir()}


@pytest.fixture
def world(tmp_path: Path):
    lib = tmp_path / "lib"
    inbox = tmp_path / "inbox"
    (inbox / "My Pack" / "Kicks").mkdir(parents=True)
    (inbox / "My Pack" / "Kicks" / "Kick_01.wav").write_bytes(b"kick-one")
    (inbox / "My Pack" / "Kicks" / "Kick_01.wav.asd").write_bytes(b"asd")
    (inbox / "My Pack" / "Snares").mkdir()
    (inbox / "My Pack" / "Snares" / "Snare_Tight.wav").write_bytes(b"snare")
    (inbox / "My Pack" / "mystery_1.wav").write_bytes(b"???")
    (inbox / "My Pack" / ".DS_Store").write_bytes(b"x")
    with zipfile.ZipFile(inbox / "Zipped.zip", "w") as z:
        z.writestr("Hats/Hat_Closed.wav", b"hat")
        z.writestr("__MACOSX/Hats/._Hat_Closed.wav", b"junk")
        z.writestr("../evil.wav", b"nope")
    cfg = Config(library_roots=[lib], keep_originals=False)
    conn = db.connect(tmp_path / "test.db")
    return tmp_path, inbox, lib, cfg, conn


def run(world, apply=True):
    tmp, inbox, lib, cfg, conn = world
    staging = tmp / "staging"
    staging.mkdir(exist_ok=True)
    res = scan([inbox], staging)
    plan = planner.build_plan(res.items, cfg, planner.sort_router(cfg), [])
    batch = mover.execute(conn, plan, "sort", lib) if apply else None
    return res, plan, batch


def test_dry_run_changes_nothing(world):
    tmp, inbox, lib, *_ = world
    before = snapshot(tmp)
    run(world, apply=False)
    assert {k: v for k, v in snapshot(tmp).items() if not k.startswith("staging")} == {
        k: v for k, v in before.items() if not k.startswith("staging")
    }


def test_sort_then_undo_restores_bytes(world):
    tmp, inbox, lib, cfg, conn = world
    before = snapshot(inbox)
    res, plan, batch = run(world)
    assert (lib / "One Shots/Kicks/Kick_01.wav").exists()
    assert (lib / "One Shots/Kicks/Kick_01.wav.asd").exists()  # sidecar traveled
    assert (lib / "One Shots/Snares/Snare_Tight.wav").exists()
    assert (lib / "One Shots/Hats & Cymbals/Hat_Closed.wav").exists()  # from the zip
    assert (lib / "_Review/mystery_1.wav").exists()
    assert not (tmp / "evil.wav").exists()
    assert any("unsafe" in w for w in res.warnings)
    assert not (inbox / "My Pack" / "Kicks").exists()  # emptied dirs pruned

    assert mover.undo(conn, batch, trash=lambda p: Path(p).unlink()) == []
    assert snapshot(inbox) == before
    assert not lib.exists() or not any(lib.rglob("*.wav"))


def test_idempotent_second_run(world):
    run(world)
    tmp, inbox, lib, cfg, conn = world
    res, plan, _ = run(world, apply=False)
    assert plan.ops == [] or all(o.src.parent.name != "Kicks" for o in plan.ops)


def test_collision_gets_suffix(world):
    tmp, inbox, lib, cfg, conn = world
    (lib / "One Shots/Kicks").mkdir(parents=True)
    (lib / "One Shots/Kicks/Kick_01.wav").write_bytes(b"different")
    _, plan, _ = run(world, apply=False)
    kick = next(o for o in plan.ops if o.src.name == "Kick_01.wav")
    assert kick.dst.name == "Kick_01 (2).wav" and kick.renamed
    assert any(o.dst.name == "Kick_01 (2).wav.asd" for o in plan.ops)


def test_identical_content_is_skipped(world):
    tmp, inbox, lib, cfg, conn = world
    (lib / "One Shots/Kicks").mkdir(parents=True)
    (lib / "One Shots/Kicks/Kick_01.wav").write_bytes(b"kick-one")
    _, plan, _ = run(world, apply=False)
    assert all(o.src.name != "Kick_01.wav" for o in plan.ops)
    assert any("identical" in why for _, why in plan.skipped)


def test_undo_after_crash_mid_batch(world, monkeypatch):
    tmp, inbox, lib, cfg, conn = world
    before = snapshot(inbox)
    calls = {"n": 0}
    real = mover._perform

    def flaky(op):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real(op)

    monkeypatch.setattr(mover, "_perform", flaky)
    with pytest.raises(KeyboardInterrupt):
        run(world)
    batch = mover.latest_done_batch(conn)
    assert batch is not None
    mover.undo(conn, batch, trash=lambda p: Path(p).unlink())
    assert snapshot(inbox) == before


def test_copy_mode_keeps_originals(world):
    tmp, inbox, lib, cfg, conn = world
    cfg.keep_originals = True
    res = scan([inbox], tmp / "st")
    plan = planner.build_plan(res.items, cfg, planner.sort_router(cfg), [inbox])
    mover.execute(conn, plan, "sort", lib)
    assert (inbox / "My Pack/Kicks/Kick_01.wav").exists()
    assert (lib / "One Shots/Kicks/Kick_01.wav").read_bytes() == b"kick-one"
