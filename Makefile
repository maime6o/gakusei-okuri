.PHONY: install run test lint

VENV = .venv
PYTHON = $(VENV)/bin/python
UVICORN = $(VENV)/bin/uvicorn
PYTEST = $(VENV)/bin/pytest

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

run:
	PYTHONPATH=. $(UVICORN) server.main:app --reload --host 0.0.0.0 --port 8000

test:
	PYTHONPATH=. $(PYTEST) tests/ -v

lint:
	$(PYTHON) -m py_compile engine/models.py engine/catalog.py engine/deck_builder.py \
	  engine/hooks.py engine/actions.py engine/game.py server/main.py server/rooms.py
	@echo "Syntax OK"
