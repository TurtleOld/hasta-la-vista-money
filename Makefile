.PHONY: lint format pre-commit pre-commit-install pre-commit-update \
        transprepare transcompile shell install install-prod migrate \
        docker-build docker-build-prod docker-test-prod docker-up \
        gettext staticfiles start secretkey test coverage \
        rabbitmq rabbitmq-stop rabbitmq-management export-api-schema \
        help check docs

lint:
	@cd hasta_la_vista_money && echo "Running flake8 check..." && uv run flake8 . --select=WPS

format:
	@cd hasta_la_vista_money && echo "Running ruff..." && uv run ruff format && uv run ruff check --fix
	@cd config && echo "Running ruff on config..." && uv run ruff format && uv run ruff check --fix

pre-commit:
	@echo "Running pre-commit on all files..." && uv run pre-commit run --all-files

pre-commit-install:
	@echo "Installing pre-commit hooks..." && uv run pre-commit install && echo "Pre-commit hooks installed successfully!"

pre-commit-update:
	@echo "Updating pre-commit hooks..." && uv run pre-commit autoupdate && echo "Pre-commit hooks updated successfully!"

transprepare:
	@uv run django-admin makemessages

transcompile:
	@uv run django-admin compilemessages

shell:
	@uv shell

.env:
	@test ! -f .env && cp .env.example .env || true

install: .env secretkey
	@uv sync --dev

install-prod: .env secretkey
	@uv sync

migrate:
	@uv run python manage.py makemigrations && echo "" && echo "Migrating..." && uv run python manage.py migrate

docker-build: .env
	@docker compose build

docker-build-prod:
	@docker build -f docker/production.Dockerfile -t hasta-la-vista-money:prod .

docker-test-prod:
	@docker run --rm -p 8001:8001 hasta-la-vista-money:prod

docker-up:
	@([ -f ./.env ] && docker compose --env-file ./.env up -d) || docker compose up -d

gettext:
	@echo "Install gettext manually on Windows; apt only for Linux." && uv run python -c "print('For Windows: choco install gettext (or use MSYS2)')"

staticfiles:
	@uv run python manage.py collectstatic

start:
	@uv run python manage.py runserver 127.0.0.1:8000

secretkey:
	@uv run python -c "import os,re; p='.env';\
content=open(p,'r',encoding='utf-8').read() if os.path.exists(p) else '';\
import sys; \
from django.core.management.utils import get_random_secret_key as g; \
print('SECRET_KEY already present, skipping') if re.search(r'^SECRET_KEY=',content, re.M) else open(p,'a',encoding='utf-8').write(('' if content.endswith('\n') or not content else '\n')+'SECRET_KEY='+g()+'\n') or print('SECRET_KEY added')"

test:
	@uv run python manage.py test -v 2

coverage:
	@uv run python -m coverage run manage.py test -v 2 && uv run python -m coverage xml && uv run python -m coverage report

rabbitmq:
	@docker run -d --name hlvm_rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management-alpine

rabbitmq-stop:
	@docker stop hlvm_rabbitmq && docker rm hlvm_rabbitmq

rabbitmq-management:
	@echo "RabbitMQ Management UI: http://localhost:15672" && echo "Username: guest" && echo "Password: guest"

export-api-schema:
	@uv run python -c "import os; os.makedirs('docs/docs/api', exist_ok=True)"
	@echo "Exporting OpenAPI schema..." && uv run python manage.py spectacular --file docs/docs/api/schema.json --format openapi-json && echo "Schema exported to docs/docs/api/schema.json"

docs:
	@uv run mkdocs build -q

check:
	@$(MAKE) format
	@$(MAKE) lint
	@uv run mypy . && uv run pyright

help:
	@uv run python -c "print('Targets:\\n  install / install-prod\\n  pre-commit-install / pre-commit / pre-commit-update\\n  format / lint / check\\n  migrate / staticfiles / start\\n  test / coverage\\n  export-api-schema / docs\\n  docker-build / docker-build-prod / docker-test-prod / docker-up\\n  rabbitmq / rabbitmq-stop / rabbitmq-management\\n  secretkey (idempotent)')"
