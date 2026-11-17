FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY frontend ./frontend
COPY data ./data
COPY scripts ./scripts
EXPOSE 8000 8501
CMD ["uvicorn", "app.chat_api:app", "--host", "0.0.0.0", "--port", "8000"]
