#!/usr/bin/env python3
"""Launch the housing simulator web app.

Usage:
    python run.py [--port 8000] [--host 127.0.0.1] [--reload]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def main():
    parser = argparse.ArgumentParser(description="Run the housing simulator web app.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port to bind (default: 8000)")
    parser.add_argument("--reload", action="store_true",
                        help="Reload on code changes (dev mode)")
    args = parser.parse_args()

    import uvicorn

    print(f"\nHousing Simulator")
    print(f"  Frontend:  http://{args.host}:{args.port}/")
    print(f"  API docs:  http://{args.host}:{args.port}/docs")
    print(f"  Press Ctrl+C to stop.\n")

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=os.path.join(ROOT, "backend"),
    )


if __name__ == "__main__":
    main()
