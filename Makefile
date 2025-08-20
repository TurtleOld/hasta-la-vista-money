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

.PHONY: docker-build-prod
docker-build-prod:
		docker build -f docker/production.Dockerfile -t hasta-la-vista-money:prod .

.PHONY: docker-test-prod
docker-test-prod:
		docker run --rm -p 8001:8001 hasta-la-vista-money:prod

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
		@uv run python ./manage.py test -v 2

.PHONY: coverage
coverage:
		@uv run coverage run manage.py test
		@uv run coverage xml
		@uv run coverage report

.PHONY: taskiq-worker
taskiq-worker:
		@uv run taskiq worker hasta_la_vista_money.taskiq:broker

.PHONY: taskiq-scheduler
taskiq-scheduler:
		@uv run taskiq scheduler hasta_la_vista_money.taskiq:scheduler

.PHONY: taskiq-dashboard
taskiq-dashboard:
		@uv run taskiq dashboard hasta_la_vista_money.taskiq:broker

.PHONY: rabbitmq
rabbitmq:
		@docker run -d --name hlvm_rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management-alpine

.PHONY: rabbitmq-stop
rabbitmq-stop:
		@docker stop hlvm_rabbitmq && docker rm hlvm_rabbitmq

.PHONY: rabbitmq-management
rabbitmq-management:
		@echo "RabbitMQ Management UI: http://localhost:15672"
		@echo "Username: guest"
		@echo "Password: guest"
