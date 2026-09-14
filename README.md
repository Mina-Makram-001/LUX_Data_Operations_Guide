```markdown
# KNIME Pipeline & Data Operations Guide

MkDocs Material site documenting the LUX Actuaries KNIME data pipeline, equipped with an integrated Gemini AI Assistant.

## Prerequisites & Setup

1. **Activate Virtual Environment:**
   ```bash
   source vir_env/bin/activate        # Windows PowerShell: .\vir_env\Scripts\Activate.ps1

```

2. **Install Dependencies:**
```bash
pip install -r requirements.txt

```


3. **Configure Environment Variables:**
Create a `.env` file in the project root and add your Gemini API key:
```env
GEMINI_API_KEY=AIzaSy...

```



---

## Running the Project Local Services

To run the site with full Gemini AI integration, you must launch **both** the backend API and the MkDocs server in separate terminal windows:

### Terminal 1: FastAPI Backend

```bash
uvicorn server:app --port 8001 --reload

```

*Runs the Gemini API proxy at `http://127.0.0.1:8001`.*

### Terminal 2: MkDocs Local Server

```bash
python -m mkdocs serve

```