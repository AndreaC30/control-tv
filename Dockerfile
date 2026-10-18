FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# En contenedor escucha en la red Docker; no abrir navegador.
RUN sed -i 's/("127.0.0.1", PORT)/("0.0.0.0", PORT)/' mando.py \
    && sed -i 's/webbrowser.open(url)/pass/' mando.py

EXPOSE 8765 8766

CMD ["python3", "mando.py"]
