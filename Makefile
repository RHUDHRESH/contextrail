# ContextRail operator targets (CLAUDE.md §19). Runs on the EC2 host and any machine with GNU make.
# Engine commands go through uv so the locked environment (engine/uv.lock) is used.
UV_ENGINE := uv run --project engine --frozen

.PHONY: up down logs migrate seed reset fmt lint test ps

up:            ## start postgres, engine, caddy (voice: docker compose --profile voice up -d)
	docker compose up -d --build

down:          ## stop the stack (data volumes are kept)
	docker compose down

logs:          ## follow engine + caddy logs
	docker compose logs -f --tail=200 engine caddy

ps:
	docker compose ps

migrate:       ## apply SQL migrations to DATABASE_URL
	$(UV_ENGINE) python -m contextrail.migrate

seed:          ## migrate, load the identity map for every door, reset FIXTURE connector state
	$(UV_ENGINE) python -m contextrail.seed

reset:         ## restore FIXTURE connector state between demo runs (the audit DB is never rewritten)
	$(UV_ENGINE) python -m contextrail.reset

fmt:           ## auto-fix lint findings
	$(UV_ENGINE) ruff check --fix contextrail tests

lint:
	$(UV_ENGINE) ruff check contextrail tests

test:
	$(UV_ENGINE) pytest -q
