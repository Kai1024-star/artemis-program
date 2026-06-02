#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy==1.26.4"
tmp_dir="$(mktemp -d)"
archive="$tmp_dir/aeneas-1.7.3.0.tar.gz"
python - <<'PY'
from urllib.request import urlretrieve

urlretrieve(
    "https://files.pythonhosted.org/packages/source/a/aeneas/aeneas-1.7.3.0.tar.gz",
    "aeneas-1.7.3.0.tar.gz",
)
PY
mv aeneas-1.7.3.0.tar.gz "$archive"
tar -xzf "$archive" -C "$tmp_dir"
source_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d -name 'aeneas-*' | head -n 1)"
cd "$source_dir"
rm -f pyproject.toml
python setup.py install
cd /opt/render/project/src
python -m pip install -r requirements.txt
