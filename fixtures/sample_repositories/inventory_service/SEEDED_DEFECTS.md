# Seeded defects (synthetic)

| File | Line(s) | Defect | Expected detector |
|------|---------|--------|-------------------|
| inventory/store.py | `load_items` | bare `except:` swallows all errors | ruff E722 |
| inventory/store.py | `run_report` | `subprocess` with `shell=True` on caller input | bandit B602 |
| inventory/store.py | `connect` | hardcoded password string | bandit B105/B106 |
| inventory/pricing.py | `apply_discount` | off-by-one: `>` should be `>=` for the 100-unit tier | AI only |
| inventory/pricing.py | `paginate` | last page dropped (`len // size`) | AI only |
| inventory/store.py | `read_config` | file opened without closing | AI only (resource) |
