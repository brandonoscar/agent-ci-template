# agent-ci-template

GitHub Actions for an app with an AI agent and a multi-tenant database: secret scanning, an eval gate, RLS checks, post-deploy smoke tests, and a check that notices when a scheduled job quietly stops running. Click **Use this template**, turn on what you need with repository variables, and replace the sample app.

| Workflow | Runs | What it does | Turn on with |
|---|---|---|---|
| `ci.yml` | every PR and push | lint and tests (replace with your own) | always on |
| `secrets.yml` | every PR and push, weekly | gitleaks over the PR's commits, or the whole history | always on |
| `evals.yml` | every PR and push | the eval gate from [agent-eval-harness](https://github.com/brandonoscar/agent-eval-harness): safety failures block the merge | `EVALS_ENABLED=true` |
| `evals-nightly.yml` | nightly | three runs of the suite; one issue listing failing, flaky, unreached and drifting cases | `EVALS_ENABLED=true` |
| `rls.yml` | every PR and push, weekly | [supabase-rls-guard](https://github.com/brandonoscar/supabase-rls-guard): RLS on every table, no view around it, no tenant query without the tenant column; weekly against the live catalog | `RLS_ENABLED=true` |
| `smoke.yml` | after each production deploy, every 6 hours | `scripts/smoke.py` against the deployed app: up, correct, fast enough | `SMOKE_ENABLED=true` |
| `liveness.yml` | every 6 hours | files an issue when a scheduled workflow hasn't succeeded on schedule within its allowed age | `LIVENESS_ENABLED=true` |

Set the variables under **Settings → Secrets and variables → Actions → Variables**. A workflow that isn't turned on shows its job as skipped.

**Skipped counts as passing for a required check.** GitHub treats a job skipped by its `if:` as a success, so a required status check on a workflow you haven't turned on lets every pull request merge without it. Make Evals or RLS a required check only after its variable is set.

## Rules every workflow follows

- **A check that didn't run is not a pass.** A missing `EVALS_TARGET`, `SMOKE_BASE_URL` or `DATABASE_URL`, a failed install, or a crash before any result fails the job, and the scheduled workflows file an issue saying it could not run. A credential-gated check that quietly skips stays broken for weeks.
- **Scheduled failures file one issue**, through `.github/actions/file-issue`: a new issue the first time, a comment on the same issue after that. A red scheduled run in the Actions tab is a run nobody opens.
- **Least privilege.** Every workflow defaults to `contents: read`. Only the jobs that file issues get `issues: write`, and liveness adds `actions: read`. Nothing uses `pull_request_target`, so pull requests from forks never see your secrets. GitHub's own actions and the two companion tools are pinned by commit, and the gitleaks download by checksum.
- **Pipelines keep their exit codes.** A step that pipes through `tee` uses `pipefail` or `PIPESTATUS`; without them the step takes `tee`'s exit code and a failed check passes. Error output goes through `tee` too, so the issue says why.
- **A timeout on every job and a concurrency group on every workflow**, so a hung run can't eat the minutes budget, and two runs of one workflow can't race to file the same issue.
- **Schedules run from the default branch only.** A cron on a feature branch never fires, so the nightly and weekly jobs start working the day they reach `main`.

## Turning things on

**Evals.** Commit cases under `evals/cases/` (one JSON file each) and a target function that runs your agent for one case. Then set `EVALS_ENABLED=true` and `EVALS_TARGET=my_app.evals:target`, and optionally `EVALS_CASES` and `EVALS_AGENT_GLOB`. Put your model provider's key in a secret (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; edit the workflow for others). See the [agent-eval-harness README](https://github.com/brandonoscar/agent-eval-harness) for the case format.

On a pull request the gate runs the deterministic cases and the cases whose files changed. Only when the pull request touches agent code does it also run every tier-1 safety case and a rotating slice of the other safety cases. `EVALS_AGENT_GLOB` says what agent code is: comma-separated patterns, default `src/*,prompts/*,pyproject.toml,*.lock,requirements*.txt`, so a model SDK bump counts. A pull request is compared with the commit it branched from, not with everything main gained since. The merge to main runs every case.

The nightly tracker compares replies with `evals/baseline.json`. Until you commit one, each night files an `unmeasured` finding that names the cases with no baseline reply. To make one, run the suite three times locally, read the replies, then store them:

```bash
for i in 1 2 3; do agent-eval run --cases evals/cases --target my_app.evals:target --json runs/run-$i.json; done
agent-eval track runs/*.json --cases evals/cases --baseline evals/baseline.json --update-baseline
```

**RLS.** Commit an `rls-guard.toml` ([format](https://github.com/brandonoscar/supabase-rls-guard#configure-it)) and set `RLS_ENABLED=true`. For the weekly live check, add a `DATABASE_URL` secret with a read-only role.

**Smoke.** Edit `smoke/checks.json` (path, expected status, expected JSON fields or text, time budget per check) and set `SMOKE_ENABLED=true` and `SMOKE_BASE_URL`.

```bash
python scripts/smoke.py --base-url https://app.example.com --checks smoke/checks.json
```

- Hosts that report deployments to GitHub (Vercel, Render, Netlify and others) trigger it after each successful deployment, against that deployment's URL. Only environments listed in `SMOKE_ENVIRONMENTS` count (comma-separated, any case, default `production`), so preview deployments aren't smoke-tested. Use the environment name your repository's **Deployments** page shows; the names each host uses are NOT VERIFIED here.
- A deployment that reports no URL is a run that could not check anything. It files an issue; it never falls back to `SMOKE_BASE_URL`, because that would test production and call it the new deployment.
- The checks and the script always come from the default branch, never the deployed commit, because this job can file issues.
- Redirects are not followed. A check sees the status the app sent, so expect the 30x itself or point the check at the final path. Otherwise an app that sends everything to its sign-in page would pass a check for `/`.

**Liveness.** Set `LIVENESS_ENABLED=true` and `LIVENESS_MAX_AGE` to the scheduled workflows you depend on, for example `secrets.yml=8d,evals-nightly.yml=2d,rls.yml=8d,smoke.yml=1d`.

- Only scheduled runs count. A pull request run of the same workflow says nothing about whether its schedule still fires.
- A workflow name it can't look up (a typo, an API error) is reported with GitHub's error, never as "never ran".
- It can't see GitHub stopping every schedule at once: GitHub disables schedules in a public repository after 60 days without activity, and a billing problem stops all runs. Liveness is a schedule too. For that case, create a check in an outside dead-man's-switch monitor (one that alerts when an expected ping doesn't arrive) and put its ping URL in a `LIVENESS_HEARTBEAT_URL` secret. Each liveness run pings it, and when GitHub stops running schedules the pings stop and the monitor alerts.

**Secrets.** On always. A pull request is scanned with the base branch's `.gitleaks.toml` and `.gitleaksignore`, and its `gitleaks:allow` comments don't count, so a pull request can't loosen its own scan. Change an allowlist in a pull request of its own, before the one that needs it. To make that reviewable, list `.gitleaks.toml` and `.gitleaksignore` in your `CODEOWNERS`.

## After you create your repo

- Replace `src/app/` with your app, `tests/` with its tests, and the steps in `ci.yml` with your own lint and test commands.
- Replace this README, and delete or restart `CHANGELOG.md`; both describe the template.
- `LICENSE` is the template's MIT licence. Keep it or choose your own for your project.
- Edit `smoke/checks.json` and the allowlist in `.gitleaks.toml` for your app.
- Set the repository variables for the workflows you want, and the secrets they use.

## What's in the box

```text
.github/workflows/       the seven workflows above
.github/actions/file-issue/  one issue per title: open it, or comment on it
.github/dependabot.yml   weekly updates for pip packages and pinned actions
.gitleaks.toml           default rules plus an allowlist for known non-secrets
scripts/smoke.py         post-deploy smoke checks (standard library only)
scripts/liveness.py      overdue scheduled workflows (standard library only)
smoke/checks.json        the checks smoke.py runs
src/app/server.py        a stand-in app for the smoke tests: replace it
tests/                   tests for the two scripts, run by ci.yml
```

## Development

```bash
pip install ruff pytest
ruff check . && ruff format --check . && pytest
```

Found a bug in the template itself? Open an issue at [brandonoscar/agent-ci-template](https://github.com/brandonoscar/agent-ci-template/issues). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE).
