from __future__ import annotations

import argparse
import importlib.util
import inspect
import os
import sys
import tempfile
import traceback
import types
import unittest
from pathlib import Path
from typing import Any


class MiniMonkeyPatch:
    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, bool, Any]] = []

    def setattr(self, target: Any, name: str, value: Any, raising: bool = True) -> None:
        existed = hasattr(target, name)
        if raising and not existed:
            raise AttributeError(f"{target!r} has no attribute {name!r}")
        old_value = getattr(target, name, None)
        self._undo.append((target, name, existed, old_value))
        setattr(target, name, value)

    def undo(self) -> None:
        while self._undo:
            target, name, existed, old_value = self._undo.pop()
            if existed:
                setattr(target, name, old_value)
            elif hasattr(target, name):
                delattr(target, name)


def load_module(path: Path, index: int) -> types.ModuleType:
    module_name = f"_dependency_free_test_{index}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_function_test(func: Any, label: str) -> tuple[bool, str | None]:
    temporary_directories: list[tempfile.TemporaryDirectory[str]] = []
    monkeypatch = MiniMonkeyPatch()
    kwargs: dict[str, Any] = {}
    try:
        for parameter in inspect.signature(func).parameters.values():
            if parameter.name == "tmp_path":
                temp_dir = tempfile.TemporaryDirectory(prefix="vc_test_")
                temporary_directories.append(temp_dir)
                kwargs[parameter.name] = Path(temp_dir.name)
            elif parameter.name == "monkeypatch":
                kwargs[parameter.name] = monkeypatch
            elif parameter.default is inspect.Parameter.empty:
                raise RuntimeError(
                    f"Unsupported required fixture {parameter.name!r} in {label}"
                )
        func(**kwargs)
        return True, None
    except BaseException:
        return False, traceback.format_exc()
    finally:
        monkeypatch.undo()
        for temp_dir in reversed(temporary_directories):
            temp_dir.cleanup()


def run_module(module: types.ModuleType, path: Path) -> tuple[int, int]:
    passed = 0
    failed = 0

    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    case_count = suite.countTestCases()
    if case_count:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        passed += result.testsRun - len(result.failures) - len(result.errors)
        failed += len(result.failures) + len(result.errors)

    functions = [
        value
        for name, value in module.__dict__.items()
        if name.startswith("test_")
        and inspect.isfunction(value)
        and value.__module__ == module.__name__
    ]
    functions.sort(key=lambda function: function.__code__.co_firstlineno)

    for function in functions:
        label = f"{path.as_posix()}::{function.__name__}"
        ok, error = run_function_test(function, label)
        if ok:
            passed += 1
            print(f"PASS {label}")
        else:
            failed += 1
            print(f"FAIL {label}")
            assert error is not None
            print(error.rstrip())

    return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("test_files", nargs="+")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--expect-count", type=int)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"FAIL repo root not found: {repo_root}")
        return 2

    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root))

    total_passed = 0
    total_failed = 0

    for index, raw_path in enumerate(args.test_files):
        path = (repo_root / raw_path).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError:
            print(f"FAIL test path escapes repository: {raw_path}")
            return 2
        if not path.is_file():
            print(f"FAIL test file not found: {path}")
            return 2
        try:
            module = load_module(path, index)
        except BaseException:
            total_failed += 1
            print(f"FAIL import {path.as_posix()}")
            print(traceback.format_exc().rstrip())
            continue
        passed, failed = run_module(module, path.relative_to(repo_root))
        total_passed += passed
        total_failed += failed

    total = total_passed + total_failed
    print(f"RESULT passed={total_passed} failed={total_failed} total={total}")
    if args.expect_count is not None and total != args.expect_count:
        print(f"FAIL expected test count {args.expect_count}, observed {total}")
        return 3
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
