# 01 — `pyproject.toml`

Read [`00-overview.md`](00-overview.md) first. This file produces packaging metadata only.

**Files:**
- Create: [`pyproject.toml`](../../../../pyproject.toml)

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `aiv2lib` package with exactly one runtime dependency (`uiautomation`), a Python 3.10 floor, and pytest configured to collect from `tests/`.

---

- [ ] **Step 1: Create the file**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aiv2lib"
version = "0.1.0"
description = "Small Windows automation library for A.I.VOICE2 Editor"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
dependencies = ["uiautomation>=2.0,<3"]

[project.optional-dependencies]
test = ["pytest>=8,<9"]

[tool.setuptools.packages.find]
include = ["aiv2lib*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

Notes on the pins, so a later reader does not "modernize" them into breakage:

- `uiautomation` is capped below `3` because the control-lookup API used in [`03-aiv2lib-win.md`](03-aiv2lib-win.md) is a 2.x surface.
- `readme = "README.md"` requires [`05-readme.md`](05-readme.md) to have produced that file before `pip install .` will succeed. Editable installs and `pytest` runs from the repo root do not need it.
- No `pynput`, `watchdog`, or `pyperclip`. If a later task wants one, that is a design change, not a dependency bump.

- [ ] **Step 2: Verify the metadata parses**

Run: `python -c "import tomllib,pathlib;tomllib.loads(pathlib.Path('pyproject.toml').read_text())"`

Expected: no output, exit status 0.

- [ ] **Step 3: Verify pytest picks up the config**

Run: `python -m pytest --collect-only`

Expected: exit status 5 (`no tests ran`) because `tests/` does not exist yet. Any *error* about an unparsable `pyproject.toml` is a failure; "no tests collected" is the pass condition here.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add aiv2lib packaging metadata"
```
