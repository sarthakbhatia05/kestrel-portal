# Kestrel Provisions — Supply Chain Control Tower

Single, documented, reproducible answers for Kestrel Provisions' daily supply
chain operations.

Requirements are defined in [PRD.md](PRD.md). The architecture is described in
[docs/superpowers/specs/2026-09-08-kestrel-portal-design.md](docs/superpowers/specs/2026-09-08-kestrel-portal-design.md).
Decisions and their trade-offs are in [DECISIONS.md](DECISIONS.md).

## Prerequisites

- Python 3.11 or later
- Node.js 20 or later
- The assignment pack's `kestrel_ops.db`. It is **not** committed to this
  repository. The application opens it read-only and never modifies it.

## Cold start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and set `KESTREL_SOURCE_DB_PATH` to the path of `kestrel_ops.db`.
Relative paths are resolved from this repository's root, so the default
`../data/kestrel_ops.db` is correct when this repository sits inside the
assignment pack.

### 2. Install and build the curated data

```bash
cd backend
python -m venv .venv
```

Activate it — macOS/Linux `source .venv/bin/activate`, Windows PowerShell
`.venv\Scripts\Activate.ps1`, Git Bash on Windows `source .venv/Scripts/activate` — then:

```bash
pip install -r requirements-dev.txt
pip install -e . --no-deps
python -m kestrel.transform build
```

The build prints the row counts it produced and the quality ledger counts by
rule. It is idempotent: re-run it as often as you like. It takes 10-35 seconds depending on disk, and
writes `data/curated/kestrel_curated.db`.

### 3. Run the API

```bash
python -m uvicorn kestrel.main:app --reload
```

API docs at http://127.0.0.1:8000/docs

### 4. Run the interface

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Tests

```bash
cd backend && python -m pytest
```

Tests build a miniature source database in a temporary directory, so they do
not need `kestrel_ops.db` to be present.

Lint with `python -m ruff check src tests`.

## How it fits together

```
kestrel_ops.db  ──(read-only)──>  transform  ──>  kestrel_curated.db
                                      │                   │
                                      └──> quality_ledger │
                                                          v
                                                       metrics
                                                          │
                                          FastAPI routers │  (no arithmetic)
                                                          v
                                                    React frontend
```

Reporting surfaces read the curated database only. Every figure is produced by
exactly one metric implementation and is returned with the basis on which it
was derived.
