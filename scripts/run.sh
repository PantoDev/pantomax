#!/usr/bin/env bash

set -e

if ! [ -x "$(which git)" ]; then
   echo "Git is not installed. Installing it."
   # hacky way to install git
   apt-get install -y git
fi

if [ -e ".envrc" ]; then
   echo "sourcing .envrc file."
   source .envrc
else
   echo ".envrc file not found. Skipping sourcing."
fi

if [ -e "venv/bin/activate" ]; then
   echo "Activating virtual environment. from venv/bin/activate"
   source venv/bin/activate
else
   echo "Virtual environment not found. Skipping activation."
fi

if [ -z "$GUNICORN_WORKER_COUNT" ]; then
   echo "GUNICORN_WORKER_COUNT not set. Setting it to 1."
   GUNICORN_WORKER_COUNT=4
fi

echo "Starting the server...!!"
exec gunicorn -w $GUNICORN_WORKER_COUNT -t 300 -b 0.0.0.0:5001 -k uvicorn.workers.UvicornWorker panto.server:app
