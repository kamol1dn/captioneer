r"""Run the unit tests without pytest (not installed in the shared venv):
    ..\venv\Scripts\python.exe -m skleyka.tests.run
"""
import importlib
import pkgutil
import sys
import traceback

import skleyka.tests as pkg

failed = passed = 0
for mod in pkgutil.iter_modules(pkg.__path__):
    if not mod.name.startswith("test_"):
        continue
    module = importlib.import_module(f"skleyka.tests.{mod.name}")
    for name in dir(module):
        if name.startswith("test_") and callable(getattr(module, name)):
            try:
                getattr(module, name)()
                passed += 1
            except Exception:
                failed += 1
                print(f"FAIL {mod.name}.{name}")
                traceback.print_exc()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
