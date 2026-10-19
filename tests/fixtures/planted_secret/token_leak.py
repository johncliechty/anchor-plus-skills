# PLANTED SECRET FIXTURE — for tests only. NOT shippable. Carries a concrete
# auth-token VALUE (not the bare env-var name) so the scan fails the build.
# The bare identifier ANCHOR_TOKEN (env var name) must NOT trip the scan; an
# assigned secret VALUE must.
ANCHOR_TOKEN = "a9F3kZ2pQ7wL5mN8xR1tY6vB4cD0eH2j"
