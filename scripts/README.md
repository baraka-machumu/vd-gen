# scripts/

| Path | Purpose | Module |
|---|---|---|
| `setup/` | `install.sh`, `verify_gx10.sh` (spec §74) | M31, M02 |
| `health/` | GPU smoke tests, health probes | M17, M02 |
| `models/` | Pinned model fetch + offline bundle (spec §50) | M16 |
| `backup/` | Backup/restore | M30 |
| `status/` | `render_status.py` — status tracker (ADR-011) | M00 |
