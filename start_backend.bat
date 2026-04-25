@echo off
start "tail_sock Backend" cmd /k "cd /d E:\workspace\tail_sock\backend && echo Starting backend... && .venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
