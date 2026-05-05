.PHONY: setup run test clean keepalive

# ── Setup ────────────────────────────────────────────────────────────────────
setup:
	python -m venv .venv
	.venv\Scripts\pip install -r requirements.txt
	@echo "Setup complete. Activate venv: .venv\Scripts\activate"

# ── Run Pipeline ─────────────────────────────────────────────────────────────
run:
	.venv\Scripts\python -m src.pipeline

# ── Tests ────────────────────────────────────────────────────────────────────
test:
	.venv\Scripts\python -m pytest src\tests\ -v

# ── Supabase Keepalive ───────────────────────────────────────────────────────
keepalive:
	.venv\Scripts\python -c "from src.load.database import get_engine; eng = get_engine(); conn = eng.connect(); print(conn.execute(__import__('sqlalchemy').text('SELECT 1')).scalar()); conn.close()"

# ── Clean ────────────────────────────────────────────────────────────────────
clean:
	del /q pipeline_status.json 2>nul
	rmdir /s /q logs 2>nul
	rmdir /s /q __pycache__ 2>nul
	@echo "Cleaned."
