# Usa una imagen base oficial de Python para Cloud Run
FROM python:3.10-slim

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia los archivos de dependencias y código
COPY requirements.txt .
COPY app.py .

# Instala las dependencias de Python.
RUN pip install --no-cache-dir -r requirements.txt

# Cloud Run automáticamente expone el puerto que escucha la aplicación, 
# que por defecto es el 8080 si se usa la variable de entorno PORT.
# Gunicorn es un servidor WSGI que se ejecuta en el contenedor.
# Usamos --workers 4 para manejar varias solicitudes concurrentes.
CMD exec gunicorn --bind :$PORT --workers 4 --threads 4 app:app