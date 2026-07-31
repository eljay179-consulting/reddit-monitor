# Deploying via GitHub Actions

One-time setup, in order. Each step blocks the next.

## 0. Prerequisites

- The GitHub org exists (created via github.com — this repo assumes it's already there)
- This folder is pushed to `eljay179-consulting/reddit-monitor` on `main`
- You have SSH access to johnsonserve already, under some username (`SSH_USER` below)

## 1. Install the deploy key on johnsonserve

A keypair was generated for this at `.deploy-key-DO-NOT-COMMIT/` (already gitignored — it must never be committed). On johnsonserve, as the user the Action will deploy as:

```bash
mkdir -p ~/.ssh
echo "<contents of deploy_key.pub>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

## 2. One-time manual clone on johnsonserve

The Action only runs `git pull` — it needs an existing clone and a working `.env` to pull into.

```bash
git clone git@github.com:eljay179-consulting/reddit-monitor.git /path/to/reddit-monitor
cd /path/to/reddit-monitor
cp .env.example .env
cp watches.example.json watches.json
# fill in .env for real (Reddit creds, HOST_VAULT_INBOX_PATH) and add your
# projects' subreddits/keywords to watches.json — see README.md
docker compose up -d --build
```

`.env` and `watches.json` are both gitignored and stay local to the server — `git pull` never touches either. Adding a new project later just means editing `watches.json` and `docker compose restart`, no git involved.

## 3. Create a Tailscale OAuth client

johnsonserve is tailnet-only, so the GitHub-hosted runner needs to join the tailnet before it can SSH in.

1. [Tailscale admin console](https://login.tailscale.com/admin/settings/oauth) → **Settings → OAuth clients → Generate OAuth client**
2. Scope: `Devices: Write` (minimum needed to have the runner join as a device)
3. Assign tag: `tag:ci` (create this tag if it doesn't exist yet — see step 4)
4. Save the **client ID** and **client secret**

## 4. Make sure `tag:ci` exists in your tailnet ACL policy

[Admin console → Access Controls](https://login.tailscale.com/admin/acls), check for a `tagOwners` entry. If `tag:ci` isn't defined, add:

```json
"tagOwners": {
  "tag:ci": ["autogroup:admin"]
}
```

Ephemeral CI nodes tagged `tag:ci` join and are torn down automatically after each run — they don't linger as persistent tailnet devices.

## 5. Add GitHub repo secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `TS_OAUTH_CLIENT_ID` | from step 3 |
| `TS_OAUTH_SECRET` | from step 3 |
| `SSH_HOST` | johnsonserve's tailnet IP (`100.116.62.94`) or MagicDNS name if enabled |
| `SSH_USER` | the SSH user from step 1 |
| `SSH_PRIVATE_KEY` | full contents of `.deploy-key-DO-NOT-COMMIT/deploy_key` (the private key, not `.pub`) |
| `DEPLOY_PATH` | the path used in step 2, e.g. `/path/to/reddit-monitor` |

## 6. Delete the local key files

Once `SSH_PRIVATE_KEY` is saved in GitHub and the public key is installed on johnsonserve, delete `.deploy-key-DO-NOT-COMMIT/` from this machine — it's no longer needed locally and shouldn't sit around as a plaintext private key.

```bash
rm -rf .deploy-key-DO-NOT-COMMIT
```

## Done

Every push to `main` now: joins the tailnet as an ephemeral `tag:ci` node → SSHes into johnsonserve → `git pull` → `docker compose up -d --build`.

To trigger a deploy without a code change, use the "Run workflow" button on the Actions tab (`workflow_dispatch` is enabled for this).
