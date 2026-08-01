#!/bin/sh
set -eu

aerich upgrade
exec uvicorn app.main:app --host 0.0.0.0 --port 8100 --no-access-log
