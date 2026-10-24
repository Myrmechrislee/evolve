FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home evolve
COPY --chown=evolve:evolve . .
USER evolve
EXPOSE 9000
CMD ["flask", "--app", "app", "run", "--host=0.0.0.0", "--port=9000"]
