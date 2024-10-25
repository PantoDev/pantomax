FROM python:3.12.0-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y git gcc

RUN python -m venv venv

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

RUN if [ ! -f .envrc ]; then echo ".envrc file not found!"; exit 1; fi

ARG APP_VERSION
RUN test -n "$APP_VERSION" || (echo "APP_VERSION is not set" && exit 1)
RUN echo "export APP_VERSION=$APP_VERSION" >> .envrc

CMD [ "scripts/run.sh" ]

EXPOSE 5001
