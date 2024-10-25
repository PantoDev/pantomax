all: help

include makefiles/*.mk
-include panto_dashboard/makefiles/*.mk

help:
	@echo "Available commands:"
	@awk '/^[a-zA-Z0-9._-]+:/ { print "  " $$1 }' $(MAKEFILE_LIST) | sed 's/://' | grep -v .PHONY
