UV ?= $(if $(wildcard .tools/bin/uv),.tools/bin/uv,uv)
export UV_CACHE_DIR := $(CURDIR)/.uv-cache
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.uv-python
export PRE_COMMIT_HOME := $(CURDIR)/.pre-commit-cache

.PHONY: setup lint test check smoke demo bench record render golden verify-clone vision-up vision-down studio

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

# HUMAN: owner studio on gpu-box (docs/TEST_RUN.md). One large model is resident at a time.
REMOTE ?= /home/mazen/instabay-native
BRAND ?= config/brand.yaml
WORKSPACE ?= data/workspace
RUNS ?= outputs/studio

vision-up:
	rsync -az --exclude=__pycache__ gpu_worker/ gpu-box:$(REMOTE)/gpu_worker/
	ssh gpu-box 'tmux has-session -t instabay-vision 2>/dev/null || (cd $(REMOTE) && tmux new -d -s instabay-vision "PYTHONPATH=data/pydeps-d3:. INSTABAY_GPU_ENABLED=1 PYTHONUNBUFFERED=1 $$HOME/miniconda3/envs/main/bin/python -m uvicorn gpu_worker.vision_server:app --host 127.0.0.1 --port 8790 >> outputs/instabay-vision.log 2>&1")'
	curl -s -m 3 127.0.0.1:18790/health || ssh -f -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18790:127.0.0.1:8790 gpu-box
	@echo "vision service: http://127.0.0.1:18790 (d3-flash, Qwen3.5-9B judge, FLUX.2-klein views)"

vision-down:
	-ssh gpu-box 'tmux kill-session -t instabay-vision'
	-pkill -f "18790:127.0.0.1:8790"

studio:
	mkdir -p "$(RUNS)"
	INSTABAY_DECISIONS_ENABLED=1 INSTABAY_GPU_ENABLED=1 INSTABAY_LLM_ENABLED=1 $(UV) run --offline --no-sync instabay dashboard \
	  --brand "$(BRAND)" --workspace "$(WORKSPACE)" --runs "$(RUNS)" --engine d3 --judge vlm --views gpu \
	  --confirm-external --confirm-gpu --generate
