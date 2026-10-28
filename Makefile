.PHONY: setup up demo test check down graph
PYTHON ?= python3
DOCKER ?= docker
export LOCAL_UID ?= $(shell id -u)
export LOCAL_GID ?= $(shell id -g)
setup:
	mkdir -p artifacts
	$(DOCKER) compose up -d --build --wait
	$(DOCKER) compose exec -T app delivery init
up: setup
demo: setup
	$(DOCKER) compose exec -T app delivery demo --wall-seconds 600
test: setup
	$(DOCKER) compose exec -T -e DELIVERY_SOURCE_REVISION=$$(git rev-parse HEAD) app pytest -q -p delivery.health_report --health-report=artifacts/health
check: setup
	$(DOCKER) compose exec -T app ruff check src tests
	$(DOCKER) compose exec -T app mypy --cache-dir=/tmp/mypy-cache src
graph:
	python -m delivery.world --download
down:
	$(DOCKER) compose down

# Read-only dashboard at /health; checks use delivery_test and zero model calls.
.PHONY: health
health:
	$(DOCKER) compose run --rm --no-deps --build -e DELIVERY_SOURCE_REVISION=$$(git rev-parse HEAD) app python scripts/health_check.py

# City development remains local. These explicitly opt into/out of the paid judge.
.PHONY: gcp-start gcp-stop gcp-status
gcp-start:
	$(PYTHON) scripts/gcp_demo.py start
gcp-stop:
	$(PYTHON) scripts/gcp_demo.py stop
gcp-status:
	$(PYTHON) scripts/gcp_demo.py status
