# Kestrel Control Tower

One screen showing where Kestrel is losing service and money, plus a chatbot you can ask questions in plain English.

Setup takes about five minutes the first time.

---

## 1. What you need

- **Python 3.11 or newer**. Check with `python --version` (on macOS, `python3 --version`).
- **Node.js 20 or newer**. Check with `node --version`.
- **The assignment pack**, which contains `data/kestrel_ops.db`. The database is not in this repository.
- *Optional:* a **Gemini API key**, only needed for the chatbot. Everything else works without one.

## 2. Put the code in the right place

Clone this repository **inside the assignment pack folder**, next to `data/`:

```
FDE_Assignment_Pack_Kestrel_v1.1/
├── data/kestrel_ops.db      ← the database
└── kestrel-portal/          ← this repository
```

With that layout, the app finds the database by itself.

## 3. One-time setup

Open a terminal in the `kestrel-portal` folder.

**Step 1: create the settings file.**

macOS / Linux:

```bash
cp .env.example .env
```

Windows (PowerShell):

```powershell
Copy-Item .env.example .env
```

For the chatbot, open `.env` and add (or fill in) this line with your own key:

```
KESTREL_GEMINI_API_KEY=your-key-here
```

**Step 2: install the backend and build the data.** This takes about a minute.

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e . --no-deps
python -m kestrel.transform build
```

Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install -e . --no-deps
python -m kestrel.transform build
```

When the build finishes, it prints how many rows it built.

**Step 3: install the frontend.** From the `kestrel-portal` folder:

```bash
cd frontend
npm install
```

## 4. Run it

You need **two terminals**, both left open.

**Terminal 1: the backend.** Go to `kestrel-portal/backend`, activate the environment (`source .venv/bin/activate`, or `.venv\Scripts\Activate.ps1` on Windows), then run:

```bash
python -m uvicorn kestrel.main:app
```

**Terminal 2: the frontend.** Go to `kestrel-portal/frontend`, then run:

```bash
npm run dev
```

Then open **http://localhost:5173** in your browser.

---

## If something goes wrong

| You see | Do this |
|---|---|
| `Source database not found` | The database isn't at `../data/kestrel_ops.db`. Either move this folder into the assignment pack, or set `KESTREL_SOURCE_DB_PATH=` in `.env` to the full path of `kestrel_ops.db`. |
| `Curated database not found`, or the page shows errors | You skipped the build. Run `python -m kestrel.transform build` in `backend` with the environment active. |
| Windows says running scripts is disabled | Run `Set-ExecutionPolicy -Scope Process Bypass` in the same terminal, then activate again. |
| `python` or `pip` not found | On macOS / Linux use `python3`. On Windows, reinstall Python with "Add to PATH" ticked. |
| Port 8000 is already in use | Start the backend with `--port 8001`. Then start the frontend with `KESTREL_API_TARGET=http://127.0.0.1:8001 npm run dev` on macOS / Linux, or `$env:KESTREL_API_TARGET="http://127.0.0.1:8001"; npm run dev` in Windows PowerShell. |
| The chatbot says it is unavailable | Add `KESTREL_GEMINI_API_KEY` to `.env` and restart the backend. |

---

## Using it

- **Control tower:** fill rate, on-time-in-full, returns, near-expiry stock and temperature breaches, with the worst performers listed. Choose a region and period in the top bar. The page address updates, so you can bookmark or share any view.
- **Data quality:** what each number leaves out and why.
- **Ask anything:** type a question such as *"why did fill rate drop in the West last week?"*. The chatbot shows each measurement it takes, then answers. Every number comes from the same calculations as the dashboard.

Why things were built the way they are: [DECISIONS.md](DECISIONS.md).

## For developers

Run the tests (they don't need the real database) and the linter from `backend`, with the environment active:

```bash
python -m pytest
```

```bash
python -m ruff check src tests
```

- **API docs:** http://127.0.0.1:8000/docs while the backend is running.
- **How the data flows:** `kestrel_ops.db` → build step (read-only) → `kestrel_curated.db` → API → web page. The API does no calculating of its own: every number comes from one metric function and carries the basis it was calculated on.
- **More detail:** requirements in [PRD.md](PRD.md), and a build log in [PROGRESS.md](PROGRESS.md).
