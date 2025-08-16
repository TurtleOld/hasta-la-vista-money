# This docker file is used for production
# Creating image based on official python3 image
FROM python:3.13.7

RUN pip install uv==0.7.13

RUN uv venv .venv && uv pip install -e '.[dev]'

ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY . .

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
