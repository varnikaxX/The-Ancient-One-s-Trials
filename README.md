# The Ancient One's Trials

**Constraint-satisfaction interview scheduler for campus placements** (Team SheCodes, Webster 2026).

Students rank interview slots, a Google OR-Tools CP-SAT engine finds the best conflict-free schedule, the coordinator approves it, and everyone is notified. This guide shows how to set up your computer and run the whole project locally.

## Contents
1. [What you will run](#1-what-you-will-run)
2. [Prerequisites](#2-prerequisites)
3. [Get the code](#3-get-the-code)
4. [Quick start on Windows](#4-quick-start-on-windows)
5. [Quick start on Linux and macOS](#5-quick-start-on-linux-and-macos)
6. [Configuration (`backend/.env`)](#6-configuration-backendenv)
7. [Check that everything is running](#7-check-that-everything-is-running)
8. [Log in and try it](#8-log-in-and-try-it)
9. [Optional: send real emails](#9-optional-send-real-emails)
10. [Optional: run the frontend without the backend](#10-optional-run-the-frontend-without-the-backend)
11. [Everyday commands](#11-everyday-commands)
12. [Troubleshooting](#12-troubleshooting)
13. [Project structure](#13-project-structure)

---

## 1. What you will run

The project is six small programs that work together. Five of them must be running at the same time.

| Part | What it does | Address |
|---|---|---|
| PostgreSQL | Stores all data | `localhost:5432` |
| Redis | Job queue, cache and live notifications | `localhost:6379` |
| API (FastAPI) | Backend rules and endpoints | `http://localhost:8000` |
| Worker (Celery) | Runs the solver and sends emails in the background | none |
| Beat (Celery) | Timer for recurring jobs: email delivery, reminders, result release | none |
| Frontend (React + Vite) | The website you open in the browser | `http://localhost:5173` |

PostgreSQL and Redis usually run as background services. You start the API, worker, beat and frontend yourself, in four terminal windows.

---

## 2. Prerequisites

Install these once. After each install, **close and reopen your terminal** so it sees the new program.

| Software | Version | Check with |
|---|---|---|
| Python | 3.11 or newer | `python --version` |
| Node.js | 18 or newer | `node --version` |
| PostgreSQL | 15 or newer | `psql --version` |
| Redis-compatible server | any recent | `memurai-cli ping` (Windows) or `redis-cli ping` |
| Git | any | `git --version` |

### Windows
- **Python:** download from python.org. On the first installer screen, tick **Add python.exe to PATH**.
- **Node.js:** download the LTS version from nodejs.org.
- **PostgreSQL:** download the installer from postgresql.org. **Remember the password you set for the `postgres` user.** Leave the port as `5432` and include all components, because the project needs the `btree_gist` extension that ships with them.
  - If `psql --version` is not found, add the `bin` folder to PATH: Start menu, search **environment variables**, open **Edit the system environment variables**, **Environment Variables**, select **Path** under System variables, **Edit**, **New**, and paste something like `C:\Program Files\PostgreSQL\18\bin`.
  - Check the service is running: press `Win + R`, type `services.msc`, find **postgresql-x64-XX** and confirm it says Running.
- **Redis:** Redis has no official Windows build. Install **Memurai Developer Edition** (memurai.com), which runs as a Windows service and starts automatically. Check it with `memurai-cli ping`, which should answer `PONG`. Alternative: install WSL (`wsl --install`), then inside Ubuntu run `sudo apt install redis-server -y` and `sudo service redis-server start`.

### macOS
```bash
brew install python node postgresql@16 redis git
brew services start postgresql@16
brew services start redis
```

### Ubuntu / Debian
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql postgresql-contrib redis-server git
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
```
`postgresql-contrib` provides `btree_gist`. Redis and PostgreSQL start automatically after installation.

---

## 3. Get the code

```powershell
git clone https://github.com/varnikaxX/The-Ancient-One-s-Trials.git
cd The-Ancient-One-s-Trials
```

If you downloaded a zip instead, unzip it and open a terminal **in the folder that contains `backend`, `frontend`, `scheduler` and `install.ps1`**. This is called the repo root. Every command below is run from there unless it says otherwise.

---

## 4. Quick start on Windows

Use **PowerShell** from the repo root.

### Step 1: allow the helper scripts to run
Files downloaded from the internet are blocked by Windows. Unblock them once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
Get-ChildItem -Recurse -Filter *.ps1 | Unblock-File
```

### Step 2: install the Python and npm packages

```powershell
.\install.ps1
```

This creates a `.venv` folder, installs the Python packages and then runs `npm install` for the frontend. It takes a few minutes.

### Step 3: create your settings file

```powershell
Copy-Item backend\infra\.env.example backend\.env
notepad backend\.env
```

Set `DATABASE_URL` to use your own PostgreSQL password:

```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/ancient_trials
```

Leave `USE_STUB_SOLVER=false` so the real OR-Tools engine is used. If your password contains characters like `@` or `#`, URL-encode them (`@` becomes `%40`). A simple password avoids that.

### Step 4: create the database

```powershell
.\setup_db.ps1 -Password YOUR_PASSWORD
```

This creates the `ancient_trials` database, enables `btree_gist`, builds the tables and loads the demo data. It ends by listing the tables. If it says the database already exists, that is fine.

### Step 5: start the four programs
Open **four separate PowerShell windows**, each in the repo root, and run one script in each:

| Window | Command |
|---|---|
| 1. API | `.\run_api.ps1` |
| 2. Worker | `.\run_worker.ps1` |
| 3. Beat | `.\run_beat.ps1` |
| 4. Frontend | `.\run_frontend.ps1` |

Leave all four open. Then open **http://localhost:5173** in your browser.

<details>
<summary>Prefer to run the commands by hand instead of the scripts?</summary>

```powershell
# one-time install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; cd ..

# database
$env:PGPASSWORD="YOUR_PASSWORD"
createdb -U postgres -h localhost ancient_trials
psql -U postgres -h localhost -d ancient_trials -c "CREATE EXTENSION IF NOT EXISTS btree_gist;"
psql -U postgres -h localhost -d ancient_trials -f backend/db/migrations/001_init.sql
psql -U postgres -h localhost -d ancient_trials -f backend/db/seed.sql

# each of these in its own window, from the repo root
.\.venv\Scripts\Activate.ps1; cd backend; $env:PYTHONPATH=".."; uvicorn app.main:app --reload --port 8000
.\.venv\Scripts\Activate.ps1; cd backend; $env:PYTHONPATH=".."; celery -A workers.celery_app worker --loglevel=info --pool=solo
.\.venv\Scripts\Activate.ps1; cd backend; $env:PYTHONPATH=".."; celery -A workers.celery_app beat --loglevel=info
cd frontend; npm run dev
```

On Windows, Celery's beat scheduler cannot be embedded in the worker (`-B`), so it runs in its own window.
</details>

---

## 5. Quick start on Linux and macOS

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt ortools
cp backend/infra/.env.example backend/.env
```

> Use `backend/requirements.txt` plus `ortools` here. The root `requirements.txt` is a Windows export and includes `pywin32`, which will not install on Linux or macOS.

Edit `backend/.env` so `DATABASE_URL` matches your PostgreSQL user, for example `postgresql://youruser:yourpassword@localhost:5432/ancient_trials`. If your PostgreSQL uses the default `postgres` account on Linux, create a database role first: `sudo -u postgres createuser -P youruser`.

Create the database:

```bash
createdb ancient_trials          # on Linux you may need: sudo -u postgres createdb ancient_trials
psql -d ancient_trials -c "CREATE EXTENSION IF NOT EXISTS btree_gist;"
psql -d ancient_trials -f backend/db/migrations/001_init.sql
psql -d ancient_trials -f backend/db/seed.sql
cd frontend && npm install && cd ..
```

Start four terminals, each from the repo root:

```bash
# 1. API
source .venv/bin/activate && cd backend && PYTHONPATH=.. uvicorn app.main:app --reload --port 8000

# 2. Worker
source .venv/bin/activate && cd backend && PYTHONPATH=.. celery -A workers.celery_app worker --loglevel=info

# 3. Beat
source .venv/bin/activate && cd backend && PYTHONPATH=.. celery -A workers.celery_app beat --loglevel=info

# 4. Frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**.

---

## 6. Configuration (`backend/.env`)

The backend reads `backend/.env` by itself at startup. You do not need to load it into your terminal. **Restart the API, worker and beat after changing it.** Never commit this file. It is already in `.gitignore`.

| Variable | Meaning | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/trials` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `JWT_SECRET` | Key that signs logins. Change it for any shared setup | placeholder |
| `JWT_EXPIRY_MINUTES` | How long a login lasts | `720` |
| `SLOT_MINUTES` | Interview slot length | `30` |
| `USE_STUB_SOLVER` | `false` uses the real OR-Tools engine, `true` uses a simple greedy stand-in | `false` |
| `SOLVER_TIME_LIMIT` / `RESCHEDULE_TIME_LIMIT` | Seconds the solver may think | `20` / `10` |
| `CORS_ORIGINS` | Allowed frontend addresses | `http://localhost:5173,http://127.0.0.1:5173` |
| `EMAIL_FROM`, `SMTP_*`, `RESEND_API_KEY`, `EMAIL_DRY_RUN` | Email delivery (see [section 9](#9-optional-send-real-emails)) | emails are only logged |
| `CELERY_EAGER` | `true` runs background jobs inside the API (no worker needed, for quick demos) | `false` |

---

## 7. Check that everything is running

| Program | What you should see |
|---|---|
| API window | `Application startup complete.` and no red database errors |
| Browser at `http://localhost:8000/docs` | The interactive API page |
| Worker window | A `[tasks]` list, then `celery@... ready.` |
| Beat window | Lines like `beat: Starting...` and `Scheduler: Sending due task ...` |
| Frontend window | `Local: http://localhost:5173/` |
| Browser at `http://localhost:5173` | The Aetherion sign-in page |

---

## 8. Log in and try it

The sign-in page has three gateways: choose the role first, then enter the email and password.

| Role | Email | Password |
|---|---|---|
| Coordinator | `coordinator@trials.edu` | `Passw0rd!` |
| Interviewer | `arjun@kamartaj.com` | `Passw0rd!` |
| Interviewer | `meera@kamartaj.com` | `Passw0rd!` |
| Interviewer | `kabir@sanctum.io` | `Passw0rd!` |
| Student | create one on the sign-up page | your choice |

Students register through **Create an account**. Interviewer and coordinator accounts are fixed in the demo data.

### A five-minute walkthrough
1. **Interviewer** (`arjun@kamartaj.com`): open **Availability**, click or drag a few 30-minute cells, and save. The seeded slots on 3 November are already shown.
2. **Student:** register, open **Companies**, pick **Kamar-Taj Labs**, select up to 3 slots, reorder them to set the rank, and submit. Status shows *Pending*.
3. **Coordinator:** open **Matching**, choose round 1 and run it. Wait a few seconds for the draft, then open it. **Approve** stays disabled until interviewers accept.
4. **Interviewer:** open **Proposals** and click **Accept**.
5. **Coordinator:** approve the draft. The student gets a notification, the interview appears on the calendar, and a calendar invite can be downloaded.
6. **Interviewer:** open **Results**, mark Pass or Fail with a score. The verdict shows on the student's dashboard. Results release immediately by default.

To delay results, change the setting in the database:
```sql
UPDATE config SET value = '30' WHERE key = 'result_delay_minutes';
```

---

## 9. Optional: send real emails

By default, emails are only printed in the worker window as `[dry-run email]`. To send real ones, add one provider to `backend/.env`, then restart the worker.

**Gmail** (needs 2-Step Verification, then an App Password from `https://myaccount.google.com/apppasswords`):

```
EMAIL_FROM=you@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your 16 character app password
EMAIL_DRY_RUN=false
```

**Resend** (`resend.com`): set `RESEND_API_KEY`, `EMAIL_FROM=onboarding@resend.dev` and `EMAIL_DRY_RUN=false`. On the free plan it only delivers to the address you signed up with.

Emails are queued and sent about every 10 seconds, so allow a short wait.

---

## 10. Optional: run the frontend without the backend

Create `frontend/.env.local` containing:

```
VITE_USE_MOCK=true
```

Restart `npm run dev`. The interface now runs on built-in sample data with no database, Redis or API. Delete the file (or set it to `false`) to go back to the real backend.

---

## 11. Everyday commands

| Task | Command |
|---|---|
| Stop a program | `Ctrl + C` in its window |
| Start everything again | Re-run the four `run_*.ps1` scripts (Windows) |
| Pull the latest code | `git pull`, then `.\install.ps1` if packages changed |
| Reset the database | Stop the API, worker and beat, then run `dropdb -U postgres -h localhost ancient_trials` and `.\setup_db.ps1 -Password YOUR_PASSWORD` |
| See registered students | `psql -U postgres -h localhost -d ancient_trials -c "SELECT u.name, u.email, s.reg_no, s.branch FROM users u JOIN students s ON s.user_id = u.id;"` |
| Rename rooms | `UPDATE rooms SET name='Room A' WHERE id=1;` in `psql` |
| Run the solver tests | `python -m unittest discover scheduler/tests` |
| Run the backend tests | `python -m unittest discover backend/tests` (needs PostgreSQL and Redis running) |

On Windows, if `psql` asks for a password every time, set it for the session with `$env:PGPASSWORD="YOUR_PASSWORD"`.

---

## 12. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `install.ps1 ... is not digitally signed` | Windows blocks downloaded scripts. Run `Get-ChildItem -Recurse -Filter *.ps1 \| Unblock-File`, or for one window `Set-ExecutionPolicy -Scope Process Bypass`. |
| `.\install.ps1 is not recognized` | You are in the wrong folder. `cd` to the repo root, where `dir` shows `install.ps1`. |
| `psql` or `createdb` is not recognized | The PostgreSQL `bin` folder is not on PATH. See [Prerequisites](#2-prerequisites), then reopen the terminal. |
| `password authentication failed for user "postgres"` | The password in `DATABASE_URL` does not match PostgreSQL. Test with `psql "postgresql://postgres:PASSWORD@localhost:5432/ancient_trials" -c "select 1;"` and fix `backend/.env`. |
| `database "ancient_trials" does not exist` | Run `.\setup_db.ps1 -Password YOUR_PASSWORD`. |
| `could not open extension control file ... btree_gist` | The PostgreSQL extras are missing. Reinstall with all components (Windows) or install `postgresql-contrib` (Linux). |
| `No module named 'psycopg'` or `celery is not recognized` | The packages are missing or the virtual environment is not active. Run `.\install.ps1`. The `run_*.ps1` scripts activate it for you. |
| `-B option does not work on Windows` | Expected. Run the worker and beat in separate windows, as `run_worker.ps1` and `run_beat.ps1` do. |
| Redis `Error 10061` or connection refused on port 6379 | Redis is not running. Start the **Memurai** service in `services.msc`, or `sudo service redis-server start` on Linux or WSL. |
| `Address already in use` (port 8000 or 5173) | An old copy is still running. Close the old windows, or find it with `netstat -ano \| findstr :8000` and stop it. |
| Page shows old styles or a blank screen | Hard refresh with `Ctrl + Shift + R`. |
| Network errors for `/api` in the browser | The API window is not running or crashed. Check it for errors. |
| Students see no slots | Interviewers must save availability, and the `rooms` table must have free rooms. Slot lists are cached for about 60 seconds. |
| Running matching never produces a draft | The worker window is not running, or no student has submitted preferences. Check the worker window. |
| Interviewer proposals do not appear | Matching must finish first. Refresh the **Proposals** page. |
| Emails do not arrive | `EMAIL_DRY_RUN` is still `true`, or the provider settings are wrong. Restart the worker and check it for `smtp error` lines. |
| `pip install -r requirements.txt` fails on Linux or macOS (`pywin32`) | Use `pip install -r backend/requirements.txt ortools`. |
| Demo login fails | Regenerate the demo hashes with `python backend/db/make_seed_hashes.py "Passw0rd!"` and reload the seed after clearing the old rows. |

---

## 13. Project structure

```
.
├── frontend/      React + Vite app (pages, components, API client, styles)
├── scheduler/     OR-Tools CP-SAT engine: batch matching, repair, panels, pipeline, ranking
├── backend/
│   ├── app/       FastAPI routers and services
│   ├── workers/   Celery app and tasks (solver, outbox, reminders, result release)
│   ├── db/        SQL migrations and seed data
│   ├── infra/     Nginx config and .env.example
│   └── tests/     Backend tests
├── contracts/     API notes, solver I/O format, SQL schema
├── install.ps1  setup_db.ps1  run_api.ps1  run_worker.ps1  run_beat.ps1  run_frontend.ps1
└── requirements.txt
```

---

**Team SheCodes (ID-207):** Vaishnavi Baranwal (frontend), Varnika Rameshkumar (scheduling engine), Ishika Agarwal (backend and database).
