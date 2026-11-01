# Lightsmith Deploy

The whole Lightsmith platform on one machine with Docker Compose:

| Service | URL (default) | From |
|---|---|---|
| **Community**: accounts, shared projects, forum, materials explorer | http://localhost:3000 | `lightsmith-community` |
| **Studio**: the simulation GUI (web mode) | http://localhost:8080 | `lightsmith-studio` |
| **Cloud**: compute API, job queue, CPU and GPU workers | http://localhost:8200 | `lightsmith-cloud` |
| **Materials**: optical-constants database API | http://localhost:8100 | `lightsmith-materials` |
| Mailpit: catches Community's sign-in emails | http://localhost:58025 | `axllent/mailpit` |

They share one Postgres 17 server (one database and role per product), one Redis (Cloud's job
queue) and one SeaweedFS S3 gateway (one bucket and key per product). Community is the identity
provider: it signs short-lived HS256 tokens that Cloud (`aud=compute`) and Materials
(`aud=materials-db`) verify with the shared `PLATFORM_JWT_SECRET`, and Studio signs in through it.

```
browser ── Community :3000 ──┬── Cloud API :8200 ── Redis ── workers (CPU, GPU)
        ── Studio    :8080   ├── Materials  :8100        │
                             └──────────── Postgres ── SeaweedFS S3 ──┘
```

## Requirements

- Docker with Compose v2.29 or newer. For the GPU worker: an NVIDIA GPU with Docker Desktop (WSL2)
  or the NVIDIA Container Toolkit; the worker image ships CUDA 12.8, so RTX 50xx cards work.
- [uv](https://docs.astral.sh/uv/), to build the library wheel.
- The sibling checkouts next to this one (or set `REPOS_DIR` in `.env`):

  ```
  lightsmith/ (or PlasmonHub/)   lightsmith-community/   lightsmith-studio/
  lightsmith-cloud/              lightsmith-materials/   lightsmith-deploy/
  ```

## Run it

```bash
uv run --no-project python scripts/prepare.py
```

```bash
docker compose up -d --build --wait
```

```bash
docker compose --profile import run --rm materials-import
```

```bash
uv run --no-project python scripts/smoke.py
```

1. `prepare.py` builds the library wheel (the library is not on PyPI yet) into `wheels/` and
   `lightsmith-cloud/wheels/`, and creates `.env` with fresh random secrets on first run. Re-run it
   after library changes, then rebuild.
2. `up` builds the four products from their checkouts and starts everything; migrations run as
   one-off containers first.
3. The import loads the pinned refractiveindex.info snapshot into Materials (a few minutes; run it
   once, it is idempotent).
4. `smoke.py` checks every service and the paths between them: a job through Cloud's queue and
   worker into S3, Community's tokens accepted by Cloud and Materials, Community using the real
   services rather than its built-in mocks, and Studio's configuration.

Sign in to Community with an email address; the link arrives in Mailpit. Put your address in
`ADMIN_EMAILS` first to become the admin. Demo content: `docker compose --profile seed run --rm
community-seed` (it wipes Community's tables).

### GPU worker

```bash
docker compose --profile gpu up -d --build --wait
```

The GPU worker serves the tiers that fit in its memory. Set `CPU_WORKER_QUEUES` so the CPU worker
only takes the larger tiers (for a 12 GB card: `gpu-24g,gpu-80g`); by default it serves every
tier, which is what a machine without a GPU needs. The worker image is large (about 8 GB, based on
`pytorch/pytorch` with CUDA 12.8).

### Stop, reset

```bash
docker compose down
```

`docker compose down -v` also deletes the volumes: every account, project, job and imported dataset.

## Production notes

- Put a TLS reverse proxy in front, set the `*_URL` variables in `.env` to the public `https://`
  origins (and `CLOUD_WS_URL` to `wss://`), and keep `BIND_ADDRESS=127.0.0.1`.
- Point `EMAIL_SERVER` at a real SMTP server, and consider GitHub sign-in (`AUTH_GITHUB_*`).
- Stripe billing in Cloud accepts test keys only (`sk_test_...`) at this stage.
- The bundled Postgres, Redis and SeaweedFS suit a single host. Managed equivalents (any Postgres,
  Redis and S3-compatible store) work by changing the URLs in `docker-compose.yml`.
- Back up the `pgdata` and `s3data` volumes.

## Licence

MIT. Each product repository carries its own licence file; third-party images keep theirs.
