env "local" {
  dev = getenv("DEV_DATABASE_URL")
  url = getenv("DATABASE_URL")
  migration {
    dir = "file://migrations"
  }
}
