# KNIME Pipeline Documentation

MkDocs Material site documenting the LUX Actuaries KNIME data pipeline.

## Quick start

```bash
source vir_env/bin/activate          # Windows: vir_env\Scripts\activate
pip install -r requirements.txt
python -m mkdocs serve                         # preview at http://127.0.0.1:8000
```

## Add a new workflow
See `docs/how-to/add-a-new-workflow.md` (copy `docs/workflows/_template`).

## Deploy
Push to `main` — GitHub Actions builds and publishes to GitHub Pages.
