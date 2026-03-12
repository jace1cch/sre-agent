# Release Guide

This document describes the process for creating a new release of `sre-agent`.

## Prerequisites

- You have push access to the repository.
- All features and fixes intended for the release have been merged into `develop`.
- CI is passing on `develop`.

## Steps

### 1. Create a release branch

Branch off `develop` using the `release/` prefix:

```bash
git checkout develop
git pull origin develop
git checkout -b release/X.Y.Z
```

### 2. Bump the version

Update the version in `pyproject.toml`:

```toml
version = "X.Y.Z"
```

Commit the version bump:

```bash
git add pyproject.toml
git commit -m "Bump version to X.Y.Z"
git push -u origin release/X.Y.Z
```

### 3. Open a pull request to main

Open a PR from `release/X.Y.Z` → `main` (not `develop` — the release goes directly to `main`).

Ensure CI passes and get the required approvals.

### 4. Merge and tag

Once the PR is approved, merge it into `main` via GitHub. Then tag the merge commit locally:

```bash
git checkout main
git pull origin main
git tag X.Y.Z
git push origin X.Y.Z
```

### 5. Merge back into develop

Open a second PR from `release/X.Y.Z` → `develop` on GitHub so the version bump and any last-minute fixes are not lost. Get it approved and merge.

### 6. Publish to PyPI

Publishing happens automatically via GitHub Actions when a version tag is pushed
(see `.github/workflows/publish.yml`). The workflow uses
[Trusted Publishers](https://docs.pypi.org/trusted-publishers/) so no API tokens
need to be stored as secrets.

Verify the release is live at https://pypi.org/project/sre-agent/.

### 7. Create a GitHub release

Create a release on GitHub from the new tag:

```bash
gh release create X.Y.Z --generate-notes --title "X.Y.Z"
```

Review and edit the auto-generated notes as needed.

## Versioning

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR** — incompatible API or behaviour changes
- **MINOR** — new functionality, backwards-compatible
- **PATCH** — backwards-compatible bug fixes

## Hotfixes

For urgent fixes against a release that is already published, branch off `main`:

```bash
git checkout main
git pull origin main
git checkout -b hotfix/X.Y.Z
```

Follow the same process from step 2 onwards: bump version, open a PR to `main`, merge, tag, publish, create a GitHub release, and merge back into `develop`.
