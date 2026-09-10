#!/usr/bin/env bash
# One-command reproduction of every table and figure in the paper.
# Usage:  bash reproduce.sh          (full run, ~5 min on a laptop CPU)
#         bash reproduce.sh --fast   (quick smoke test, ~30 s)
set -euo pipefail
python -m pip install --quiet --upgrade -r requirements.txt
python run_all.py "$@"
echo
echo "Done. Outputs written to:"
echo "  results/results.json      (all metrics)"
echo "  results/tables/*.csv      (Tables 3, 5, 7, privacy-utility)"
echo "  results/figures/*.png     (sensitivity, federated, calibration)"
