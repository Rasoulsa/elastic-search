.PHONY: setup up down migrate import create-index rebuild-index test test-backend test-frontend lint

setup:
	@test -f .env || cp .env.example .env
	docker compose build

up:
	docker compose up --build

down:
	docker compose down

migrate:
	docker compose run --rm backend python manage.py migrate

import:
	docker compose run --rm backend python manage.py import_profiles --path /data/profiles.txt

create-index:
	docker compose run --rm backend python manage.py create_profile_index

rebuild-index:
	docker compose run --rm backend python manage.py rebuild_profile_index

test: test-backend test-frontend

test-backend:
	docker compose run --rm backend pytest tests

test-frontend:
	docker compose run --rm frontend npm test -- --run

lint:
	docker compose run --rm backend ruff check .
	docker compose run --rm frontend npm run lint
