IMAGE ?= feedbin-mcp
PORT ?= 8000
CACHE_DIR ?= $(HOME)/.cache/feedbin-mcp

.PHONY: build run stop

build:
	docker build -t $(IMAGE) .

run: build
	mkdir -p "$(CACHE_DIR)"
	-docker rm -f $(IMAGE)
	docker run -d --name $(IMAGE) --restart unless-stopped \
		-p $(PORT):$(PORT) \
		-e FEEDBIN_MCP_PORT=$(PORT) \
		-e FEEDBIN_EMAIL \
		-e FEEDBIN_PASSWORD \
		-v "$(CACHE_DIR)":/data \
		$(IMAGE)

stop:
	docker stop $(IMAGE)
