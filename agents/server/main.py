import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from shared import graph_client, kafka_client
from shared.startup import wait_for_services
from routers import admin, posts, eval
from services import eval_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_services()
    graph_client.ensure_indexes()
    eval_consumer.start_eval_consumer()
    yield
    graph_client.close_driver()
    kafka_client.close_producer()


app = FastAPI(title="Fact-Check API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(posts.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(eval.router, prefix="/api/v1")

_MOCHEG_IMAGES_DIR = Path(__file__).parent.parent / "mocheg" / "test" / "images"
if _MOCHEG_IMAGES_DIR.exists():
    app.mount("/mocheg-images", StaticFiles(directory=str(_MOCHEG_IMAGES_DIR)), name="mocheg-images")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MAIN_PORT", "8081"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
