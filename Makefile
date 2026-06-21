.PHONY: setup setup-all lane-infra lane-agent lane-frontend test demo dashboard up down logs lock clean

setup:          ## sync venv + dev deps (everyone runs this first)
	uv sync
	@echo "ready -> uv run demo.py  (or: source .venv/bin/activate)"

up:             ## start local infra (redis + phoenix) via docker compose
	docker compose up -d
	@echo "redis -> localhost:6379   phoenix UI -> http://localhost:6006"

down:           ## stop local infra
	docker compose down

logs:           ## tail infra logs
	docker compose logs -f

setup-all:      ## sync every lane's deps
	uv sync --all-extras

lane-infra:     ## P2 deps (redis, sentry)
	uv sync --extra infra

lane-agent:     ## P3 deps (anthropic, arize-phoenix)
	uv sync --extra agent

lane-frontend:  ## P4 deps (streamlit)
	uv sync --extra frontend

test:           ## run invariant tests
	uv run pytest

demo:           ## run the side-by-side demo
	uv run demo.py

dashboard:      ## launch the visual dashboard (http://localhost:8501)
	uv run --extra frontend streamlit run dashboard/app.py

phoenix:        ## launch local Arize Phoenix UI (http://localhost:6006)
	uv run --extra agent phoenix serve

phoenix-seed:   ## send demo traces to a running local Phoenix (project 'immune')
	uv run --extra agent python scripts/phoenix_seed.py

phoenix-clean:  ## wipe the local Phoenix 'immune' project (then: make phoenix-seed)
	uv run --extra agent python scripts/phoenix_clean.py

lock:           ## refresh the lockfile after changing deps
	uv lock

clean:
	rm -rf .venv **/__pycache__ .pytest_cache
