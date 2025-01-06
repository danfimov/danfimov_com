args := $(wordlist 2, 100, $(MAKECMDGOALS))

APPLICATION_NAME = danfimov_com

HELP_FUN = \
	%help; while(<>){push@{$$help{$$2//'options'}},[$$1,$$3] \
	if/^([\w-_]+)\s*:.*\#\#(?:@(\w+))?\s(.*)$$/}; \
    print"$$_:\n", map"  $$_->[0]".(" "x(20-length($$_->[0])))."$$_->[1]\n",\
    @{$$help{$$_}},"\n" for keys %help; \

CODE = src
TEST = pytest

ifndef args
MESSAGE = "No such command (or you pass two or many targets to ). List of possible commands: make help"
else
MESSAGE = "Done"
endif


help: ##@Help Show this help
	@echo -e "Usage: make [target] ...\n"
	@perl -e '$(HELP_FUN)' $(MAKEFILE_LIST)

watch: ##@Application Run application with hot reload
	uvicorn src.main:app --port 8000 --reload & \
	npx tailwindcss -i ./src/static/style/tailwind.css -o ./src/static/style/tailwind_output.css --watch
