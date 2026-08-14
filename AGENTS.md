# Lake Balaton Thermal Monitoring

Read `PROJECT_CONTEXT.md` and `DECISIONS.md` before substantive work. Treat approved, non-superseded decisions in `DECISIONS.md` as constraints and proposed decisions as unresolved.

## Governance

- The main Codex task is the coordinator and the only interface for user approval.
- `DECISIONS.md` is the authoritative versioned register for approved scientific and scope decisions. Approved decisions must be recorded there with approval provenance.
- Chat-only proposals are not approved and must not be treated as implementation authority.
- When registered decisions conflict, the newest approved, non-superseded decision controls.
- Ask the user before approving or changing any material scientific or scope decision, including datasets, periods, formulas, thresholds, sensor roles, terminology, outputs, deployment strategy, or thesis–internship separation. Material decisions always require the user's explicit approval.
- Do not implement the GEE application until the relevant methodology or task specification is explicitly approved.
- Use `thermal_remote_sensing_researcher` for evidence and method research, `gee_application_engineer` for approved implementation, and `scientific_validator` for independent review.
- Keep research and validation read-only. Only the engineer may edit implementation files, and only within an approved specification.
- The validator reports findings to the coordinator and never silently fixes files.
- Prefer parallel agents only for independent read-heavy work. Keep production edits under one engineer to avoid conflicts.
- Preserve unrelated user work, make changes reviewable, validate proportionately, and do not commit unless the user explicitly requests it.
