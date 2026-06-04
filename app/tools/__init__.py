# Importing each module causes its @registry.register decorators to execute,
# populating the registry. To add a new tool: create app/tools/your_tool.py
# and add it here. Nothing else needs to change.
from app.tools import ask_user, run_command  # noqa: F401
