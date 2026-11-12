# Build Spec: Ableton-First Audio Sample Organizer (working name: `crate`)

You are building a Python command-line tool from scratch. It reorganizes a large audio sample library on macOS into a clean folder structure that can be browsed in **Ableton Live 12's browser**. There is no standalone GUI.

Read this whole spec before writing code. Start in plan mode: give me your architecture and the Milestone 1 plan, and wait for my OK before implementing. Rename the tool if you have a better name.

---

## 1. Context

- **Owner:** a producer on macOS (Apple Silicon assumed, so verify) running Ableton Live 12 (beta).
- **Library:** about 100 GB and growing, mostly in the Splice download folder on the internal drive, some on external drives.
- **Problem:** Splice packs are deeply nested and hard to browse without Splice's own search, which locks him into the subscription. Random packs and downloads pile up in folders that are hard to navigate.
- **Goal:** drop folders into the terminal. The tool unpacks them, analyzes every sample by its sound, and files it into his existing structure. He can later change his rules and re-sort without re-analyzing anything.
- **Public GitHub repo:** this is a portfolio piece. Code quality, tests, README and CI matter as much as features.

## 2. Non-negotiable safety rules

These override any convenience. The tool moves real files that real Ableton projects depend on.

1. **Dry run by default.** Every command that touches files prints a plan (a table of from → to, plus counts per destination folder). It only acts with `--apply`.
2. **Journal every operation.** Each file operation is logged to SQLite before it executes, with a batch ID. `crate undo [batch_id]` fully reverses a batch, and undo must be crash-safe.
3. **Never rename by default.** Ableton recovers missing samples with File Manager search, which matches on **filename**. Preserving filenames keeps old Live Sets recoverable after moves. Renaming is an opt-in setting with a user-defined template (see §8).
4. **Verify before deleting.** For cross-volume moves, copy the file, check its size and content hash, then remove the source. Never delete a file whose verified copy doesn't exist. Prefer `send2trash` over hard deletes for anything the user didn't explicitly ask to remove permanently.
5. **`.asd` sidecar files travel with their sample.** Same name and the same destination.
6. **Never modify audio content.** Never write tags into the audio files in v1.
7. **Handle collisions.** If a destination name already exists and the content differs, append ` (2)` and so on, and log it. If the content is identical, treat it as a duplicate (see §7).
8. **Idempotent.** Running the same command twice does nothing the second time.

## 3. Tech stack

- Python 3.11+, managed with `uv`, packaged via `pyproject.toml`, installable with `pipx`/`uv tool install`.
- CLI: `typer` + `rich` for progress bars, tables and colored plan output.
- Storage: SQLite (stdlib `sqlite3` or SQLModel), stored at `~/.crate/library.db`.
- Config: YAML at `~/.crate/config.yaml`, validated with `pydantic`.
- Audio I/O: `soundfile` for WAV/AIFF/FLAC, and `audioread` or ffmpeg for MP3.
- DSP features: `librosa` and `numpy`. Use `essentia` (KeyExtractor, rhythm descriptors) if it installs cleanly on Apple Silicon; otherwise fall back to librosa, and document which one is used.
- Pretrained model: **CLAP** via Hugging Face `transformers` (`laion/clap-htsat-unfused` or a better current checkpoint) for zero-shot classification with text prompts. Run it on MPS when available and on CPU otherwise. It must work out of the box with no user training.
- Quality: `ruff`, `mypy` (strict on core modules), `pytest`, and GitHub Actions CI on macOS.

## 4. CLI commands

```
crate init                      # create config + DB, ask for library root(s)
crate unpack <paths...>         # flatten nested pack folders, extract zips (no analysis)
crate analyze <paths...>        # analyze + cache results in DB, no file moves
crate sort <paths...>           # plan/apply moves into library structure (analyzes if needed)
crate ingest <paths...>         # unpack → analyze → sort in one shot (the main daily command)
crate reorganize [--section X]  # re-sort existing library (or a subfolder) after config changes
crate review                    # walk through low-confidence files (play preview via afplay, assign label)
crate correct <file> <label>    # manual override; stored and respected forever
crate dedupe                    # find + resolve duplicates (incl. Splice re-downloads)
crate where <name-or-path>      # look up where a file went / what it was originally called
crate undo [batch_id]           # reverse a batch
crate status                    # library stats, pending review count, last batches
```

Global flags: `--apply`, `--config`, `--verbose`, `--jobs N`. Paths can be dragged into the terminal, so handle shell-escaped spaces and quoted paths.

## 5. Pipeline

### 5.1 Unpack (rebuild of his old "unpack files" tool, but better)

