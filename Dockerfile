FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
RUN useradd --uid 10001 --create-home app && mkdir -p /data /app/staticfiles && chown -R app:app /data /app
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["sh", "deploy/entrypoint.sh"]
