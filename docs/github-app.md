# GitHub App setup (read-only import)

DevPilot connects to GitHub as a **GitHub App** using the user-authorization (web) flow. A user's
token can reach only repositories that the user can see **and** that the App is installed on, so
private repositories are available only when someone explicitly grants them. DevPilot never writes
to GitHub.

## Create the App

GitHub → Settings → Developer settings → GitHub Apps → **New GitHub App**:

| Setting | Value |
|---|---|
| GitHub App name | anything, for example `devpilot-<you>`; its URL name is the **slug** |
| Homepage URL | where you open DevPilot (development: `http://localhost:5173`) |
| Callback URL | that address + `/api/github/oauth/callback` (development: `http://localhost:5173/api/github/oauth/callback`; compose: `http://localhost:8080/api/github/oauth/callback`) |
| Expire user authorization tokens | **On** (DevPilot renews tokens with the refresh token) |
| Request user authorization (OAuth) during installation | **Off** (that redirect carries no DevPilot `state`, so the callback would reject it; users connect from Settings instead) |
| Setup URL | DevPilot's Settings page (development: `http://localhost:5173/settings`), with "Redirect on update" on |
| Webhook | **Off** (not used) |
| Repository permissions | **Contents: Read-only**, **Metadata: Read-only**, **Pull requests: Read-only**. Nothing else |
| Organization / account permissions | none |
| Where can this App be installed | "Only on this account" for a personal demo |

After creating it: note the **Client ID**, generate a **client secret**. DevPilot does not need the
App's private key: it acts only as the signed-in user, never as the installation.

## Configure DevPilot

In `backend/.env` (never commit it):

```
DEVPILOT_GITHUB_CLIENT_ID=<client id>
DEVPILOT_GITHUB_CLIENT_SECRET=<client secret>
DEVPILOT_GITHUB_APP_SLUG=<app slug>
DEVPILOT_SECRET_KEY=<Fernet key; required outside development, encrypts stored tokens>
```

Restart the API. Settings → **Connect GitHub**, authorize, then **Choose repositories** to install
the App on the repositories you want.

## What happens on import

1. The browser sends `owner/name` and a branch. The server lists the user's App installations and
   their repositories and refuses anything not in that list (a public repository that is readable
   but not granted is refused too). The canonical name comes from GitHub.
2. The branch is resolved to a commit SHA, the archive is downloaded **at that SHA** (redirects only
   to GitHub hosts, size-capped), and the SHA and branch are stored on the repository.
3. The existing import pipeline runs: safe ZIP extraction, then the file policy below. Nothing from
   the repository is executed.

**File policy** (`backend/app/services/ingestion.py`): secret-looking files (`.env*` except
examples, keys, keystores, `.npmrc`, `.netrc`, `credentials*`, `secrets.*` and more) are deleted;
generated or vendored directories (`node_modules`, `.venv`, `dist`, `build`, `vendor`, caches,
`.next`, `coverage` and more) are skipped; symlinks are removed; files over
`DEVPILOT_MAX_FILE_BYTES`, binary files and unsupported types are skipped and counted in
`skipped`.

## Token handling

- Access and refresh tokens are Fernet-encrypted in `github_accounts` and never sent to the browser.
- A token within 5 minutes of expiry is renewed; GitHub rotates the refresh token, and the row is
  locked while renewing.
- A rejected refresh, an expired refresh token, or a 401 from the API removes the stored connection;
  the UI then shows "Connect GitHub". If GitHub is unreachable, the connection is kept.
- **Disconnect** deletes DevPilot's copy. To also revoke on GitHub: GitHub → Settings →
  Applications → Authorized GitHub Apps.

## Tests

- Deterministic (always run): `tests/test_github_app.py` and the GitHub tests in `tests/test_api.py`
  use a mocked transport: grant enforcement, ungranted public repository, branch import and SHA,
  cross-user access, revoked token, rate limit, retry and backoff, pagination bounds, token renewal
  and rotation, OAuth decline and success.
- Live (opt-in): `tests/test_github_live.py`, with a **dedicated test account** and a disposable
  private repository; never a personal token. See the file header for the three variables, then:
  `uv run pytest -m live_github tests/test_github_live.py`.
