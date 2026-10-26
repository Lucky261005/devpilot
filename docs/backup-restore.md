# Backup and restore (Docker Compose deployment)

Operator runbook for the Compose stack in `docker-compose.yml`. Run every command from the
repository root on the host, with the stack running. Commands are bash (Linux, macOS, or Git Bash
on Windows). In Git Bash, prefix the commands that pass a container path (`tar ... -C /data`) with
`MSYS_NO_PATHCONV=1`, or Git Bash rewrites `/data` into a Windows path and `tar` fails. PowerShell
5.1 is not suitable: its `>` and `<` re-encode binary data and corrupt the dump.

## What a backup must contain

| Item | Where it lives | Covered by |
|---|---|---|
| Accounts, sessions, repositories, search index, reviews, findings, feedback, audit log, rate-limit records, encrypted GitHub tokens | PostgreSQL (`pgdata` volume) | **1. Database** below |
| Repository snapshots (the files reviews read and the UI shows) | `snapshots` volume, mounted at `/data` in `backend` and `worker` | **2. Snapshots** below |
| `DEVPILOT_SECRET_KEY` | the root `.env` | **3. Configuration**: copy it yourself, separately |
| The rest of `.env` (registration mode, invite code, GitHub App credentials, LLM settings) | the root `.env` | **3. Configuration** |
| GitHub App registration and users' authorizations | GitHub | not backed up; it lives at GitHub |

What a database backup alone does **not** give you:

- **Repository files.** Without the snapshots volume, restored repositories still list their
  findings, but file views fail and new reviews cannot run until each repository is imported again.
- **Readable GitHub tokens.** Tokens are stored encrypted with `DEVPILOT_SECRET_KEY`. Restored with a
  different key, they cannot be decrypted, and every user must connect GitHub again. The same key
  also keys the hashed sign-in and per-IP rate-limit records; with a new key those simply start
  over.
- **GitHub-side state.** Revoking or reinstalling the GitHub App, or a user revoking access on
  GitHub, is not undone by a restore.

Keep the backup files and the secret key in different places: the dump contains encrypted tokens,
password hashes, email addresses and source code excerpts, so treat it as sensitive.

## 1. Database

```bash
docker compose exec -T db pg_dump -U devpilot -d devpilot -Fc > devpilot-$(date +%Y%m%d-%H%M%S).dump
```

- `pg_dump` runs inside the `db` container and connects over its local socket, which the PostgreSQL
  image trusts, so no password appears on a command line, in the process list or in a script.
- `-Fc` is PostgreSQL's compressed custom format, read by `pg_restore`. It is a consistent
  snapshot taken while the stack keeps running.
- The output goes to the current directory on the host. A dump with only the header (a few hundred
  bytes) means the command failed; check its output.

## 2. Snapshots

```bash
docker compose exec -T backend tar -czf - -C /data . > devpilot-data-$(date +%Y%m%d-%H%M%S).tar.gz
```

Take it right after the database dump. A review that finishes between the two can leave a snapshot
folder without its row, or the reverse; both are harmless (`cleanup` and re-import handle them).

## 3. Configuration and the secret key

`DEVPILOT_SECRET_KEY` changes rarely, so save it once (and again only if you rotate it), not with
every backup:

- Store it in a password manager (Bitwarden, KeePassXC, 1Password, …) as a secure note, together
  with the rest of the root `.env` if you like. Do not paste it into chat, email or a cloud document.
- Do not keep it in the backup folder. Someone holding both a dump and the key can decrypt the
  stored GitHub tokens.

## Current policy (portfolio project)

DevPilot is not yet a production service, so there are **no scheduled backups**. Run
`scripts/backup.sh` by hand before a database migration or any risky change, when the data matters.
Git does not protect the ignored databases, the `.env` files or uncommitted work; back those up
separately if you need them. Scheduling (below) is left for a real deployment.

## Routine backups (one command)

`scripts/backup.sh` runs the two commands above with a timestamp and writes to temporary
`*.partial` files first, renaming them only when **both** succeed. A failed run (stack not running,
disk full, Docker stopped) exits non-zero and leaves no file with a final name, so every
`devpilot-*.dump` in the folder is complete. It never deletes anything.

```bash
scripts/backup.sh /d/DevPilotBackups     # Git Bash path for D:\DevPilotBackups
```

It prints only the two file names and sizes. No password is used: `pg_dump` connects over the
container's local socket. Cost per run: a few seconds of CPU and two `docker compose exec`
processes that exit when done; nothing keeps running in the background.

### Schedule it with Windows Task Scheduler (for a real deployment; not used now)

No extra service or container is needed. The task runs only while you are signed in and Docker
Desktop and the stack are running; otherwise it fails cleanly and writes nothing.

