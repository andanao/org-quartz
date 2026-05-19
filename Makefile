.PHONY: combined personal serve serve-combined serve-personal deploy-nuc clean help

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  combined        - Build combined site"
	@echo "  personal        - Build personal site"
	@echo "  serve           - Serve existing build"
	@echo "  serve-combined  - Build and serve combined"
	@echo "  serve-personal  - Build and serve personal"
	@echo "  deploy-nuc      - Build combined and deploy to NUC"
	@echo "  clean           - Remove content/ and public/"

combined:
	python3 filter.py combined
	npx quartz build

personal:
	python3 filter.py personal
	npx quartz build

serve:
	npx quartz build --serve

serve-combined:
	python3 filter.py combined
	npx quartz build --serve

serve-personal:
	python3 filter.py personal
	npx quartz build --serve

nuc:
	./scripts/deploy-nuc.sh

clean:
	rm -rf content/ public/
