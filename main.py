import asyncio
import logging

import yaml
from dotenv import load_dotenv

from core.engine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def main() -> None:
    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    engine = TradingEngine(config)
    await engine.start()


if __name__ == "__main__":
    asyncio.run(main())