- Recursively find all audio (`.wav .aif .aiff .mp3 .flac .ogg`), MIDI, presets and archives.
- Extract `.zip` files (and `.rar`/`.7z` if a library is available, otherwise skip with a warning) into a temp staging area. Process archives nested inside archives too.
- Remember **provenance** for every file: original full path, pack name (inferred from the top-level folder or the Splice structure), and the original folder names. Folder names are a strong classification signal ("Kicks", "Drum Loops", "Melodic"), so keep them.
- Skip junk: `__MACOSX`, `.DS_Store`, zero-byte files, and files that fail to decode (log them).
- Remove the now-empty nested folders after a successful apply.

### 5.2 Analyze

Each file is identified by a **content hash** of the decoded PCM, not the raw file bytes. This catches the same audio saved under a different name or container. The raw byte hash is stored too. Analysis results are cached by content hash, so re-sorts never re-analyze.

Classification fuses three sources, in this order:

1. **Metadata:** parse the filename and parent folder names for type keywords (kick, snare, rim, clap, hat, perc, 808, bass, vox, pad, chord, fx, riser, etc.), loop vs one-shot markers, BPM (`120bpm`, `_120_`) and key (`Cmin`, `F#m`, `A_maj`). Splice naming conventions are common, so handle them well.
2. **DSP features:** duration, onset count, transient strength, crest factor, attack time, decay/RT estimate, spectral centroid and rolloff, low/mid/high band energy, tonalness/pitch confidence, tempo, beat-grid alignment, key and scale with confidence.
3. **CLAP zero-shot:** score the audio against text prompts for each category and characteristic (for example "a punchy electronic kick drum", "a short tight UK garage snare", "a wet reverb-heavy snare"). Prompts live in config so the user can tune them.

**Fusion:** metadata and audio agree → high confidence. They disagree → trust the audio for sound type unless the metadata is very explicit, and lower the confidence. Below the confidence threshold (configurable, default 0.6), the file goes to `_Review/` rather than a wrong folder. Manual corrections (`crate correct`, `crate review`) always win.

### 5.3 What to detect

**Loop vs one-shot:** use duration, onset count and whether the length lands on whole bars at the detected tempo. Metadata markers count too.

**One-shot types:** Kick, Snare, Clap, Rim, Hat (closed/open), Cymbal, Perc, Tom, 808/Sub, Bass, Synth, Keys, Pluck, Pad, Vocal, FX (riser, impact, sweep, texture), Foley.

**Loop types:** Drum (full, top, kick-free, percussion), Bass, Melodic (chords, keys, synth, guitar), Vocal, FX/Texture.

**Characteristics** (these are what he cares about most):
- **Punchy vs Soft:** transient strength, crest factor and attack time.
- **Long vs Short:** decay time, with category-relative thresholds (a long hat is not a long 808).
- **Wet vs Dry:** reverb tail and decay shape, plus CLAP.
- **Snares specifically: Body vs Tight.** "Body" means big, thwacky, with low-mid energy and longer decay. "Tight" means sharp, short, high centroid, the UKG snare/rim style.
- **Loop feel: Straight vs Swung/Groovy.** Measure how far onsets deviate from a straight 16th grid at the detected tempo, using swing ratio and microtiming. This replaces BPM folders entirely.
- **Melodic material:** key and scale, plus a tonal type (pad, keys, pluck, etc.).

Store every raw feature value in the DB, not just the labels. That way new characteristics and thresholds can be added later without re-analysis.

## 6. Default folder structure

Rules from the owner:
- **3 levels max.**
- **Prefer bigger folders over many tiny ones.** He wants to scan long lists by eye, not dig through folders.
- **No BPM folders for loops.** BPM is usually in the filename, and Live warps anyway.

```
<Library Root>/
  One Shots/
    Kicks/         Punchy/  Soft/
    Snares/        Body/    Tight/
    Claps/
    Hats & Cymbals/
    Percussion/
    808 & Bass/
    Melodic/       (synth, keys, pluck, pad — mixed, key in DB)
    Vocals/
    FX/
  Loops/
    Drums/         Straight/  Swung/
    Tops & Percs/  Straight/  Swung/
    Bass/
    Melodic/
    Vocals/
    FX & Textures/
  MIDI/
  _Review/
  _Duplicates/     (only if user chooses quarantine over trash)
```

Subfolders are only created when a category would otherwise exceed a configurable size (default: split at about 300 files). Small categories stay flat. The whole structure is driven by config (§8) and the default is just a template.

## 7. Duplicates and Splice re-downloads

The owner's scenario: a Splice sample gets moved into the library. Later he re-downloads it in Splice, and Splice puts a fresh copy back in the Splice folder. Now there are two copies.

- The DB keeps a permanent record of **content hash → current library path**, plus the original name and the original Splice path.
- `crate dedupe` (and an automatic check during `ingest`) finds files whose content hash already exists in the library and reports them as duplicates of the library copy.
- Resolution options, set in config with a per-run override: `trash` (default: send the incoming copy to Trash), `quarantine` (move to `_Duplicates/`), `keep`, or `symlink` (replace the duplicate with a symlink to the library copy, so Splice still sees a file at its path).
- `crate where <name>` answers "where did this file go?" from either its original or current name. This matters if renaming is ever turned on.
- Also detect near-duplicates (the same audio at a different bit depth or sample rate) by comparing a downsampled PCM fingerprint. Report these but never auto-delete them.

