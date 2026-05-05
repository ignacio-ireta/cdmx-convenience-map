# Personal Website Embed Sync

This repository is the source project for the CDMX convenience map. The personal website repository (`ignacio-ireta/ignacio-ireta.github.io`) keeps a committed static copy at:

```text
projects/cdmx-map/
```

That committed copy is what lets the project appear inside the broader personal website while this repository remains the canonical source for the app and data pipeline.

## Local sync

From this repository root:

```bash
cd frontend
npm ci
npm run build
cd ..
scripts/sync_website_embed.sh ../ignacio-ireta.github.io/projects/cdmx-map
```

The script removes the old embedded static files and copies `frontend/dist/` into the website path.

## Automated sync on push

`.github/workflows/deploy.yml` builds the Vite app on every push to `master`. After building, it can also check out the personal website repository and commit the updated static files into `projects/cdmx-map/`.

The cross-repository write needs one secret in `ignacio-ireta/cdmx-convenience-map`:

```text
WEBSITE_REPO_DEPLOY_KEY
```

Recommended setup:

1. Generate a dedicated deploy key pair.
2. Add the public key to `ignacio-ireta/ignacio-ireta.github.io` as a **write-enabled deploy key**.
3. Add the private key to `ignacio-ireta/cdmx-convenience-map` as the `WEBSITE_REPO_DEPLOY_KEY` Actions secret.

Why this shape: the default `GITHUB_TOKEN` can write to the repository running the workflow, but it cannot push to a different repository. A write deploy key gives the source repo exactly one narrow permission: update the website repo.

If the secret is missing, the workflow still builds and deploys this repository's own GitHub Pages artifact, but it skips the personal-website sync.
