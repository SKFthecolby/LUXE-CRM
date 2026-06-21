# Luxe CRM

Production-oriented local operations dashboard for Luxe Home Services.

## Install

```bash
python -m pip install -r requirements.txt
```

## Development

```bash
streamlit run app.py
```

Client portal:

```bash
streamlit run client_portal.py
```

## Build

This Streamlit app does not have a packaged build step. Use Python compilation as a syntax check:

```bash
python -m compileall app.py client_portal.py luxe_ops
```

## Lint / Test

No linter is configured.

Smoke test, if `pytest` is installed:

```bash
python -m pytest luxe_ops/core/tests
```

## Database

The app uses a local SQLite database at `luxe_ops.db`. It is created automatically on first run from the schema in `luxe_ops/core/db.py`.

No database setup command is required.

## Clean Database

The app creates schema and production settings only. It does not create example
leads, clients, jobs, invoices, expenses, messages, or portal access.

## Environment Variables

No required environment variables are currently used.
