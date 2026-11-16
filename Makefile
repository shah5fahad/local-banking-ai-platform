.PHONY: lint test format typecheck install-dev

lint:
	cd common && python -m ruff check banking_common tests
	cd banking_service && python -m ruff check app tests
	cd ai_service && python -m ruff check app tests

format:
	cd common && python -m ruff format banking_common tests
	cd banking_service && python -m ruff format app tests
	cd ai_service && python -m ruff format app tests

typecheck:
	cd common && python -m mypy banking_common
	cd banking_service && python -m mypy app
	cd ai_service && python -m mypy app

test:
	cd common && python -m pytest -v
	cd banking_service && python -m pytest -v
	cd ai_service && python -m pytest -v

install-dev:
	pip install -e common[dev]
	pip install -e banking_service[dev]
	pip install -e ai_service[dev]
