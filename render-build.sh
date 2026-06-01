#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip setuptools wheel
python -m pip install numpy
python -m pip install --no-build-isolation aeneas
python -m pip install -r requirements.txt
