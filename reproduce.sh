#!/usr/bin/env bash
# One-command reproduction of the PRISM simulator results and figures.
set -e
python -m pip install -r requirements.txt
echo "Running full pipeline (paper cohort sizes, ~2-6 min CPU) ..."
python run_all.py
echo
echo "Done. See results/results.json, results/tables/*.csv, results/figures/*.png"
