from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from .config import Config
from .store import Store


def setup(config: Config):
    from .content import import_jmdict

    fonts = config.root / "enki" / "assets" / "production"
    fonts.mkdir(parents=True, exist_ok=True)
    for name, url in {
        "NotoSansJP.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf",
        "IBMPlexMono.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
        "Manrope.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/Manrope%5Bwght%5D.ttf",
    }.items():
        path = fonts / name
        if not path.exists():
            response = httpx.get(url, timeout=90, follow_redirects=True)
            response.raise_for_status()
            path.write_bytes(response.content)
        print(f"Font ready: {name}")
    source = config.data / "JMdict_e.gz"
    if not source.exists():
        print("Downloading JMdict English source from EDRDG…", flush=True)
        with httpx.stream(
            "GET",
            "https://www.edrdg.org/pub/Nihongo/JMdict_e.gz",
            timeout=120,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            temp = source.with_suffix(".download")
            with temp.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
            temp.replace(source)
    store = Store(config)
    with store.connection() as db:
        imported = import_jmdict(db, source)
    print(f"Curriculum ready: {store.stats()['cards']} cards ({imported} common JMdict entries).")
    print("Dictionary credit: JMdict / Electronic Dictionary Research and Development Group.")
    print("https://www.edrdg.org/edrdg/licence.html")
    config.token()


def main():
    parser = argparse.ArgumentParser(prog="enki")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    sub.add_parser("status")
    backup = sub.add_parser("backup")
    backup.add_argument("destination", type=Path)
    sub.add_parser("device-key")
    importer = sub.add_parser("import")
    importer.add_argument("file", type=Path)
    args = parser.parse_args()
    config = Config.load()
    if args.command == "setup":
        setup(config)
    elif args.command == "serve":
        import uvicorn

        from .app import create_app

        import logging
        from logging.handlers import RotatingFileHandler

        logs = config.data / "logs"
        logs.mkdir(exist_ok=True, mode=0o700)
        handler = RotatingFileHandler(logs / "enki.log", maxBytes=5_000_000, backupCount=2)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        server_logger = logging.getLogger("uvicorn")
        server_logger.handlers = [handler]
        server_logger.propagate = False
        server_logger.setLevel(logging.INFO)
        uvicorn.run(
            create_app(config),
            host=args.host,
            port=args.port,
            proxy_headers=False,
            access_log=False,
            log_config=None,
        )
    elif args.command == "status":
        print(json.dumps(Store(config).stats(), indent=2))
    elif args.command == "backup":
        Store(config).backup(args.destination)
        print(f"Saved {args.destination}")
    elif args.command == "import":
        from .importer import import_cards

        print(f"Imported {import_cards(Store(config), args.file)} personal cards.")
    elif args.command == "device-key":
        print(config.token())


if __name__ == "__main__":
    main()
