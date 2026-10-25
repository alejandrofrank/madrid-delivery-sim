.PHONY: setup up demo test check down graph
PYTHON ?= python3
export LOCAL_UID ?= $(shell id -u)
export LOCAL_GID ?= $(shell id -g)
setup:
	mkdir -p artifacts
	docker compose up -d --build --wait
	docker compose exec -T app delivery init
up: setup
demo: setup
	docker compose exec -T app delivery demo --wall-seconds 600
test: setup
	docker compose exec -T app pytest -q
check: setup
	docker compose exec -T app ruff check src tests
	docker compose exec -T app mypy --cache-dir=/tmp/mypy-cache src
graph:
	python -m delivery.world --download
down:
	docker compose down

# City development remains local. These explicitly opt into/out of the paid judge.
.PHONY: gcp-start gcp-stop gcp-status
gcp-start:
	$(PYTHON) scripts/gcp_demo.py start
gcp-stop:
	$(PYTHON) scripts/gcp_demo.py stop
gcp-status:
	$(PYTHON) scripts/gcp_demo.py status
