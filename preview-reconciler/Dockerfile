FROM python:3.13-alpine

RUN addgroup -g 10001 reconciler \
 && adduser -D -u 10001 -G reconciler reconciler
WORKDIR /app
COPY preview_reconciler.py /app/preview_reconciler.py
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "/app/preview_reconciler.py"]
