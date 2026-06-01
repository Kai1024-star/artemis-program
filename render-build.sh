#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy==1.26.4"
PIP_NO_BUILD_ISOLATION=1 python -m pip install --no-build-isolation --no-use-pep517 "aeneas==1.7.3.0"
python -m pip install -r requirements.txt
