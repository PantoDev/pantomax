local.run.server:
	@scripts/run.sh

local.run.server.standalone:
	@python3 -m panto.server

local.run.cli:
	@python3 -m panto.cli review

local.services:
	@echo "Starting local services"
	@docker compose -f docker-compose.local.yml up
