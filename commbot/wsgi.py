"""
Entry point for gunicorn:  gunicorn "commbot.wsgi:app" -b 0.0.0.0:5000

Use a single worker. With RUN_POLLER on, each worker would start its own
fetch loop, and two loops would race each other over the same database.
"""
import logging

from .channels import get_sender
from .config import Settings
from .demo import seed_subscribers, start_background_poller
from .storage import Store
from .webhooks import create_app

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

settings = Settings()
if settings.demo_mode:
    # Never send real SMS from the public copy, whatever else is configured.
    settings.sms_provider = "console"

store = Store(settings.db_path)
sender = get_sender(settings)

if settings.demo_mode:
    seed_subscribers(store)
if settings.run_poller:
    start_background_poller(settings, store, sender)

app = create_app(settings, store, sender)