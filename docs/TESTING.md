# Testing EdgeBot

This project uses `pytest` to discover and run both unittest-style and pytest-style tests.

## Local

```bash
pip install -r edge_node/requirements.txt  # optional if you run the app
pip install -r requirements-dev.txt

pytest -q --maxfail=1 --disable-warnings \
  --cov=edge_node/app --cov-report=term-missing --cov-report=xml:coverage.xml \
  --junitxml=reports/junit.xml \
  --html=reports/report.html --self-contained-html 2>&1 | tee test-output.txt

python scripts/simple_test_report.py reports/junit.xml > reports/simple_report.md
```

Artifacts produced:
- `reports/simple_report.md` — non-technical summary (scenarios and pass/fail).
- `reports/report.html` — full HTML report (technical).
- `reports/junit.xml` — machine-readable test results (CI).
- `test-output.txt` — full console logs for engineers.

## CI

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on pushes/PRs and:
- Installs dev dependencies
- Lints with `black --check`
- Runs tests on Python 3.10 and 3.11 with coverage
- Publishes all artifacts listed above
- Builds the Docker image (without pushing by default)