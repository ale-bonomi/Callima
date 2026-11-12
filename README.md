# Callima
Audio sample organizer that reads sample, categorizes by quality, and organizes them to new root directories based on user preferences. It can reorganize existing libraries or sort new packs into existing file structures.

> Status: Milestone 1 prototype. Files are sorted by filename and folder keywords only; audio analysis comes later. The command is called `crate`.

## Setup

You need [uv](https://docs.astral.sh/uv/). If you don't have it:

```bash
python3 -m pip install --user uv
```

If `uv` isn't found afterwards, add pip's user bin folder to your PATH (the path depends on your Python version):

```bash
export PATH="$HOME/Library/Python/3.10/bin:$PATH"
```

Install the project and its dev tools (uv downloads Python 3.12 if needed):

```bash
uv sync --python 3.12
```

## Usage

Create the config and database. It asks for your library root and Splice folder:

```bash
uv run crate init
```

Preview where files would go. This is a dry run and changes nothing:

```bash
uv run crate sort "/path/to/Some Pack"
```

Apply the plan:

```bash
uv run crate sort "/path/to/Some Pack" --apply
```

Other commands:

```bash
uv run crate ingest "/path/to/Some Pack" --apply   # unpack zips, classify and sort in one go
uv run crate unpack "/path/to/Some Pack"           # flatten nested folders and extract zips only
uv run crate status                                # tracked files and recent batches
uv run crate undo                                  # reverse the latest batch
uv run crate undo 3                                # reverse a specific batch
```

Every command is a dry run unless you pass `--apply`. Filenames are never changed, and `.asd` files move with their sample. By default `ingest` and `sort` copy files out of the Splice folder and leave the originals in place (`keep_originals` in the config).

Use a different config file with `--config`:

```bash
uv run crate --config ./my-config.yaml sort "/path/to/Some Pack"
```

## Development

```bash
uv run pytest        # tests
uv run ruff check .  # lint
uv run mypy          # type check
```
