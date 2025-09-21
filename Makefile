.PHONY: install test lint format api worker build-akash deploy-akash

install:
python -m pip install --upgrade pip
pip install -r requirements.txt

lint:
ruff check app tests

format:
black app tests
ruff check --fix app tests

api:
uvicorn app.main:app --reload --port 8000 --host 0.0.0.0

worker:
celery -A celery_main:celery_app worker --loglevel=info

test:
pytest -q

build-akash:
./scripts/build-for-akash.sh $(IMAGE)

deploy-akash:
./scripts/deploy-to-akash.sh $(MANIFEST)
