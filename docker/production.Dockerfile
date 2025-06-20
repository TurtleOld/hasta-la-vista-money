# This docker file is used for production
# Creating image based on official python3 image
FROM python:3.13.5

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd -m superuser
USER superuser
WORKDIR /home/superuser
COPY ../ .
ENV PATH="/home/superuser/.local/bin:$PATH"

RUN pip install uv

RUN uv pip install -e '.[dev]'

EXPOSE 8000

CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
