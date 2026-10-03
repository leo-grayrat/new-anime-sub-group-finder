import argparse
import asyncio
import json
import logging
from pathlib import Path

from .config import load_config


def main():
    parser = argparse.ArgumentParser(description="新番字幕组发现：网页、采集及 MCP")
    parser.add_argument("command", nargs="?", choices=["serve", "scan", "mcp"], default="serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--server", default="http://127.0.0.1:18765")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "mcp":
        from .mcp_server import run_stdio

        run_stdio(args.server)
    elif args.command == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(config_path=args.config), host=args.host, port=args.port)
    else:
        from .monitor import Monitor
        from .service import QueryService
        from .store import Store

        async def scan():
            config = load_config(args.config)
            store = Store(Path(config.data_dir) / "finder.sqlite")
            monitor = Monitor(config, store)
            try:
                await monitor.scan(full=args.full)
                print(json.dumps(QueryService(monitor).status(), ensure_ascii=False, indent=2))
            finally:
                await monitor.close()
                store.close()

        asyncio.run(scan())


if __name__ == "__main__":
    main()
