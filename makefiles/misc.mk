test:
	@echo "Running tests"
	@pytest --disable-pytest-warnings tests/

image_name := panto

install:
	pip3 install -r requirements.txt

image.build:
	@echo "Building image '$(image_name)'..."
	docker build -t $(image_name) --platform=linux/amd64 --build-arg APP_VERSION=$(shell git rev-parse HEAD).$(shell date +%s) .

image.run:
	@echo "Running image"
	@docker rm -f $(image_name) 2>/dev/null || true
	docker run --rm -p 5001:5001 --name $(image_name) $(image_name)

deploy.prod:
	@echo "Deploying to prod"
	@./scripts/deploy-az-app.sh

pre-commit:
	@echo "Running pre-commit"
	@pre-commit run --all-files
