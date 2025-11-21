import sys
import time
import logging
import discord
import asyncio

# Get logger from the main bot module
logger = logging.getLogger(__name__)


def run_bot_with_error_handling(bot, TOKEN, on_shutdown=None):
    """
    Main bot loop with advanced error handling.
    
    Args:
        bot: Discord bot instance
        TOKEN: Discord bot token
        on_shutdown: Optional callback function to run on shutdown/restart (e.g. for saving data)
    """
    retry_count = 0
    while True:
        try:
            logger.info("Starting bot...")
            bot.run(TOKEN)
        except discord.errors.PrivilegedIntentsRequired:
            logger.error("ERROR: Privileged Intents Not Enabled!")
            logger.error("Please enable MESSAGE CONTENT INTENT and SERVER MEMBERS INTENT")
            sys.exit(1)
            
        except discord.LoginFailure:
            logger.error("ERROR: Invalid token")
            sys.exit(1)
        except discord.ConnectionClosed as e:
            retry_count += 1
            wait_time = min(retry_count * 5, 60)  # Exponential backoff up to 60 seconds
            logger.warning(f"Connection closed. Retrying in {wait_time} seconds... (Attempt {retry_count})")
            time.sleep(wait_time)
        except discord.GatewayNotFound:
            logger.error("Discord gateway not found. Retrying in 30 seconds...")
            time.sleep(30)
        except discord.HTTPException as e:
            logger.error(f"HTTP Error: {e}")
            if e.status >= 500:  # Server error, retry
                time.sleep(5)
            else:
                sys.exit(1)
        except asyncio.CancelledError:
            logger.warning("Asyncio task cancelled (likely connection timeout). Retrying...")
            retry_count += 1
            time.sleep(5)
            if retry_count > 5:
                logger.error("Too many connection cancellations. Exiting.")
                sys.exit(1)
        except RuntimeError as e:
            error_msg = str(e)
            if "Session is closed" in error_msg or "session" in error_msg.lower():
                logger.warning(f"Session was closed. Attempting to reconnect...")
                # Save data before retry
                if on_shutdown:
                    try:
                        on_shutdown()
                        logger.info("Data saved before reconnection attempt")
                    except Exception as save_error:
                        logger.error(f"Failed to save data: {save_error}")
                
                # Wait and retry
                time.sleep(5)
                if retry_count < 3:
                    retry_count += 1
                    logger.info(f"Reconnection attempt {retry_count}/3...")
                    continue
                else:
                    logger.error("Too many reconnection attempts. Please restart manually.")
                    sys.exit(1)
            else:
                logger.error(f"Runtime error: {e}")
                if retry_count < 5:
                    retry_count += 1
                    logger.info(f"Attempting restart... (Attempt {retry_count})")
                    time.sleep(5)
                else:
                    logger.error("Too many restart attempts. Exiting.")
                    sys.exit(1)
        except discord.ClientException as e:
            error_msg = str(e)
            if "Session is closed" in error_msg or "session" in error_msg.lower():
                logger.warning(f"Session was closed, likely due to previous shutdown. Waiting before restart...")
                time.sleep(3)  # Wait for cleanup
            else:
                logger.error(f"Client error: {e}")
            if retry_count < 5:
                retry_count += 1
                logger.info(f"Attempting restart... (Attempt {retry_count})")
                time.sleep(5)
            else:
                logger.error("Too many restart attempts. Exiting.")
                sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Bot shutdown requested by user")
            try:
                if not bot.is_closed():
                    loop = asyncio.get_event_loop()
                    if not loop.is_closed():
                        if loop.is_running():
                            asyncio.create_task(bot.close())
                        else:
                            loop.run_until_complete(bot.close())
            except Exception:
                pass
            sys.exit(0)
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            # Check if it's a session-related error
            if "Session is closed" in str(e) or "session" in str(e).lower():
                logger.warning("Session error detected, waiting before restart...")
                try:
                    if not bot.is_closed():
                        loop = asyncio.get_event_loop()
                        if not loop.is_closed():
                            if loop.is_running():
                                asyncio.create_task(bot.close())
                            else:
                                loop.run_until_complete(bot.close())
                except Exception:
                    pass
                time.sleep(3)
            if retry_count < 5:
                retry_count += 1
                logger.info(f"Attempting restart... (Attempt {retry_count})")
                time.sleep(5)
            else:
                logger.error("Too many restart attempts. Exiting.")
                sys.exit(1)