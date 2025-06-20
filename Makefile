.PHONY: lint
lint:
		@cd ./hasta_la_vista_money && \
			echo "Running flake8 check..." && \
			flake8 . --select=WPS

.PHONY: format
format:
	@cd ./hasta_la_vista_money && \
			echo "Running ruff..." && \
			uv run ruff format
			uv run ruff check --fix


.PHONY: transprepare
transprepare:
		@uv run django-admin makemessages

.PHONY: transcompile
transcompile:
		@uv run django-admin compilemessages

.PHONY: shell
shell:
		@uv shell

.PHONY: .env
.env:
		@test ! -f .env && cp .env.example .env

.PHONY: install
install: .env
		@uv pip install -e '.[dev]'

.PHONY: migrate
migrate:
		uv run python ./manage.py makemigrations && \
		echo "" && \
		echo "Migrating..." && \
		uv run python ./manage.py migrate

.PHONY: docker-build
docker-build: .env
		docker compose build

.PHONY: docker-up
docker-up:
		@[ -f ./.env ] && \
			docker compose --env-file ./.env up -d || \
			docker compose up -d

.PHONY: gettext
gettext:
		sudo apt install gettext -y

.PHONY: staticfiles
staticfiles:
		@uv run python manage.py collectstatic

.PHONY: start
start:
		@uv run python manage.py runserver

.PHONY: secretkey
secretkey:
		@uv run python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

.PHONY: test
test:
		DB_USER="postgres" DB_PASSWORD="postgres" uv run python ./manage.py test -v 2

.PHONY: coverage
coverage:
		@uv run coverage run manage.py test
		@uv run coverage xml
		@uv run coverage report

.PHONY: celery
celery:
		@cd ./app && \
			uv run celery -A calndr worker --loglevel=info
