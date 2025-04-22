# This docker file is used for production
# Creating image based on official python3 image
FROM python:3.13.3

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Get the django project into the docker container



RUN useradd -m superuser
USER superuser
WORKDIR /home/superuser
COPY ../ .
ENV PATH="/home/superuser/.local/bin:$PATH"
RUN curl -sSL https://install.python-poetry.org | python3 - && poetry --version
RUN pip install --upgrade pip
RUN pip install -r /home/superuser/requirements/prod.txt
RUN pip install -r /home/superuser/requirements/dev.txt



EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
