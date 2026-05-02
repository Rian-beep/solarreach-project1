"""External-API adapter package.

Pluggable: every adapter has a Mock (default for dev/CI) and Real impl.
Pick via factory.get_adapter(name, mode='mock'|'real')."""
