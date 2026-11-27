"""Read-only deployment guard; never interrupt queued or running business jobs."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import func, select, inspect
from sqlalchemy.orm import Session

from app.database import AgentRun, ImageJob, CreationExecution, database_url, make_engine


def main():
    engine = make_engine(database_url())
    try:
        with Session(engine) as session:
            counts = {
                model.__tablename__: session.scalar(
                    select(func.count()).select_from(model).where(
                        model.status.in_(("queued", "running"))
                    )
                )
                for model in (ImageJob, AgentRun, CreationExecution)
            }
            if inspect(engine).has_table('market_queries'):
                from app.market_insights import MarketQuery
                counts['market_queries'] = session.scalar(select(func.count()).select_from(MarketQuery).where(
                    MarketQuery.status.in_(('queued', 'running'))))
        print(json.dumps({"active_or_queued": counts}))
        return 1 if any(counts.values()) else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
