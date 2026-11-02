"""THE LICENSE BUILDS PAST 2027: pyproject.toml declares it the way setuptools will keep accepting.

setuptools deprecated the `project.license` TOML table (`license = {text = "MIT"}`) and the
`License ::` trove classifiers in favour of PEP 639: an SPDX expression in `project.license` and the
files it covers in `project.license-files`. Its warning gives the table's end as 2027-02-18; after
that the editable install in deploy/install.sh:29 (under `set -euo pipefail`, :10) fails. Four
facts keep it building:

  1. `project.license` is the SPDX string "MIT", not a table;
  2. `project.license-files` names LICENSE, and that file is in the repository;
  3. no classifier starts with "License ::": setuptools raises InvalidConfigError when an SPDX
     expression sits beside one;
  4. `build-system.requires` asks for setuptools>=77, the release its warning names as the first
     to read both options, so a build that does not fetch the newest setuptools (no build
     isolation, offline) still gets one that does.

Built metadata then carries `License-Expression: MIT` (Metadata-Version 2.4), not `License: MIT`.

Stdlib only: tomllib parses the file; nothing is built or installed. Python 3.10, which the package
still claims, has no tomllib, so there this file skips and says why.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    pytest.skip(
        "tomllib is in the standard library from Python 3.11; Python 3.10 (which pyproject.toml "
        "still claims) has no stdlib TOML parser and this test uses no third-party one, so the "
        "packaging facts are pinned by the 3.11+ runs",
        allow_module_level=True,
    )

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _release(version: str) -> tuple[int, ...]:
    """The numeric release segment of a version string: '77.0.3' -> (77, 0, 3)."""
    m = re.match(r"\d+(?:\.\d+)*", version)
    assert m, f"no release number in {version!r}"
    return tuple(int(p) for p in m.group(0).split("."))


def test_license_is_the_spdx_string_mit():
    lic = _pyproject()["project"].get("license")
    assert lic == "MIT", f"project.license must be the SPDX string 'MIT', not {lic!r}"


def test_license_files_name_license_and_it_exists():
    files = _pyproject()["project"].get("license-files")
    assert files == ["LICENSE"], f"project.license-files must be ['LICENSE'], not {files!r}"
    assert (ROOT / "LICENSE").is_file(), "project.license-files names LICENSE, which is missing"


def test_no_license_classifier_beside_the_expression():
    classifiers = _pyproject()["project"].get("classifiers", [])
    hits = [c for c in classifiers if c.startswith("License ::")]
    assert hits == [], f"setuptools refuses a 'License ::' classifier beside an SPDX license: {hits}"


def test_build_requires_setuptools_77_or_later():
    requires = _pyproject()["build-system"]["requires"]
    named = [r for r in requires
             if re.sub(r"[-_.]+", "-", re.match(r"\s*([A-Za-z0-9._-]+)", r).group(1)).lower()
             == "setuptools"]
    assert len(named) == 1, f"build-system.requires must name setuptools once: {requires}"
    spec = named[0].split(";", 1)[0]
    lower = [_release(v) for v in re.findall(r">=\s*([0-9][0-9A-Za-z.]*)", spec)]
    assert lower and max(lower) >= (77,), (
        f"build-system.requires must ask for setuptools>=77 (a string license needs it), "
        f"not {named[0]!r}")
