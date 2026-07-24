## Summary

## Behavior and security impact

## Verification

- [ ] `python3 scripts/self_verify.py`
- [ ] `python3 scripts/check_secrets.py`
- [ ] `PYTHONPATH=src python3 -m unittest discover -s tests -q`
- [ ] `PYTHONPATH=src python3 scripts/smoke_installed_matrix.py`
- [ ] Packaging/release smoke added when applicable
- [ ] Fixtures are synthetic and use registered provenance anchors
- [ ] No source CLI execution, source-store mutation, secrets, or real home paths
- [ ] Docs do not overclaim host UI, marketplace UI, or remote release evidence

## Related issue / evidence
