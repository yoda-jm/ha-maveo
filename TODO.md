# TODO

## Extract library to a separate PyPI package

**Context:** Home Assistant's [developer guidelines](https://developers.home-assistant.io/docs/api_lib_index/) require all API/protocol-specific code to live in a standalone PyPI package, not bundled inside `custom_components/`. The library files currently duplicated in `custom_components/maveo/` violate this rule.

**Target structure:**
- `maveo/` → published as a PyPI package (e.g. `python-maveo`)
- `custom_components/maveo/manifest.json` declares it as a requirement — HA installs it automatically
- No library files left inside `custom_components/maveo/`

**Steps:**
1. Add a `pyproject.toml` to `maveo/` to make it a proper Python package
2. Publish to PyPI (or use a git requirement during development)
3. Update `custom_components/maveo/manifest.json`:
   - Before PyPI: `"requirements": ["python-maveo@git+https://github.com/yoda-jm/ha-maveo.git@main#subdirectory=maveo"]`
   - After PyPI: `"requirements": ["python-maveo==x.y.z"]`
4. Delete the copied/duplicated files from `custom_components/maveo/`
5. Update imports in the integration to use the installed package

**Why:**
- Eliminates the sync problem between `maveo/` and `custom_components/maveo/`
- Required for HACS publication and HA code review compliance
- Makes the library independently reusable
