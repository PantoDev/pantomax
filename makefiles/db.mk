db.migration.create:
	@echo "Creating migration"
	@alembic -c ./panto/alembic.ini revision --autogenerate -m "$(msg)"

db.migration.upgrade:
	@echo "Upgrading migration"
	@alembic  -c ./panto/alembic.ini upgrade head

db.migration.downgrade:
	@echo "Downgrading migration"
	@alembic  -c ./panto/alembic.ini downgrade -1
