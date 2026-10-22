.PHONY: setup up demo test check down graph
setup:
	docker compose up -d --build --wait
	docker compose exec -T app delivery init
up: setup
demo: setup
	docker compose exec -T app delivery demo --wall-seconds 600
test: setup
	docker compose exec -T app pytest -q
check: setup
	docker compose exec -T app ruff check src tests
	docker compose exec -T app mypy src
graph:
	python -m delivery.world --download
down:
	docker compose down
