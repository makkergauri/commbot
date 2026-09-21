FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Uncomment for LLM / voice / Firebase support:
# RUN pip install --no-cache-dir -r requirements-optional.txt

COPY . .
# Keep the database on a volume so it survives container restarts.
ENV COMMBOT_DB=/data/commbot.db
VOLUME ["/data"]

# Default: the web server. Run the poller as a second container with
#   command: python -m commbot.cli run
EXPOSE 5000
CMD ["gunicorn", "commbot.wsgi:app", "-b", "0.0.0.0:5000", "-w", "2", "--timeout", "30"]