## 8. Config file (example to ship as default)

```yaml
library_roots:
  - ~/Music/Samples Library
sources:
  splice_folder: ~/Splice/Samples        # verify actual default Splice path on macOS
external_volumes: true                  # track volume UUID so unmounted drives don't look like deleted files

review_threshold: 0.6
split_folder_threshold: 300
max_depth: 3

rename:
  enabled: false
  template: "{type}_{character}_{key}_{bpm}_{original}"   # tokens skipped if unknown

duplicates: trash                       # trash | quarantine | keep | symlink

taxonomy:
  one_shots:
    kick:  { folder: "One Shots/Kicks",  split_by: punch }
    snare: { folder: "One Shots/Snares", split_by: snare_body }
    # ...
  loops:
    drums: { folder: "Loops/Drums", split_by: feel }
    # ...

clap_prompts:
  kick: ["a kick drum", "a bass drum hit"]
  snare_tight: ["a short tight snare", "a crisp UK garage rimshot"]
  # ...

non_audio:
  midi: "MIDI"
  presets:                               # extension → destination
    ".fxp": "~/Library/Audio/Presets/Xfer Records/Serum Presets/User"   # verify real paths
    ".vital": "~/Music/Vital/User/Presets"
    ".adv": "<Ableton User Library>/Presets"
    ".adg": "<Ableton User Library>/Presets"
    unknown: "_Presets Unsorted"
  other: leave                           # leave | "_Other"
```

Detect the real Ableton User Library and plugin preset paths on first run where possible, and ask the user to confirm them in `crate init`.

## 9. Performance and robustness

- 100 GB+ libraries: parallelize analysis with `--jobs`, defaulting to the CPU count minus one. Batch CLAP inference.
- **Resumable:** if analysis of 40k files is interrupted, a re-run continues where it stopped.
- Analyze only the first ~30 s of long files for classification. Key and feel detection can use the full loop up to a cap.
- Cross-volume moves follow the copy → verify → delete path. Same-volume moves use an atomic rename.
- Use a clear progress UI with rich progress bars and an ETA, and print a summary table at the end.

## 10. Testing and evaluation

- **Never commit copyrighted samples.** Generate synthetic fixtures in tests: a synthesized kick (pitch-swept sine plus click), a noise-burst snare with short vs long decay, straight vs swung click loops, and tonal loops in known keys.
- Unit tests cover the metadata parser, which needs many real-world Splice filename patterns as strings, plus the move/undo engine, collision handling, dedupe and the config schema.
- Integration test: build a temp nested "pack" with zips, run `ingest --apply`, assert the structure, run `undo`, and assert the original state comes back byte-for-byte.
- `crate eval <labels.csv>`: lets the owner hand-label a few hundred of his own samples and get per-category precision/recall. Use it to tune thresholds and prompts.

## 11. Repo polish (portfolio quality)

- A README with the problem statement, a GIF placeholder of the CLI in action, install steps, a quickstart, a config reference and a section on how classification works (metadata + DSP + CLAP fusion).
- `ARCHITECTURE.md` with a module diagram.
- MIT license, CI badge, `CONTRIBUTING.md`, conventional commits and a tagged `v0.1.0`.
- Clean module layout, for example: `crate/cli.py`, `unpack.py`, `analyze/{features,metadata,clap,fusion}.py`, `taxonomy.py`, `planner.py`, `mover.py` (the journal plus undo), `dedupe.py`, `db.py`, `config.py`.

## 12. Milestones (build in this order and stop for review after each)

1. **Foundation:** project skeleton, config, DB schema, `unpack`, the move planner, the journal and `undo`, and dry-run plan output. Sort by **metadata only** (filename and folder keywords). This is already useful and proves the safety engine.
2. **Audio analysis:** DSP features, loop vs one-shot detection, and key and BPM detection, with caching by content hash.
3. **CLAP and fusion:** zero-shot type classification, confidence scores, `_Review`, and `review`/`correct`.
4. **Characteristics:** punchy/soft, long/short, wet/dry, body/tight snares, straight/swung loop feel, and auto-splitting large folders.
5. **Dedupe and Splice:** content-hash dedupe, near-duplicate reports, symlink mode and `where`.
6. **Non-audio routing:** MIDI, presets to plugin folders, `reorganize`, and opt-in renaming.
7. **Polish:** README, eval command, CI and the release.

## 13. Open questions (ask me before or during Milestone 1)

- The library root location.
- Whether the Splice folder is the default path.
- Which plugins' presets I actually have.
- Whether `ingest` should leave the original Splice files in place, which keeps Splice's "downloaded" state happy, or move them out. Explain the trade-off before I decide.
