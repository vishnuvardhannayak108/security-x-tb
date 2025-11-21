import os
import discord
from bot import bot
from webserver import keep_alive
import time

if __name__ == '__main__':
    # Start the webserver
    keep_alive()
    
    # Get token from environment
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("ERROR: No token found in environment!")
        exit(1)

    # Run the bot with error handling
    while True:
        try:
            bot.run(TOKEN)
        except discord.LoginFailure:
            print("ERROR: Invalid bot token!")
            exit(1)
        except Exception as e:
            print(f"ERROR: {str(e)}")
            print("Attempting to reconnect in 5 seconds...")
            time.sleep(5)