#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy==1.26.4"
tmp_dir="$(mktemp -d)"
python - <<'PY'
from urllib.request import urlretrieve

urlretrieve(
    "https://files.pythonhosted.org/packages/source/a/aeneas/aeneas-1.7.3.0.tar.gz",
    "/tmp/aeneas-1.7.3.0.tar.gz",
)
PY
cp /tmp/aeneas-1.7.3.0.tar.gz "$tmp_dir/"
tar -xzf "$tmp_dir"/aeneas-*.tar.gz -C "$tmp_dir"
cd "$tmp_dir"/aeneas-*
rm -f pyproject.toml
python setup.py install
cd /opt/render/project/src
python -m pip install -r requirements.txt
