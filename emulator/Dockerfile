FROM python:3.12-slim
WORKDIR /app

# emulator core
COPY emulator.py protocol.py png.py avatar_render.py admin.html ./
# client resource webroot served over HTTP
COPY runtime/res ./runtime/res
# DB (volume-mount overrides this at runtime)
COPY data ./data

ENV EMU_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080 9001 9002 9003
CMD ["python3", "emulator.py"]