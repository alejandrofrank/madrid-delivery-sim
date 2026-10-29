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
.PHONY: health eval-agents test-adk demo-adk
demo-adk:
	$(DOCKER) compose run --rm --no-deps --build app python scripts/demo_adk_restaurants.py
test-adk:
	$(DOCKER) compose run --rm --no-deps --build app pytest -q tests/test_adk_restaurant.py -p delivery.health_report --health-report=artifacts/health/adk
health:
	$(DOCKER) compose run --rm --no-deps --build -e DELIVERY_SOURCE_REVISION=$$(git rev-parse HEAD) app python scripts/health_check.py
eval-agents:
	$(DOCKER) compose run --rm --no-deps --build app python scripts/eval_agents.py

# City development remains local. These explicitly opt into/out of the paid judge.
.PHONY: gcp-start gcp-stop gcp-status gcp-vertex-start demo-adk-vertex demo-adk-routing verify-adk-contracts
gcp-vertex-start:
	$(PYTHON) scripts/gcp_demo.py vertex-start
demo-adk-routing:
	$(PYTHON) scripts/run_adk_vertex.py --paid --routing-comparison

verify-adk-contracts:
	$(PYTHON) scripts/run_adk_vertex.py --paid --contract-verification

demo-adk-vertex:
	$(PYTHON) scripts/run_adk_vertex.py --paid
gcp-start:
	$(PYTHON) scripts/gcp_demo.py start
gcp-stop:
	$(PYTHON) scripts/gcp_demo.py stop
gcp-status:
	$(PYTHON) scripts/gcp_demo.py status

.PHONY: eval-adk
eval-adk:
	$(DOCKER) compose run --rm --no-deps --build app python3 scripts/eval_agents.py --suite adk --repeat 3