1. Open **Task Scheduler** → **Create Basic Task**. Name: `DevPilot backup`.
2. Trigger: **Daily** (or **Weekly** if the data changes little), at a time the PC is usually on.
3. Action: **Start a program**.
   - Program: `C:\Program Files\Git\bin\bash.exe` (your Git for Windows `bin\bash.exe`)
   - Arguments: `scripts/backup.sh /d/DevPilotBackups`
   - Start in: the repository folder, for example `D:\Lucky CS\Projects\devpilot`
4. Finish, then open the task's **Properties**:
   - **Settings**: tick *Run task as soon as possible after a scheduled start is missed*; set
     *Stop the task if it runs longer than* to **30 minutes**.
   - **Conditions**: untick *Start the task only if the computer is on AC power* on a laptop, if you
     want backups on battery.
5. Right-click the task → **Run** once, and check that two new files appear in the folder.

**Is it working?** In Task Scheduler, *Last Run Result* `0x0` means both files were written; any
other value means nothing was written for that run. Check the folder for a recent date now and then.

### Retention: keep the disk from filling

Each run adds one dump and one archive (DevPilot's are usually a few MB; check yours after the first
run). Nothing is deleted automatically. A modest policy:

- keep the **last 7 daily** backups, plus **one per month for 3 months**;
- delete older ones by hand, about once a month.

To see what that policy would remove, from Git Bash (lists only, deletes nothing):

```bash
ls -1t /d/DevPilotBackups/devpilot-[0-9]*.dump | tail -n +8           # dumps older than the newest 7
du -sh /d/DevPilotBackups                                              # total space used
```

Each `devpilot-<stamp>.dump` belongs with the `devpilot-data-<stamp>.tar.gz` of the same stamp;
delete them together. Leftover `*.partial` files only appear if the PC lost power mid-run; they
are incomplete and safe to delete.

Put the folder on the disk with the most free space (here D:, not C:).

### Keep a copy off this PC

A backup on the same disk does not survive a disk failure or a lost laptop. Every week or so, copy
the newest pair of files to an external drive, or to cloud storage you control (OneDrive, Google
Drive). The dump contains password hashes, emails, encrypted tokens and code excerpts: if it goes to
the cloud, put it in an encrypted archive first (for example 7-Zip with AES-256 and a password kept
in your password manager).

## Verify a backup: restore drill

This restores into a **separate, throwaway PostgreSQL container** that is not part of the stack and
has no published port. It never touches the running database.

```bash
DUMP=devpilot-YYYYMMDD-HHMMSS.dump   # the file to check

# 1. Throwaway server (same major version as the stack). Trust auth is safe here: no port is published.
docker run -d --rm --name devpilot-restore-test -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16-alpine
until docker exec devpilot-restore-test pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done

# 2. Restore into a new database there.
docker exec devpilot-restore-test createdb -U postgres devpilot_restore
docker exec -i devpilot-restore-test pg_restore -U postgres -d devpilot_restore --no-owner --no-privileges --exit-on-error < "$DUMP"

# 3. Check it: schema version and row counts.
docker exec devpilot-restore-test psql -U postgres -d devpilot_restore -c "select version_num from alembic_version"
docker compose exec backend alembic heads    # must print the same revision, marked (head)
docker exec devpilot-restore-test psql -U postgres -d devpilot_restore -c \
  "select (select count(*) from users) users, (select count(*) from repositories) repositories,
          (select count(*) from review_jobs) reviews, (select count(*) from findings) findings"
docker compose exec db psql -U devpilot -d devpilot -c \
  "select (select count(*) from users) users, (select count(*) from repositories) repositories,
          (select count(*) from review_jobs) reviews, (select count(*) from findings) findings"

# 4. Remove the throwaway server (--rm deletes it and its data).
docker stop devpilot-restore-test
```

The restore is good when `pg_restore` exits without errors, `alembic_version` equals the head
revision, and the counts match the live database at the time of the backup (the live numbers can
only have grown since).

To check the snapshot archive: `tar -tzf devpilot-data-*.tar.gz | head` lists `./snapshots/<repository id>/...`.

## Recovering a deployment

Restore into a **new, empty** stack, never over a running one:

1. On the target host, put the saved `.env` (same `DEVPILOT_SECRET_KEY`) in the repository root.
2. Start only the database: `docker compose up -d db`.
3. Restore: `docker compose exec -T db pg_restore -U devpilot -d devpilot --no-owner --exit-on-error < "$DUMP"`.
   This requires the new database to be empty. If it fails, remove the volumes
   (`docker compose down -v` on the **new** stack only) and start again.
4. Start the backend: `docker compose up -d backend`. Its `alembic upgrade head` is a no-op on a
   current dump and upgrades an older one.
5. Restore the files: `docker compose exec -T backend tar -xzf - -C /data < devpilot-data-*.tar.gz`.
6. Start the rest: `docker compose up -d`, then sign in and open a repository and a review.

## What stays manual

The stack has no scheduler of its own: scheduling uses the host's (Task Scheduler above; cron or a
systemd timer on Linux, with the same `scripts/backup.sh` line). Deleting old backups, copying them
off the machine and repeating the restore drill (after upgrades, and every few months) are done by
hand.
