import logging
import signal
import threading

from dotenv import load_dotenv

from listener import start_media_creation_listener
from shared import graph_client, kafka_client
from shared.startup import wait_for_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()
    wait_for_services()

    t = threading.Thread(target=start_media_creation_listener, daemon=True)
    t.start()

    shutdown = threading.Event()

    def _handle_signal(*_):
        logger.info("Shutting down media_verification service...")
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    shutdown.wait()

    graph_client.close_driver()
    kafka_client.close_producer()


if __name__ == "__main__":
    main()
