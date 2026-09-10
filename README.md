# GBFL in-season app

Mock UI first, then live engines.

```text
python -m pip install -r requirements.txt
python -m pytest -q
python -c "from app.assemble import dump_fixture; print(dump_fixture())"

cd web
npm install
npm run dev
```

API (optional; UI falls back to `web/public/fixtures/week1.json`):

```text
python -m uvicorn app.main:app --reload --port 8000
```

Refresh CBS: `python cbs_pull.py --cookies cbs_cookies.txt` then reload. HAR files are credentials — do not commit them.

Import rankings: drop updated `dynasty.csv` / `redraft.csv` and `python merge.py`, or use the UI file inputs when the API is up.
