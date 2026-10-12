UV ?= $(if $(wildcard .tools/bin/uv),.tools/bin/uv,uv)
export UV_CACHE_DIR := $(CURDIR)/.uv-cache
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.uv-python
export PRE_COMMIT_HOME := $(CURDIR)/.pre-commit-cache

.PHONY: setup lint test check smoke demo bench record render golden verify-clone

setup:
	$(UV) sync --frozen
	$(UV) run --offline --no-sync pre-commit install

lint:
	$(UV) run --offline --no-sync ruff check .
	$(UV) run --offline --no-sync ruff format --check .
	$(UV) run --offline --no-sync mypy

test:
	$(UV) run --offline --no-sync pytest

check: lint test

smoke:
	$(UV) run --offline --no-sync instabay smoke

demo:
	$(UV) run --offline --no-sync instabay demo

bench:
	$(UV) run --offline --no-sync instabay bench --readme README.md

record:
	$(UV) run --offline --no-sync instabay record $(ARGS)

render:
	$(UV) run --offline --no-sync instabay render --recipe "$(RECIPE)" --backend "$(or $(BACKEND),stub)"

golden:
	$(UV) run --offline --no-sync instabay golden --recipe "$(RECIPE)" --backend "$(or $(BACKEND),stub)"

# Run from a fresh committed checkout; build prepares dependencies, execution is offline.
verify-clone:
	docker build -f Dockerfile.validation -t instabay:validation .
	docker run --rm --network none instabay:validation
