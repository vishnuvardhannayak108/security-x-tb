# Discord Bot Configuration
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get token from environment variable or use placeholder
# Get token from environment variable
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise ValueError("No DISCORD_BOT_TOKEN found in environment variables. Please check your .env file.")

# Master Owner ID - The only user who can use Swork and Sstop commands
# Replace with your actual Discord User ID
MAIN_OWNER_ID = os.getenv('MAIN_OWNER_ID', '841264751320760331')

# Role-based permission settings
# Either set MANAGER_ROLE_NAME to the role name that should be allowed to run
# role-management commands, or set MANAGER_ROLE_IDS to a list of role IDs.
# If MANAGER_ROLE_IDS is non-empty it takes precedence.
MANAGER_ROLE_NAME = 'Manager'
MANAGER_ROLE_IDS = []  # e.g. [123456789012345678]