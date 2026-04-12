.PHONY: help build run view

DB="..\\app.db"
METADATA=".\\metadata.yaml"
INSPECT=".\\inspect-data.json"
STATIC_MOUNT="dataview:.\\static"
PORT=8001

help:
	@echo "Datasette playground for the parent app.db"
	@echo ""
	@echo "  make build  - refresh inspect-data.json from ..\\app.db"
	@echo "  make run    - serve Datasette locally on http://127.0.0.1:$(PORT)/"
	@echo "  make view   - serve Datasette and open the browser"

build:
	uv run datasette inspect $(DB) > $(INSPECT)

run: build
	uv run datasette serve -i $(DB) -m $(METADATA) --inspect-file $(INSPECT) --static $(STATIC_MOUNT) --setting allow_download off --setting allow_csv_stream off --setting default_cache_ttl 0 --setting default_page_size 50 --setting max_returned_rows 2000 --setting sql_time_limit_ms 4000 --host 127.0.0.1 --port $(PORT)

view: build
	uv run datasette serve -i $(DB) -m $(METADATA) --inspect-file $(INSPECT) --static $(STATIC_MOUNT) --setting allow_download off --setting allow_csv_stream off --setting default_cache_ttl 0 --setting default_page_size 50 --setting max_returned_rows 2000 --setting sql_time_limit_ms 4000 --host 127.0.0.1 --port $(PORT) --open
