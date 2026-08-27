import pathlib
import sys

# Ensure `app` (backend/app) is importable regardless of where pytest is
# invoked from — mirrors how `uvicorn app.main:app` is run from backend/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
