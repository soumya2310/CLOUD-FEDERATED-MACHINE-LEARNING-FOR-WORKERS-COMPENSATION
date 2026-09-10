# Reproducible environment for the PRISM synthetic simulator.
# Build:  docker build -t prism-sim .
# Run:    docker run --rm -v "$PWD/results:/prism/results" prism-sim
# This regenerates results/results.json, results/tables/*.csv and results/figures/*.png.
FROM python:3.12-slim
WORKDIR /prism
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "run_all.py"]
