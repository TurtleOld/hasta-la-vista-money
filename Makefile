lint:
	    @poetry run flake8 hasta_la_vista_money config --exclude=migrations

export-requirements:
		@poetry export -f requirements.txt --output requirements.txt --without-hashes

transprepare:
		@poetry run django-admin makemessages

transcompile:
		@poetry run django-admin compilemessages

shell:
		@poetry shell

.env:
		@test ! -f .env && cp .env.example .env

migrate:
		@poetry run python manage.py migrate

migrations:
		@poetry run python manage.py makemigrations

install: .env
		@poetry install

docker-install: .env
		docker compose build

docker-setup: migrate
		@echo Create a super user
		@poetry run python manage.py createsuperuser

docker-start:
		docker compose up

gettext:
		sudo apt install gettext -y

setup: migrations migrate staticfiles gettext transcompile
		@echo Create a super user
		@poetry run python manage.py createsuperuser

dokku:
		git push dokku main

github:
		git push origin main

staticfiles:
		@poetry run python manage.py collectstatic

start:
		@poetry run python manage.py runserver

startbot:
		@poetry run python manage.py startbot

secretkey:
		@poetry run python -c 'from django.utils.crypto import get_random_string; print(get_random_string(40))'

test:
		@poetry run coverage run --source='.' manage.py test

coverage:
		@poetry run coverage run manage.py test
		@poetry run coverage xml
		@poetry run coverage report

poetry-export-prod:
		@poetry export -f requirements.txt -o requirements/prod.txt --without-hashes

poetry-export-dev: poetry-export-prod
		@poetry export -f requirements.txt -o requirements/dev.txt --with dev --without-hashes
