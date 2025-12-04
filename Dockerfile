# Usar Python 3.11
FROM python:3.11-slim

# Crear carpeta de trabajo
WORKDIR /app

# Copiar archivo de dependencias
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el código
COPY . .

# Ejecutar el bot
CMD ["python", "bot.py"]