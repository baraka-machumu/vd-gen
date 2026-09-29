# Working rules for this repo

- Spec: `docs/spec/00-original-specification.md` (frozen; cite as §N). Amendments are in `docs/review/` and `docs/DECISIONS.md`. Where they conflict, the ADRs win over the spec.
- Before starting a module, read its entry in `docs/MODULES.md` and any ADRs it depends on.
- Status: update `status/status.toml`, then run `python scripts/status/render_status.py`. Never hand-edit `status/STATUS.md`. A module is `DONE` only when its exit criteria are met and verified.
- Never claim a model or GPU path works on the GX10 unless it was tested there (spec §78). Otherwise report `UNSUPPORTED_ON_CURRENT_HARDWARE` / `UNAVAILABLE`.
- Fakes and mocks are allowed only in tests (spec §82).
- Runtime makes no external network calls unless the egress policy allows them (spec §38).
- Shell scripts must use LF line endings (enforced by `.gitattributes`).
