"""Run with uv run python -m app.worker. One process handles one image at a time."""
import time

from app.database import database_url, data_directory, make_engine
from app.image_jobs import process_one


def main():
    url = database_url()
    if not url:
        raise SystemExit("请先配置 PostgreSQL。")
    engine = make_engine(url)
    print("Image Worker 已启动，等待任务。不会自动重试不确定的生图请求。", flush=True)
    try:
        while True:
            try:
                if not process_one(engine, data_directory()):
                    time.sleep(2)
            except KeyboardInterrupt:
                raise
            except Exception:
                print("数据库或任务暂不可用，5 秒后重新检查队列。", flush=True)
                time.sleep(5)
    except KeyboardInterrupt:
        print("Worker 已停止。", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
