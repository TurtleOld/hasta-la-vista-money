# This docker file is used for production
# Creating image based on official python3 image
FROM python:3.13.5

# Get the django project into the docker container
RUN curl -sSL https://install.python-poetry.org | python3 - && /root/.local/bin/poetry --version
RUN poetry config virtualenvs.create false && poetry install --extras psycopg2-binary --only main
RUN where poetry
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY . .
RUN pip install -r requirements/prod.txt

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
