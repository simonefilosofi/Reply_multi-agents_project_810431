PYTHON ?= python

.PHONY: install lint format type test cov smoke smoke-mocked app ci clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check . --fix

type:
	$(PYTHON) -m mypy .

test:
	$(PYTHON) -m pytest -q -m "not docker and not slow"

cov:
	$(PYTHON) -m pytest -q -m "not docker and not slow" --cov=state_demo --cov=agents_demo --cov=tools --cov=tools_code_validator --cov-report=term-missing

smoke:
	$(PYTHON) -m scripts.smoke_test

smoke-mocked:
	$(PYTHON) -m scripts.smoke_test --mocked

app:
	$(PYTHON) -m streamlit run app_demo.py

ci: lint type test cov

clean:
	$(PYTHON) -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in (pathlib.Path('.pytest_cache'), pathlib.Path('.ruff_cache'), pathlib.Path('.mypy_cache'))]"
