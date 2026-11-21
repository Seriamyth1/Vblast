# The scorer builds on linux/amd64 and runs with no network, 2 cores, read-only disk.
# map.json.gz / stmts.json.gz are built from sqlglot at the pinned commit
# (eb11aec4be8cb2122afe713a4816662c3f0fb2fa) by tools/ — see README.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY selector.py map.json.gz stmts.json.gz /app/
RUN chmod -R a+rX /app
CMD ["python", "/app/selector.py"]
