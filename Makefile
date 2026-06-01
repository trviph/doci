.PHONY: atlas-new atlas-hash atlas-migrate

# Create a new migration file: make atlas-new name=add_something
atlas-new:
	atlas migrate new $(name) --dir "file://migrations"

atlas-hash:
	atlas migrate hash --dir "file://migrations"

atlas-migrate:
	atlas migrate apply --dir "file://migrations" --url "$(DATABASE_URL)"
