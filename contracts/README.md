# contracts/ — Shared job contracts (ADR-001)

Small Pydantic package shared by `backend/` and `ai-engine/`: job payloads, results, provider
capability enums. No heavy dependencies — it must install cleanly in both Python environments.
