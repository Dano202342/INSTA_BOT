# Python 3.11 Slim asosidagi engil va xavfsiz muhit
FROM python:3.11-slim

# Tizim paketlari va FFmpeg'ni o'rnatish
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Ishchi katalog
WORKDIR /app

# Python chiqishini darhol terminalga chiqarish (unbuffered)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Kutubxonalarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Loyiha fayllarini ko'chirish
COPY . .

# Yuklab olingan fayllar uchun downloads papkasini yaratish
RUN mkdir -p downloads

# Botni ishga tushirish
CMD ["python", "main.py"]
