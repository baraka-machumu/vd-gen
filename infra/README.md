# infra/ — Deployment config (M01, M29)

Used by [`../docker-compose.yml`](../docker-compose.yml). Private network only: nginx is the single published port,
and the object store is never published (ADR-010, spec §65).

| Path | Purpose |
|---|---|
| `nginx/` | Edge proxy: `/api/*`, `/health`, API docs; `/media/*` with `auth_request` arrives with M09 |
| `seaweedfs/` | Object store (ADR-015): start script that generates the S3 identity file from the environment; bucket init |
| `docker/` | Extra Dockerfiles (`spike-ltx.Dockerfile`: P0 native-pipeline fallback) |
| `postgres/`, `redis/` | Reserved for tuning config; the stock images are used as-is for now |
| `monitoring/` | Prometheus/Grafana (M29) |

Image tags are pinned in the compose file and all publish `linux/arm64` (spec §37).
