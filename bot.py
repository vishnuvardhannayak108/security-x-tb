import os
import sys
import time
import logging
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Union, Tuple, Any
from pathlib import Path

# Add the current directory to Python path to ensure local imports work
sys.path.insert(0, str(Path(__file__).parent.absolute()))

import discord
from discord.ext import commands

# Import keep_alive from local webserver.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from webserver import keep_alive
from error_handling import run_bot_with_error_handling

# Custom type definitions for improved clarity
GuildID = int
UserID = int
RoleID = int
CommandCooldown = Dict[UserID, float]
PermissionList = List[str]
GuildContext = Union[discord.Guild, None]
MemberContext = Union[discord.Member, None]

# Set up comprehensive logging to track all bot functions
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Set up specific loggers for different bot functions
command_logger = logging.getLogger('bot.commands')
error_logger = logging.getLogger('bot.errors')
permission_logger = logging.getLogger('bot.permissions')

# Try to load manager-role config (optional)
try:
    from config import MANAGER_ROLE_NAME, MANAGER_ROLE_IDS
except Exception:
    MANAGER_ROLE_NAME = 'Manager'
    MANAGER_ROLE_IDS = []


def is_manager_member(member: discord.Member) -> bool:
    """Return True if member has the configured manager role (by ID or name)."""
    # If IDs provided, prefer them
    if MANAGER_ROLE_IDS:
        try:
            ids = [int(x) for x in MANAGER_ROLE_IDS]
        except Exception:
            ids = MANAGER_ROLE_IDS
        return any(r.id in ids for r in member.roles)
    # Fall back to name match
    return any(r.name == MANAGER_ROLE_NAME for r in member.roles)

# Helper functions for punishment application
async def apply_mute(ctx, member: discord.Member, duration: int, reason: str):
    """Apply mute punishment (used by warn system)."""
    try:
        until = discord.utils.utcnow() + timedelta(minutes=duration)
        await member.timeout(until, reason=reason)
        embed = discord.Embed(
            title='Automatic Mute Applied',
            description=f'{member.mention} has been muted for {duration} minutes due to excessive warnings.',
            color=discord.Color.dark_gray()
        )
        embed.add_field(name='Reason', value=reason, inline=False)
        await ctx.send(embed=embed)
        command_logger.info(f"auto_mute: SUCCESS - Member {member.name} (ID: {member.id}) muted for {duration} minutes in guild {ctx.guild.name} (ID: {ctx.guild.id}) for reason: {reason}")
    except Exception as e:
        error_logger.error(f"auto_mute: ERROR - Failed to mute {member.id}: {str(e)}")
        await ctx.send(f'⚠️ Failed to apply automatic mute: {str(e)}')

async def apply_kick(ctx, member: discord.Member, reason: str):
    """Apply kick punishment (used by warn system)."""
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(
            title='Automatic Kick Applied',
            description=f'{member.mention} has been kicked due to excessive warnings.',
            color=discord.Color.orange()
        )
        embed.add_field(name='Reason', value=reason, inline=False)
        await ctx.send(embed=embed)
        command_logger.info(f"auto_kick: SUCCESS - Member {member.name} (ID: {member.id}) kicked from guild {ctx.guild.name} (ID: {ctx.guild.id}) for reason: {reason}")
    except Exception as e:
        error_logger.error(f"auto_kick: ERROR - Failed to kick {member.id}: {str(e)}")
        await ctx.send(f'⚠️ Failed to apply automatic kick: {str(e)}')

async def apply_ban(ctx, member: discord.Member, reason: str):
    """Apply ban punishment (used by warn system)."""
    try:
        await member.ban(reason=reason)
        embed = discord.Embed(
            title='Automatic Ban Applied',
            description=f'{member.mention} has been banned due to excessive warnings.',
            color=discord.Color.red()
        )
        embed.add_field(name='Reason', value=reason, inline=False)
        await ctx.send(embed=embed)
        command_logger.info(f"auto_ban: SUCCESS - Member {member.name} (ID: {member.id}) banned from guild {ctx.guild.name} (ID: {ctx.guild.id}) for reason: {reason}")
    except Exception as e:
        error_logger.error(f"auto_ban: ERROR - Failed to ban {member.id}: {str(e)}")
        await ctx.send(f'⚠️ Failed to apply automatic ban: {str(e)}')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# Warnings system
warnings_file = 'warnings.json'
warnings_backup_file = 'warnings_backup.json'

def load_warnings():
    """Load warnings data from file."""
    if os.path.exists(warnings_file):
        try:
            with open(warnings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Create backup on successful load
                try:
                    with open(warnings_backup_file, 'w', encoding='utf-8') as backup:
                        json.dump(data, backup, indent=4)
                except Exception:
                    pass
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            # Try to load from backup if main file is corrupted
            if os.path.exists(warnings_backup_file):
                try:
                    logger.warning("Main warnings file corrupted, loading from backup...")
                    with open(warnings_backup_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
            return {}
    return {}

import tempfile
import shutil

async def save_json_async(filename: str, data: dict):
    """Save JSON data asynchronously and atomically."""
    def _write_json():
        # Write to a temp file first to avoid corruption
        dir_path = os.path.dirname(os.path.abspath(filename))
        with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=4, ensure_ascii=False)
            tmp_path = tmp.name
        
        # Atomic replace
        shutil.move(tmp_path, filename)

    try:
        await bot.loop.run_in_executor(None, _write_json)
    except Exception as e:
        logger.error(f"Failed to save {filename}: {e}")
        raise

def save_json_sync(filename: str, data: dict):
    """Save JSON data synchronously and atomically (for emergency backups)."""
    try:
        dir_path = os.path.dirname(os.path.abspath(filename))
        with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=4, ensure_ascii=False)
            tmp_path = tmp.name
        shutil.move(tmp_path, filename)
    except Exception as e:
        logger.error(f"Failed to save {filename} synchronously: {e}")

async def save_warnings(warnings, create_backup=True):
    """Save warnings data to file with backup."""
    try:
        # Save to main file
        await save_json_async(warnings_file, warnings)
        
        # Create backup
        if create_backup:
            try:
                await save_json_async(warnings_backup_file, warnings)
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")
    except Exception as e:
        logger.error(f"Failed to save warnings: {e}")

def save_warnings_sync(warnings, create_backup=True):
    """Save warnings data synchronously (for emergency backups)."""
    try:
        save_json_sync(warnings_file, warnings)
        if create_backup:
            save_json_sync(warnings_backup_file, warnings)
    except Exception as e:
        logger.error(f"Failed to save warnings synchronously: {e}")

warnings_data = load_warnings()
logger.info(f"Loaded {sum(len(guild_data) for guild_data in warnings_data.values())} user warnings from {len(warnings_data)} guilds")

# Security system (Anti-nuke & Anti-spam)
security_file = 'security_settings.json'

def load_security_settings():
    """Load security settings from file."""
    default_settings = {
        'antinuke_enabled': True,
        'antispam_enabled': True,
        'antinuke_ban_threshold': 5,  # Ban if user performs 5+ actions in 10 seconds
        'antinuke_kick_threshold': 3,  # Kick if user performs 3+ actions in 10 seconds
        'antinuke_time_window': 10,  # Time window in seconds
        'antispam_message_limit': 5,  # Max messages per time window
        'antispam_time_window': 5,  # Time window in seconds
        'antispam_mention_limit': 5,  # Max mentions per message
        'antispam_duplicate_limit': 3,  # Max duplicate messages
        'antispam_action': 'mute',  # mute, kick, or ban
        'antispam_mute_duration': 10,  # Minutes to mute
        'whitelisted_roles': [],  # Role IDs exempt from security checks
        'log_channel': None  # Channel ID for security logs
    }
    
    if os.path.exists(security_file):
        try:
            with open(security_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # Merge with defaults to ensure all keys exist
                for key, value in default_settings.items():
                    if key not in settings:
                        settings[key] = value
                return settings
        except (json.JSONDecodeError, FileNotFoundError):
            return default_settings
    return default_settings

async def save_security_settings(settings):
    """Save security settings to file."""
    try:
        await save_json_async(security_file, settings)
    except Exception as e:
        logger.error(f"Failed to save security settings: {e}")

security_settings = load_security_settings()

# Track user actions for anti-nuke
user_action_tracker = {}  # {guild_id: {user_id: [(action_type, timestamp), ...]}}

# Track spam activity
spam_tracker = {}  # {guild_id: {user_id: {'messages': [(content, timestamp), ...], 'last_message': timestamp}}}

# Track unknown commands to prevent spam
unknown_command_tracker = {}  # {user_id: {'count': int, 'last_time': float}}

def is_whitelisted(member: discord.Member) -> bool:
    """Check if member is whitelisted from security checks."""
    if not security_settings.get('whitelisted_roles', []):
        return False
    whitelisted_ids = [int(rid) for rid in security_settings.get('whitelisted_roles', [])]
    return any(role.id in whitelisted_ids for role in member.roles)

async def handle_antinuke_violation(guild: discord.Guild, user: discord.Member, action_count: int):
    """Handle anti-nuke violation by banning/kicking the offender."""
    try:
        if not security_settings.get('antinuke_enabled', True):
            return
        
        if is_whitelisted(user):
            return
        
        ban_threshold = security_settings.get('antinuke_ban_threshold', 5)
        kick_threshold = security_settings.get('antinuke_kick_threshold', 3)
        
        reason = f"Anti-nuke protection: {action_count} suspicious actions detected"
        
        if action_count >= ban_threshold:
            try:
                await user.ban(reason=reason, delete_message_days=0)
                logger.warning(f"ANTI-NUKE: Banned {user} (ID: {user.id}) in guild {guild.id} for {action_count} actions")
            except Exception as e:
                logger.error(f"Failed to ban nuker {user.id}: {e}")
        elif action_count >= kick_threshold:
            try:
                await user.kick(reason=reason)
                logger.warning(f"ANTI-NUKE: Kicked {user} (ID: {user.id}) in guild {guild.id} for {action_count} actions")
            except Exception as e:
                logger.error(f"Failed to kick nuker {user.id}: {e}")
    except Exception as e:
        logger.error(f"Error handling anti-nuke violation: {e}")

def track_user_action(guild_id: int, user_id: int, action_type: str):
    """Track user action for anti-nuke detection."""
    if guild_id not in user_action_tracker:
        user_action_tracker[guild_id] = {}
    if user_id not in user_action_tracker[guild_id]:
        user_action_tracker[guild_id][user_id] = []
    
    current_time = time.time()
    time_window = security_settings.get('antinuke_time_window', 10)
    
    # Add new action
    user_action_tracker[guild_id][user_id].append((action_type, current_time))
    
    # Remove old actions outside time window
    user_action_tracker[guild_id][user_id] = [
        (action, timestamp) for action, timestamp in user_action_tracker[guild_id][user_id]
        if current_time - timestamp < time_window
    ]
    
    return len(user_action_tracker[guild_id][user_id])

# Master control system
try:
    from config import MAIN_OWNER_ID
except ImportError:
    MAIN_OWNER_ID = os.getenv('MAIN_OWNER_ID', 'YOUR_USER_ID_HERE')


# Bot state persistence
bot_state_file = 'bot_state.json'

def load_bot_state():
    """Load bot state from file."""
    if os.path.exists(bot_state_file):
        try:
            with open(bot_state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return {'enabled': False}

def save_bot_state(state):
    """Save bot state to file."""
    try:
        with open(bot_state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save bot state: {e}")

# Load bot state from file
bot_state = load_bot_state()
botEnabled = bot_state.get('enabled', False)  # Load saved state or default to False
logger.info(f"Bot state loaded: {'ENABLED' if botEnabled else 'DISABLED'}")


def is_owner(user_id: int) -> bool:
    """Check if user is the main owner."""
    try:
        # Handle both string and int types
        if isinstance(MAIN_OWNER_ID, str):
            if MAIN_OWNER_ID.isdigit():
                owner_id = int(MAIN_OWNER_ID)
            else:
                logger.warning(f"MAIN_OWNER_ID is not a valid number string: {MAIN_OWNER_ID}")
                return False
        elif isinstance(MAIN_OWNER_ID, int):
            owner_id = MAIN_OWNER_ID
        else:
            logger.warning(f"MAIN_OWNER_ID is invalid type: {type(MAIN_OWNER_ID)}, value: {MAIN_OWNER_ID}")
            return False
        
        result = (owner_id == user_id)
        if not result:
            logger.debug(f"Owner check failed: user_id={user_id}, owner_id={owner_id}, MAIN_OWNER_ID={MAIN_OWNER_ID}")
        return result
    except (ValueError, AttributeError, TypeError) as e:
        logger.error(f"Error checking owner: {e}, MAIN_OWNER_ID={MAIN_OWNER_ID}, user_id={user_id}")
        return False

# Command cooldowns
command_cooldowns = {}  # Store last usage time for each user
COOLDOWN_TIME = 3  # seconds between commands per user

def check_cooldown(ctx):
    """Check if user is on cooldown."""
    if not isinstance(ctx.channel, discord.DMChannel):  # Skip cooldown in DMs
        current_time = time.time()
        user_id = ctx.author.id
        if user_id in command_cooldowns:
            time_diff = current_time - command_cooldowns[user_id]
            if time_diff < COOLDOWN_TIME:
                return False
        command_cooldowns[user_id] = current_time
    return True

# Track bot health
last_heartbeat = datetime.now(timezone.utc)
is_ready = False

bot = commands.Bot(
    command_prefix='S',
    intents=intents,
    help_command=None
)

@bot.before_invoke
async def before_command(ctx):
    global botEnabled

    # Reset unknown command count on successful command invocation
    user_id = ctx.author.id
    if user_id in unknown_command_tracker:
        unknown_command_tracker[user_id]['count'] = 0

    command_logger.info(f"Command '{ctx.command.name}' invoked by {ctx.author} (ID: {ctx.author.id}) in guild '{ctx.guild.name if ctx.guild else 'DM'}' (ID: {ctx.guild.id if ctx.guild else 'N/A'})")

    # Helper to safely send messages
    async def safe_send(content, ephemeral=False):
        try:
            if ctx.interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(content, ephemeral=ephemeral)
                else:
                    await ctx.interaction.followup.send(content, ephemeral=ephemeral)
            else:
                await ctx.send(content)
        except Exception as e:
            logger.error(f"Error sending message in before_invoke: {e}")

    # Check if command is owner-only (Swork or Sstop)
    if hasattr(ctx.command, 'owner_only') and ctx.command.owner_only:
        if not is_owner(ctx.author.id):
            await safe_send('❌ You do not have permission to use this command.', ephemeral=True)
            raise commands.CommandError('OwnerOnly')

    # Check if bot is enabled (except for Swork command)
    if not botEnabled and ctx.command.name != 'work':
        await safe_send('❌ Bot is disabled. Use Swork to enable it.', ephemeral=True)
        raise commands.CommandError('BotDisabled')

    if not check_cooldown(ctx):
        remaining = COOLDOWN_TIME - (time.time() - command_cooldowns.get(ctx.author.id, 0))
        command_logger.warning(f"Command '{ctx.command.name}' blocked due to cooldown for user {ctx.author.id}, remaining: {remaining:.1f}s")
        await safe_send(f'⏳ Please wait {remaining:.1f}s before using another command.', ephemeral=True)
        raise commands.CommandError('Cooldown')

async def check_heartbeat() -> None:
    """
    Monitor bot's health and restart if needed.
    Implements exponential backoff for retries and proper error handling.
    """
    retry_count = 0
    max_retries = 5
    base_delay = 30  # Base delay between checks in seconds

    while True:
        try:
            # Exponential backoff for retry delay
            current_delay = min(base_delay * (2 ** retry_count), 300)  # Max 5 minutes
            await asyncio.sleep(current_delay)

            # Check bot's heartbeat and connectivity
            if bot.is_ready() and bot.latency < 10:  # Bot is responsive
                # Update heartbeat and reset retry count
                global last_heartbeat
                last_heartbeat = datetime.now(timezone.utc)
                retry_count = 0
                logger.debug("Bot heartbeat check passed")
            else:
                # Check if we've exceeded timeout threshold
                time_since_heartbeat = (datetime.now(timezone.utc) - last_heartbeat).total_seconds()
                if time_since_heartbeat > 120:  # 2 minutes timeout (increased from 60)
                    logger.error(f"Bot heartbeat timeout detected - {time_since_heartbeat:.1f}s since last heartbeat")

                    if retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"Attempting restart (Attempt {retry_count}/{max_retries})")
                        await bot.close()
                        break  # Exit the loop to allow restart
                    else:
                        logger.critical("Max retry attempts reached. Manual intervention required.")
                        break
                else:
                    logger.warning(f"Bot appears unresponsive but within timeout window ({time_since_heartbeat:.1f}s)")

        except asyncio.CancelledError:
            logger.info("Heartbeat check cancelled - shutting down")
            break

        except Exception as e:
            logger.error(f"Error in heartbeat check: {str(e)}", exc_info=True)
            retry_count += 1

            if retry_count >= max_retries:
                    logger.critical("Heartbeat check failing consistently. Manual intervention required.")
                    break

async def auto_save_warnings():
    """Periodically auto-save warnings data to prevent data loss."""
    while True:
        try:
            await asyncio.sleep(300)  # Save every 5 minutes
            if warnings_data:
                await save_warnings(warnings_data)
                logger.debug("Auto-saved warnings data")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in auto-save: {e}")

@bot.event
async def on_ready():
    global last_heartbeat, is_ready, warnings_data
    last_heartbeat = datetime.now(timezone.utc)
    is_ready = True

    logger.info(f'Bot connected to Discord as {bot.user} (ID: {bot.user.id})')
    logger.info(f'Bot is active in {len(bot.guilds)} guilds')
    logger.info(f'Bot Status: {"🟢 ENABLED" if botEnabled else "🔴 DISABLED"} - Use Swork to enable')
    logger.info(f'Main Owner ID: {MAIN_OWNER_ID}')
    
    # Reload warnings data on reconnect to ensure we have latest
    warnings_data = load_warnings()
    logger.info(f'Loaded warnings data: {sum(len(guild_data) for guild_data in warnings_data.values())} user warnings from {len(warnings_data)} guilds')
    
    command_logger.info('Bot initialization completed successfully')

    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')

    # Start health monitoring
    bot.loop.create_task(check_heartbeat())
    
    # Start auto-save task
    bot.loop.create_task(auto_save_warnings())

    # Sync commands with guilds
    try:
        for guild in bot.guilds:
            try:
                await bot.tree.sync(guild=guild)
                logger.info(f'Synced commands for guild: {guild.name} (ID: {guild.id})')
                print(f'Synced commands for guild: {guild.name}')
            except Exception as e:
                logger.error(f'Failed to sync commands for guild {guild.name} (ID: {guild.id}): {e}')
                print(f'Failed to sync commands for guild {guild.name}: {e}')
        await bot.tree.sync()  # Global sync
        logger.info('Synced commands globally')
        print('Synced commands globally')
    except Exception as e:
        logger.error(f'Failed to sync commands globally: {e}')
        print(f'Failed to sync commands: {e}')

@bot.event
async def on_disconnect():
    """Save all data when bot disconnects."""
    logger.info("Bot disconnecting, saving all data...")
    try:
        await save_warnings(warnings_data)
        logger.info("All data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data on disconnect: {e}")

@bot.event
async def on_resume():
    """Handle bot reconnection."""
    logger.info("Bot reconnected, reloading data...")
    global warnings_data
    warnings_data = load_warnings()
    logger.info(f'Reloaded warnings data after reconnection')

@bot.event
async def on_message(message):
    """Handle incoming messages and process commands."""
    # Don't process messages from bots
    if message.author.bot:
        return

    # Anti-spam check
    if message.guild and security_settings.get('antispam_enabled', True):
        if isinstance(message.author, discord.Member) and not is_whitelisted(message.author):
            guild_id = message.guild.id
            user_id = message.author.id
            
            if guild_id not in spam_tracker:
                spam_tracker[guild_id] = {}
            if user_id not in spam_tracker[guild_id]:
                spam_tracker[guild_id][user_id] = {'messages': [], 'last_message': 0}
            
            current_time = time.time()
            time_window = security_settings.get('antispam_time_window', 5)
            message_limit = security_settings.get('antispam_message_limit', 5)
            mention_limit = security_settings.get('antispam_mention_limit', 5)
            duplicate_limit = security_settings.get('antispam_duplicate_limit', 3)
            
            user_data = spam_tracker[guild_id][user_id]
            
            # Check message rate
            recent_messages = [
                (content, timestamp) for content, timestamp in user_data['messages']
                if current_time - timestamp < time_window
            ]
            
            # Check mentions
            mention_count = len(message.mentions) + len(message.role_mentions)
            
            # Check duplicates
            duplicate_count = sum(1 for content, _ in recent_messages if content == message.content)
            
            # Check for spam
            is_spam = False
            spam_reason = []
            
            if len(recent_messages) >= message_limit:
                is_spam = True
                spam_reason.append(f"{len(recent_messages)} messages in {time_window}s")
            
            if mention_count > mention_limit:
                is_spam = True
                spam_reason.append(f"{mention_count} mentions")
            
            if duplicate_count >= duplicate_limit:
                is_spam = True
                spam_reason.append(f"{duplicate_count} duplicate messages")
            
            if is_spam:
                action = security_settings.get('antispam_action', 'mute')
                reason = f"Anti-spam: {', '.join(spam_reason)}"
                
                try:
                    if action == 'ban':
                        await message.author.ban(reason=reason, delete_message_days=0)
                    elif action == 'kick':
                        await message.author.kick(reason=reason)
                    elif action == 'mute':
                        mute_duration = security_settings.get('antispam_mute_duration', 10)
                        until = discord.utils.utcnow() + timedelta(minutes=mute_duration)
                        await message.author.timeout(until, reason=reason)
                    
                    # Delete spam messages
                    try:
                        await message.delete()
                    except:
                        pass
                    
                    logger.warning(f"ANTI-SPAM: {action.upper()} applied to {message.author} (ID: {message.author.id}) in guild {message.guild.id}: {reason}")
                except Exception as e:
                    logger.error(f"Failed to apply anti-spam action: {e}")
                
                # Clear spam tracker for this user
                spam_tracker[guild_id][user_id] = {'messages': [], 'last_message': 0}
                return  # Don't process the spam message
            
            # Track message
            user_data['messages'].append((message.content, current_time))
            user_data['last_message'] = current_time
            
            # Clean old messages
            user_data['messages'] = [
                (content, timestamp) for content, timestamp in user_data['messages']
                if current_time - timestamp < time_window * 2
            ]

    logger.debug(f"Message received from {message.author} (ID: {message.author.id}) in guild {message.guild.name if message.guild else 'DM'}: {message.content}")

    # Process commands
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    """
    Handle command errors with privacy-conscious logging.
    
    Args:
        ctx (commands.Context): The command context
        error (Exception): The error that occurred
    """
    # Get anonymized context for logging
    guild_id = ctx.guild.id if ctx.guild else None
    channel_id = ctx.channel.id if ctx.channel else None
    
    error_context = {
        'guild_id': guild_id,
        'channel_id': channel_id,
        'command_name': ctx.command.name if ctx.command else 'Unknown'
    }

    # Helper to safely send messages
    async def safe_send(content):
        try:
            if ctx.interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(content, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(content, ephemeral=True)
            else:
                await ctx.send(content)
        except Exception as e:
            logger.error(f"Error sending message in on_command_error: {e}")
    
    # Handle custom errors from before_invoke
    if isinstance(error, commands.CommandError):
        error_msg = str(error)
        if error_msg in ['OwnerOnly', 'BotDisabled', 'Cooldown']:
            # Already handled in before_invoke, just return
            return
    
    if isinstance(error, commands.CommandNotFound):
        user_id = ctx.author.id
        current_time = time.time()

        # Track unknown commands
        if user_id not in unknown_command_tracker:
            unknown_command_tracker[user_id] = {'count': 0, 'last_time': 0}

        # Reset count if more than 5 minutes have passed since last unknown command
        if current_time - unknown_command_tracker[user_id]['last_time'] > 300:  # 5 minutes
            unknown_command_tracker[user_id]['count'] = 0

        unknown_command_tracker[user_id]['count'] += 1
        unknown_command_tracker[user_id]['last_time'] = current_time

        # Check if user has exceeded threshold
        if unknown_command_tracker[user_id]['count'] >= 3:
            # Apply punishment: mute for 10 minutes
            if ctx.guild:
                try:
                    until = discord.utils.utcnow() + timedelta(minutes=10)
                    await ctx.author.timeout(until, reason="Spamming unknown commands")
                    await safe_send(f'🚫 {ctx.author.mention} has been muted for 10 minutes due to spamming unknown commands.')
                    logger.warning(f"User {ctx.author} (ID: {user_id}) muted for spamming unknown commands in guild {guild_id}")
                    # Reset count after punishment
                    unknown_command_tracker[user_id]['count'] = 0
                except Exception as e:
                    logger.error(f"Failed to mute user {user_id} for unknown command spam: {e}")
                    await safe_send('❌ Unknown command. Use `/help` to see available commands.')
            else:
                await safe_send('❌ Unknown command. Use `/help` to see available commands.')
        else:
            # Silent for first 2 attempts to avoid spam, just log it
            # Only send message if it's the 2nd attempt (warning before mute)
            if unknown_command_tracker[user_id]['count'] == 2:
                await safe_send('❌ Unknown command. Use `/help` to see available commands.')
            
        logger.info(f"Command not found in guild {guild_id} - Count: {unknown_command_tracker[user_id]['count']}")
        
    elif isinstance(error, commands.MissingPermissions):
        await safe_send('❌ You need Administrator permission to use this command.')
        logger.warning(f"Missing permissions in guild {guild_id} for command {ctx.command.name}")
        
    elif isinstance(error, commands.BotMissingPermissions):
        missing = [perm.replace('_', ' ').title() for perm in error.missing_permissions]
        await safe_send(f'❌ I need the following permissions: {", ".join(missing)}')
        logger.error(f"Bot missing permissions in guild {guild_id}: {missing}")
        
    elif isinstance(error, commands.MissingRequiredArgument):
        await safe_send(f'❌ Missing required argument: {error.param.name}. Check `/help` for usage.')
        logger.info(f"Missing argument in guild {guild_id}: {error.param.name}")
        
    elif isinstance(error, commands.BadArgument):
        await safe_send('❌ Invalid argument provided. Please check `/help` for correct usage.')
        logger.warning(f"Bad argument in guild {guild_id} for command {ctx.command.name}")
        
    else:
        await safe_send('❌ An unexpected error occurred. Please try again later.')
        logger.error(
            "Uncaught error in command execution",
            extra={
                'error_type': type(error).__name__,
                'error_message': str(error),
                **error_context
            },
            exc_info=True
        )
    
    # Log bot permissions only if there's a permission-related error
    if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions)):
        if ctx.guild:
            logger.debug(
                "Bot permission details",
                extra={
                    'guild_id': guild_id,
                    'bot_permissions': [p[0] for p in ctx.guild.me.guild_permissions if p[1]],
                    'bot_top_role_position': ctx.guild.me.top_role.position
                }
            )

@bot.hybrid_command(name='addrole', description='Add a role to a member', default_member_permissions=discord.Permissions(administrator=True))
async def addrole(ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
    """
    Add a role to a member with comprehensive permission checks and error handling.
    
    Args:
        ctx (commands.Context): The command context
        member (discord.Member): The member to add the role to
        role (discord.Role): The role to add
        
    Raises:
        commands.MissingPermissions: If the user lacks required permissions
        discord.Forbidden: If the bot lacks required permissions
        discord.HTTPException: If the role addition fails
    """
    try:
        # Log command execution start
        command_logger.info(f"addrole: Started - Target: {member} (ID: {member.id}), Role: {role.name} (ID: {role.id}), Guild: {ctx.guild.name} (ID: {ctx.guild.id})")

        # Check if user has administrator permission
        if not ctx.author.guild_permissions.administrator:
            permission_logger.warning(f"addrole: Permission denied - User {ctx.author} (ID: {ctx.author.id}) lacks Administrator permission in guild {ctx.guild.id}")
            await ctx.send("❌ You don't have permission to use this command. Required: Administrator permission.")
            return

        # Validate bot permissions
        if not ctx.guild.me.guild_permissions.manage_roles:
            permission_logger.error(f"addrole: Bot missing manage_roles permission in guild {ctx.guild.id}")
            await ctx.send('❌ I need the "Manage Roles" permission to execute this command.')
            return

        # Check role hierarchy for user
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            permission_logger.warning(f"addrole: Hierarchy violation - User {ctx.author.id} cannot assign role {role.id} (higher/equal to user's role) in guild {ctx.guild.id}")
            await ctx.send('❌ You cannot add a role higher than or equal to your highest role.')
            return

        # Check role hierarchy for bot
        if role >= ctx.guild.me.top_role:
            permission_logger.error(f"addrole: Bot hierarchy insufficient - Cannot assign role {role.id} (higher/equal to bot's role) in guild {ctx.guild.id}")
            await ctx.send('❌ I cannot assign a role higher than or equal to my highest role.')
            return

        # Check for existing role
        if role in member.roles:
            command_logger.info(f"addrole: Role {role.id} already exists on member {member.id} in guild {ctx.guild.id}")
            await ctx.send(f'❌ {member.mention} already has the {role.mention} role.')
            return

        # Add role with timeout handling
        try:
            async with asyncio.timeout(10):  # 10 second timeout
                await member.add_roles(role, reason=f"Added by {ctx.author} (ID: {ctx.author.id})")
                await ctx.send(f'✅ Successfully added {role.mention} to {member.mention}!')
                command_logger.info(f"addrole: SUCCESS - Role {role.name} (ID: {role.id}) added to member {member.name} (ID: {member.id}) in guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")
        except asyncio.TimeoutError:
            error_logger.error(f"addrole: TIMEOUT - Operation timed out for role {role.id} to member {member.id} in guild {ctx.guild.id}")
            await ctx.send('❌ The operation timed out. Please try again.')
            return

    except discord.Forbidden as e:
        error_logger.error(f"addrole: FORBIDDEN - Permission denied adding role {role.id} to member {member.id} in guild {ctx.guild.id}: {str(e)}")
        error_msg = '❌ I don\'t have permission to add roles. Make sure my role is above the role you\'re trying to add.'
        await ctx.send(error_msg)

    except discord.HTTPException as e:
        error_logger.error(f"addrole: HTTP_ERROR - Discord error {e.status} when adding role {role.id} to member {member.id} in guild {ctx.guild.id}: {e.text}")
        error_msg = f'❌ Failed to add role due to Discord error: {e.status} - {e.text}'
        await ctx.send(error_msg)

    except Exception as e:
        error_logger.error(f"addrole: UNEXPECTED_ERROR - Unexpected error when adding role {role.id} to member {member.id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send('❌ An unexpected error occurred. Please try again later.')

@bot.hybrid_command(name='removerole', description='Remove a role from a member', default_member_permissions=discord.Permissions(manage_guild=True))
async def removerole(ctx, member: discord.Member, role: discord.Role):
    try:
        # Log command execution start
        command_logger.info(f"removerole: Started - Target: {member} (ID: {member.id}), Role: {role.name} (ID: {role.id}), Guild: {ctx.guild.name} (ID: {ctx.guild.id})")

        # Only allow members with the configured manager role
        if not is_manager_member(ctx.author):
            permission_logger.warning(f"removerole: Permission denied - User {ctx.author} (ID: {ctx.author.id}) lacks Manager role in guild {ctx.guild.id}")
            await ctx.send("❌ You don't have permission to use this command. Required: Manager role.")
            return

        # Check if bot has manage roles permission
        if not ctx.guild.me.guild_permissions.manage_roles:
            permission_logger.error(f"removerole: Bot missing manage_roles permission in guild {ctx.guild.id}")
            await ctx.send('❌ I need the "Manage Roles" permission to execute this command.')
            return

        if role not in member.roles:
            command_logger.info(f"removerole: Role {role.id} not found on member {member.id} in guild {ctx.guild.id}")
            await ctx.send(f'❌ {member.mention} doesn\'t have the {role.mention} role.')
            return

        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            permission_logger.warning(f"removerole: Hierarchy violation - User {ctx.author.id} cannot remove role {role.id} (higher/equal to user's role) in guild {ctx.guild.id}")
            await ctx.send('❌ You cannot remove a role higher than or equal to your highest role.')
            return

        if role >= ctx.guild.me.top_role:
            permission_logger.error(f"removerole: Bot hierarchy insufficient - Cannot remove role {role.id} (higher/equal to bot's role) in guild {ctx.guild.id}")
            await ctx.send('❌ I cannot remove a role higher than or equal to my highest role.')
            return

        await member.remove_roles(role, reason=f"Removed by {ctx.author} (ID: {ctx.author.id})")
        await ctx.send(f'✅ Successfully removed {role.mention} from {member.mention}!')
        command_logger.info(f"removerole: SUCCESS - Role {role.name} (ID: {role.id}) removed from member {member.name} (ID: {member.id}) in guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    except discord.Forbidden as e:
        error_logger.error(f"removerole: FORBIDDEN - Permission denied removing role {role.id} from member {member.id} in guild {ctx.guild.id}: {str(e)}")
        await ctx.send('❌ I don\'t have permission to remove roles. Make sure my role is above the role you\'re trying to remove.')
    except discord.HTTPException as e:
        error_logger.error(f"removerole: HTTP_ERROR - Discord error when removing role {role.id} from member {member.id} in guild {ctx.guild.id}: {str(e)}")
        await ctx.send(f'❌ Failed to remove role. Error: {str(e)}')
    except Exception as e:
        error_logger.error(f"removerole: UNEXPECTED_ERROR - Unexpected error when removing role {role.id} from member {member.id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An unexpected error occurred: {str(e)}')

class RoleListView(discord.ui.View):
    def __init__(self, roles, guild_name, timeout=300):
        super().__init__(timeout=timeout)
        self.roles = roles
        self.guild_name = guild_name
        self.page = 0
        self.per_page = 25

    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        role_list = self.roles[start:end]
        description = '\n'.join([f'{role.mention} - {len(role.members)} members' for role in role_list])

        embed = discord.Embed(
            title=f'Roles in {self.guild_name}',
            description=description,
            color=discord.Color.blue()
        )

        total_pages = (len(self.roles) - 1) // self.per_page + 1
        embed.set_footer(text=f'Page {self.page + 1} of {total_pages} ({len(self.roles)} total roles)')

        return embed

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label='Next', style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        total_pages = (len(self.roles) - 1) // self.per_page + 1
        if self.page < total_pages - 1:
            self.page += 1
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

@bot.hybrid_command(name='listroles', description='List all roles in the server')
async def listroles(ctx):
    # Check if command is used in a guild
    if ctx.guild is None:
        await ctx.send('❌ This command can only be used in a server.')
        return
    
    command_logger.info(f"listroles: Started - Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    roles = [role for role in ctx.guild.roles if role.name != '@everyone']
    roles.reverse()

    if not roles:
        command_logger.info(f"listroles: No roles found in guild {ctx.guild.id}")
        await ctx.send('❌ No roles found in this server.')
        return

    view = RoleListView(roles, ctx.guild.name)
    embed = view.get_embed()

    await ctx.send(embed=embed, view=view)
    command_logger.info(f"listroles: SUCCESS - Listed {len(roles)} roles in guild {ctx.guild.name} (ID: {ctx.guild.id})")


@bot.hybrid_command(name='roleall', description='Add a role to all server members', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def roleall(ctx, role: discord.Role, confirm: bool = False):
    """Assign `role` to every non-bot member in the guild.

    Safety: by default the command will do a dry-run and report how many members would be affected.
    To actually run it, call with `confirm=True`.
    """
    command_logger.info(f"roleall: Started - Role: {role.name} (ID: {role.id}), Confirm: {confirm}, Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    # Check if user has manage roles permission
    if not ctx.author.guild_permissions.manage_roles:
        permission_logger.warning(f"roleall: Permission denied - User {ctx.author.id} lacks manage_roles permission in guild {ctx.guild.id}")
        await ctx.send("❌ You don't have permission to use this command. Required: Manage Roles permission.")
        return

    # Check role hierarchy
    if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        permission_logger.warning(f"roleall: Hierarchy violation - User {ctx.author.id} cannot assign role {role.id} (higher/equal to user's role) in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot assign a role higher than or equal to your highest role.')
        return

    if role >= ctx.guild.me.top_role:
        permission_logger.error(f"roleall: Bot hierarchy insufficient - Cannot assign role {role.id} (higher/equal to bot's role) in guild {ctx.guild.id}")
        await ctx.send('❌ I cannot assign a role higher than or equal to my highest role.')
        return

    # Get list of non-bot members who don't have the role
    members_to_add = [m for m in ctx.guild.members if not m.bot and role not in m.roles]

    if not members_to_add:
        command_logger.info(f"roleall: All non-bot members already have role {role.id} in guild {ctx.guild.id}")
        await ctx.send('✅ All non-bot members already have this role.')
        return

    # If not confirming, just show how many members would be affected
    if not confirm:
        command_logger.info(f"roleall: DRY_RUN - Would add role {role.id} to {len(members_to_add)} members in guild {ctx.guild.id}")
        await ctx.send(f'ℹ️ This would add {role.mention} to {len(members_to_add)} members.\n'
                      'Run the command again with `confirm=True` to execute.')
        return

    # Actually add the role
    success_count = 0
    failed_count = 0

    command_logger.info(f"roleall: EXECUTION_START - Adding role {role.id} to {len(members_to_add)} members in guild {ctx.guild.id}")
    progress_msg = await ctx.send(f'🔄 Adding {role.mention} to {len(members_to_add)} members...')

    try:
        for member in members_to_add:
            try:
                await member.add_roles(role)
                success_count += 1
            except Exception as e:
                failed_count += 1
                error_logger.warning(f"roleall: Failed to add role {role.id} to member {member.id} in guild {ctx.guild.id}: {str(e)}")

            # Update progress every 10 members
            if (success_count + failed_count) % 10 == 0:
                await progress_msg.edit(content=f'🔄 Progress: {success_count + failed_count}/{len(members_to_add)}')

    except Exception as e:
        error_logger.error(f"roleall: Unexpected error during bulk role assignment in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An error occurred: {str(e)}')
        return

    command_logger.info(f"roleall: SUCCESS - Added role {role.name} (ID: {role.id}) to {success_count} members, failed for {failed_count} members in guild {ctx.guild.name} (ID: {ctx.guild.id})")
    await ctx.send(f'✅ Operation complete!\n'
                   f'Successfully added role to {success_count} members.\n'
                   f'Failed for {failed_count} members.')

@bot.hybrid_command(name='kick', description='Kick a member', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def kick(ctx, member: discord.Member, *, reason: str = 'No reason provided'):
    command_logger.info(f"kick: Started - Target: {member} (ID: {member.id}), Reason: '{reason}', Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    if member == ctx.author:
        command_logger.warning(f"kick: Self-kick attempt blocked for user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot kick yourself.')
        return

    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        permission_logger.warning(f"kick: Hierarchy violation - User {ctx.author.id} cannot kick member {member.id} (higher/equal role) in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot kick a member with a role higher than or equal to yours.')
        return

    if member.top_role >= ctx.guild.me.top_role:
        permission_logger.error(f"kick: Bot hierarchy insufficient - Cannot kick member {member.id} (higher/equal to bot's role) in guild {ctx.guild.id}")
        await ctx.send('❌ I cannot kick a member with a role higher than or equal to mine.')
        return

    try:
        await member.kick(reason=f'{reason} | Kicked by {ctx.author}')
        embed = discord.Embed(
            title='Member Kicked',
            description=f'{member.mention} has been kicked.',
            color=discord.Color.orange()
        )
        embed.add_field(name='Reason', value=reason, inline=False)
        embed.add_field(name='Moderator', value=ctx.author.mention, inline=False)
        await ctx.send(embed=embed)
        command_logger.info(f"kick: SUCCESS - Member {member.name} (ID: {member.id}) kicked from guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id}) for reason: {reason}")
    except discord.Forbidden:
        error_logger.error(f"kick: FORBIDDEN - Permission denied kicking member {member.id} in guild {ctx.guild.id}")
        await ctx.send('❌ I don\'t have permission to kick members.')
    except Exception as e:
        error_logger.error(f"kick: UNEXPECTED_ERROR - Error kicking member {member.id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An error occurred: {str(e)}')

@kick.error
async def kick_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"kick_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"kick_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/kick <member> [reason]`')
    elif isinstance(error, commands.BadArgument):
        error_logger.warning(f"kick_error: Bad argument provided by user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Invalid member specified. Please mention a valid member.')
    elif isinstance(error, commands.BotMissingPermissions):
        permission_logger.error(f"kick_error: Bot missing permissions in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ I don\'t have permission to kick members. Please check my role permissions.')
    else:
        error_logger.error(f"kick_error: Unhandled error in guild {ctx.guild.id if ctx.guild else 'N/A'}: {type(error).__name__}: {str(error)}", exc_info=True)

@bot.hybrid_command(name='ban', description='Ban a member from the server', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def ban(ctx, member: discord.Member, *, reason: str = 'No reason provided'):
    command_logger.info(f"ban: Started - Target: {member} (ID: {member.id}), Reason: '{reason}', Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    if member == ctx.author:
        command_logger.warning(f"ban: Self-ban attempt blocked for user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot ban yourself.')
        return

    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        permission_logger.warning(f"ban: Hierarchy violation - User {ctx.author.id} cannot ban member {member.id} (higher/equal role) in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot ban a member with a role higher than or equal to yours.')
        return

    if member.top_role >= ctx.guild.me.top_role:
        permission_logger.error(f"ban: Bot hierarchy insufficient - Cannot ban member {member.id} (higher/equal to bot's role) in guild {ctx.guild.id}")
        await ctx.send('❌ I cannot ban a member with a role higher than or equal to mine.')
        return

    try:
        await member.ban(reason=f'{reason} | Banned by {ctx.author}')
        embed = discord.Embed(
            title='Member Banned',
            description=f'{member.mention} has been banned.',
            color=discord.Color.red()
        )
        embed.add_field(name='Reason', value=reason, inline=False)
        embed.add_field(name='Moderator', value=ctx.author.mention, inline=False)
        await ctx.send(embed=embed)
        command_logger.info(f"ban: SUCCESS - Member {member.name} (ID: {member.id}) banned from guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id}) for reason: {reason}")
    except discord.Forbidden:
        error_logger.error(f"ban: FORBIDDEN - Permission denied banning member {member.id} in guild {ctx.guild.id}")
        await ctx.send('❌ I don\'t have permission to ban members.')
    except Exception as e:
        error_logger.error(f"ban: UNEXPECTED_ERROR - Error banning member {member.id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An error occurred: {str(e)}')

@ban.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"ban_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"ban_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/ban <member> [reason]`')
    elif isinstance(error, commands.BadArgument):
        error_logger.warning(f"ban_error: Bad argument provided by user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Invalid member specified. Please mention a valid member.')
    elif isinstance(error, commands.BotMissingPermissions):
        permission_logger.error(f"ban_error: Bot missing permissions in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ I don\'t have permission to ban members. Please check my role permissions.')
    else:
        error_logger.error(f"ban_error: Unhandled error in guild {ctx.guild.id if ctx.guild else 'N/A'}: {type(error).__name__}: {str(error)}", exc_info=True)

@bot.hybrid_command(name='unban', description='Unban a user from the server', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def unban(ctx, user_id: str):
    command_logger.info(f"unban: Started - Target User ID: {user_id}, Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    try:
        user_id_int = int(user_id)
        user = await bot.fetch_user(user_id_int)
        await ctx.guild.unban(user)
        await ctx.send(f'✅ Successfully unbanned {user.mention}!')
        command_logger.info(f"unban: SUCCESS - User {user.name} (ID: {user.id}) unbanned from guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")
    except ValueError:
        error_logger.warning(f"unban: Invalid user ID '{user_id}' provided by user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ Invalid user ID. Please provide a valid numeric user ID.')
    except discord.NotFound:
        error_logger.warning(f"unban: User ID {user_id} not found or not banned in guild {ctx.guild.id}")
        await ctx.send('❌ User not found or not banned.')
    except discord.Forbidden:
        error_logger.error(f"unban: FORBIDDEN - Permission denied unbanning user {user_id} in guild {ctx.guild.id}")
        await ctx.send('❌ I don\'t have permission to unban members.')
    except Exception as e:
        error_logger.error(f"unban: UNEXPECTED_ERROR - Error unbanning user {user_id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An error occurred: {str(e)}')

@unban.error
async def unban_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"unban_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"unban_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/unban <user_id>`')

@bot.hybrid_command(name='mute', description='Timeout a member', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def mute(ctx, member: discord.Member, duration: int = 10, *, reason: str = 'No reason provided'):
    command_logger.info(f"mute: Started - Target: {member} (ID: {member.id}), Duration: {duration}min, Reason: '{reason}', Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    if member == ctx.author:
        command_logger.warning(f"mute: Self-mute attempt blocked for user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot mute yourself.')
        return

    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        permission_logger.warning(f"mute: Hierarchy violation - User {ctx.author.id} cannot mute member {member.id} (higher/equal role) in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot mute a member with a role higher than or equal to yours.')
        return

    if member.top_role >= ctx.guild.me.top_role:
        permission_logger.error(f"mute: Bot hierarchy insufficient - Cannot mute member {member.id} (higher/equal to bot's role) in guild {ctx.guild.id}")
        await ctx.send('❌ I cannot mute a member with a role higher than or equal to mine.')
        return

    try:
        until = discord.utils.utcnow() + timedelta(minutes=duration)
        await member.timeout(until, reason=f'{reason} | Muted by {ctx.author}')
        embed = discord.Embed(
            title='Member Muted',
            description=f'{member.mention} has been muted for {duration} minutes.',
            color=discord.Color.dark_gray()
        )
        embed.add_field(name='Reason', value=reason, inline=False)
        embed.add_field(name='Moderator', value=ctx.author.mention, inline=False)
        await ctx.send(embed=embed)
        command_logger.info(f"mute: SUCCESS - Member {member.name} (ID: {member.id}) muted for {duration} minutes in guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id}) for reason: {reason}")
    except discord.Forbidden:
        error_logger.error(f"mute: FORBIDDEN - Permission denied muting member {member.id} in guild {ctx.guild.id}")
        await ctx.send('❌ I don\'t have permission to timeout members.')
    except Exception as e:
        error_logger.error(f"mute: UNEXPECTED_ERROR - Error muting member {member.id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An error occurred: {str(e)}')

@mute.error
async def mute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"mute_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"mute_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/mute <member> [duration] [reason]`')

@bot.hybrid_command(name='unmute', description='Remove timeout from a member', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def unmute(ctx, member: discord.Member):
    command_logger.info(f"unmute: Started - Target: {member} (ID: {member.id}), Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    try:
        await member.timeout(None)
        await ctx.send(f'✅ Successfully unmuted {member.mention}!')
        command_logger.info(f"unmute: SUCCESS - Member {member.name} (ID: {member.id}) unmuted in guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")
    except discord.Forbidden:
        error_logger.error(f"unmute: FORBIDDEN - Permission denied unmuting member {member.id} in guild {ctx.guild.id}")
        await ctx.send('❌ I don\'t have permission to remove timeouts.')
    except Exception as e:
        error_logger.error(f"unmute: UNEXPECTED_ERROR - Error unmuting member {member.id} in guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send(f'❌ An error occurred: {str(e)}')

@unmute.error
async def unmute_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"unmute_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"unmute_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/unmute <member>`')

@bot.hybrid_command(name='warn', description='Warn a member with automatic punishment escalation', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def warn(ctx, member: discord.Member, *, reason: str = 'No reason provided'):
    command_logger.info(f"warn: Started - Target: {member} (ID: {member.id}), Reason: '{reason}', Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    if member == ctx.author:
        command_logger.warning(f"warn: Self-warn attempt blocked for user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot warn yourself.')
        return

    # Initialize warnings for guild and user if not exists
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    if guild_id not in warnings_data:
        warnings_data[guild_id] = {}
    if user_id not in warnings_data[guild_id]:
        warnings_data[guild_id][user_id] = 0

    # Increment warning count
    warnings_data[guild_id][user_id] += 1
    warning_count = warnings_data[guild_id][user_id]
    await save_warnings(warnings_data)

    embed = discord.Embed(
        title='Member Warned',
        description=f'{member.mention} has been warned.',
        color=discord.Color.yellow()
    )
    embed.add_field(name='Reason', value=reason, inline=False)
    embed.add_field(name='Warning Count', value=f'{warning_count}', inline=True)
    embed.add_field(name='Moderator', value=ctx.author.mention, inline=False)

    dm_sent = True
    try:
        await member.send(f'⚠️ You have been warned in {ctx.guild.name}.\n**Reason:** {reason}\n**Warning Count:** {warning_count}')
    except:
        embed.set_footer(text='Could not DM user')
        dm_sent = False

    await ctx.send(embed=embed)
    command_logger.info(f"warn: SUCCESS - Member {member.name} (ID: {member.id}) warned in guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id}) for reason: {reason}, DM sent: {dm_sent}, Count: {warning_count}")

    # Apply automatic punishments based on warning count
    if warning_count == 3:
        await apply_mute(ctx, member, 10, f"3 warnings reached | Original reason: {reason}")
    elif warning_count == 4:
        await apply_mute(ctx, member, 60, f"4 warnings reached | Original reason: {reason}")
    elif warning_count == 6:
        await apply_kick(ctx, member, f"6 warnings reached | Original reason: {reason}")
    elif warning_count > 6:
        await apply_ban(ctx, member, f"{warning_count} warnings reached | Original reason: {reason}")

@warn.error
async def warn_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"warn_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"warn_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/warn <member> [reason]`')

@bot.hybrid_command(name='clearwarns', description='Clear warnings from a member', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def clearwarns(ctx, member: discord.Member, amount: str = 'all'):
    command_logger.info(f"clearwarns: Started - Target: {member} (ID: {member.id}), Amount: '{amount}', Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    if member == ctx.author:
        command_logger.warning(f"clearwarns: Self-clear attempt blocked for user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ You cannot clear your own warnings.')
        return

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    if guild_id not in warnings_data or user_id not in warnings_data[guild_id]:
        await ctx.send(f'ℹ️ {member.mention} has no warnings in this server.')
        return

    current_warnings = warnings_data[guild_id][user_id]

    if amount.lower() == 'all':
        warnings_cleared = current_warnings
        warnings_data[guild_id][user_id] = 0
    else:
        try:
            warnings_to_clear = int(amount)
            if warnings_to_clear <= 0:
                await ctx.send('❌ Amount must be a positive number or "all".')
                return
            warnings_cleared = min(warnings_to_clear, current_warnings)
            warnings_data[guild_id][user_id] = max(0, current_warnings - warnings_to_clear)
        except ValueError:
            await ctx.send('❌ Amount must be a number or "all".')
            return

    await save_warnings(warnings_data)

    embed = discord.Embed(
        title='Warnings Cleared',
        description=f'Warnings cleared for {member.mention}.',
        color=discord.Color.green()
    )
    embed.add_field(name='Warnings Cleared', value=str(warnings_cleared), inline=True)
    embed.add_field(name='Remaining Warnings', value=str(warnings_data[guild_id][user_id]), inline=True)
    embed.add_field(name='Moderator', value=ctx.author.mention, inline=False)

    await ctx.send(embed=embed)
    command_logger.info(f"clearwarns: SUCCESS - Cleared {warnings_cleared} warnings from {member.name} (ID: {member.id}) in guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id}), Remaining: {warnings_data[guild_id][user_id]}")

@clearwarns.error
async def clearwarns_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"clearwarns_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"clearwarns_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/clearwarns <member> [amount]` (amount can be a number or "all")')

@bot.hybrid_command(name='purge', description='Delete multiple messages', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def purge(ctx, amount: int):
    command_logger.info(f"purge: Started - Amount: {amount}, Channel: {ctx.channel.name} (ID: {ctx.channel.id}), Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    if amount < 1:
        command_logger.warning(f"purge: Invalid amount {amount} provided by user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ Please specify a number greater than 0.')
        return

    if amount > 100:
        command_logger.warning(f"purge: Amount {amount} exceeds limit for user {ctx.author.id} in guild {ctx.guild.id}")
        await ctx.send('❌ You can only delete up to 100 messages at a time.')
        return

    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        actual_deleted = len(deleted) - 1  # Subtract the confirmation message
        msg = await ctx.send(f'✅ Successfully deleted {actual_deleted} messages.')
        await msg.delete(delay=5)
        command_logger.info(f"purge: SUCCESS - Deleted {actual_deleted} messages in channel {ctx.channel.name} (ID: {ctx.channel.id}) of guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")
    except discord.Forbidden:
        error_logger.error(f"purge: FORBIDDEN - Permission denied deleting messages in channel {ctx.channel.id} of guild {ctx.guild.id}")
        await ctx.send('❌ I don\'t have permission to delete messages. Please check my role permissions.')
    except discord.HTTPException as e:
        if e.code == 50034:
            error_logger.warning(f"purge: OLD_MESSAGES - Cannot delete messages older than 14 days in channel {ctx.channel.id} of guild {ctx.guild.id}")
            await ctx.send('❌ Cannot delete messages older than 14 days.')
        else:
            error_logger.error(f"purge: HTTP_ERROR - Discord error {e.status} when deleting messages in channel {ctx.channel.id} of guild {ctx.guild.id}: {e.text}")
            await ctx.send(f'❌ Failed to delete messages: {str(e)}')
    except Exception as e:
        error_logger.error(f"purge: UNEXPECTED_ERROR - Unexpected error when deleting messages in channel {ctx.channel.id} of guild {ctx.guild.id}: {str(e)}", exc_info=True)
        await ctx.send('❌ An unexpected error occurred while deleting messages.')

@purge.error
async def purge_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        permission_logger.warning(f"purge_error: Missing permissions for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ You need Administrator permission to use this command.')
    elif isinstance(error, commands.MissingRequiredArgument):
        error_logger.warning(f"purge_error: Missing required argument for user {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'N/A'}")
        await ctx.send('❌ Missing required argument. Usage: `/purge <amount>`')

@bot.hybrid_command(name='serverinfo', description='Display server information')
async def serverinfo(ctx):
    # Check if command is used in a guild
    if ctx.guild is None:
        await ctx.send('❌ This command can only be used in a server.')
        return
    
    command_logger.info(f"serverinfo: Requested for guild {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    guild = ctx.guild

    embed = discord.Embed(
        title=f'{guild.name} Server Information',
        color=discord.Color.blue()
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    owner_mention = guild.owner.mention if guild.owner else 'Unknown'
    embed.add_field(name='Owner', value=owner_mention, inline=True)
    embed.add_field(name='Server ID', value=guild.id, inline=True)
    embed.add_field(name='Created', value=guild.created_at.strftime('%B %d, %Y'), inline=True)
    embed.add_field(name='Members', value=guild.member_count, inline=True)
    embed.add_field(name='Roles', value=len(guild.roles), inline=True)
    embed.add_field(name='Channels', value=len(guild.channels), inline=True)

    await ctx.send(embed=embed)
    command_logger.info(f"serverinfo: SUCCESS - Displayed info for guild {ctx.guild.name} (ID: {ctx.guild.id}) with {guild.member_count} members, {len(guild.roles)} roles, {len(guild.channels)} channels")

@bot.hybrid_command(name='userinfo', description='Display user information')
async def userinfo(ctx, member: Optional[discord.Member] = None):
    # Check if command is used in a guild (required for member info)
    if ctx.guild is None:
        await ctx.send('❌ This command can only be used in a server.')
        return
    
    member = member or ctx.author
    target_is_self = member == ctx.author

    command_logger.info(f"userinfo: Requested for {'self' if target_is_self else 'other user'} - Target: {member} (ID: {member.id}), Guild: {ctx.guild.name} (ID: {ctx.guild.id}) by {ctx.author.name} (ID: {ctx.author.id})")

    embed = discord.Embed(
        title=f'{member} User Information',
        color=member.color
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name='Username', value=member.name, inline=True)
    embed.add_field(name='User ID', value=member.id, inline=True)
    embed.add_field(name='Nickname', value=member.nick or 'None', inline=True)
    embed.add_field(name='Account Created', value=member.created_at.strftime('%B %d, %Y'), inline=True)

    if member.joined_at:
        embed.add_field(name='Joined Server', value=member.joined_at.strftime('%B %d, %Y'), inline=True)
    else:
        embed.add_field(name='Joined Server', value='Unknown', inline=True)

    embed.add_field(name='Top Role', value=member.top_role.mention, inline=True)

    roles = [role.mention for role in member.roles if role.name != '@everyone']
    if roles:
        # Discord embed field value limit is 1024 characters
        # Join all roles and check if it fits in one field
        all_roles_text = ' '.join(roles)
        
        if len(all_roles_text) <= 1024:
            # All roles fit in one field
            embed.add_field(name=f'Roles [{len(roles)}]', value=all_roles_text, inline=False)
        else:
            # Need to split into multiple fields
            # Each field can hold up to 1024 characters
            role_text = ''
            field_num = 1
            for role_mention in roles:
                # Handle edge case: if a single role is too long, truncate it
                if len(role_mention) > 1024:
                    # If we have accumulated text, save it first
                    if role_text:
                        embed.add_field(
                            name=f'Roles [{len(roles)}] (Part {field_num})' if field_num == 1 else f'Roles (Part {field_num})',
                            value=role_text,
                            inline=False
                        )
                        role_text = ''
                        field_num += 1
                    # Add the truncated role in its own field
                    truncated_role = role_mention[:1021] + '...'
                    embed.add_field(
                        name=f'Roles [{len(roles)}] (Part {field_num})' if field_num == 1 else f'Roles (Part {field_num})',
                        value=truncated_role,
                        inline=False
                    )
                    field_num += 1
                    continue
                
                # Check if adding this role would exceed the limit
                test_text = role_text + (' ' if role_text else '') + role_mention
                if len(test_text) > 1024:
                    # Save current field and start a new one (only if role_text is not empty)
                    if role_text:
                        embed.add_field(
                            name=f'Roles [{len(roles)}] (Part {field_num})' if field_num == 1 else f'Roles (Part {field_num})',
                            value=role_text,
                            inline=False
                        )
                        field_num += 1
                    role_text = role_mention
                else:
                    role_text = test_text
            
            # Add the last field if there's remaining content
            if role_text:
                embed.add_field(
                    name=f'Roles [{len(roles)}] (Part {field_num})' if field_num == 1 else f'Roles (Part {field_num})',
                    value=role_text,
                    inline=False
                )
    else:
        embed.add_field(name='Roles [0]', value='No roles', inline=False)

    # Add warning count
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    warning_count = 0
    if guild_id in warnings_data and user_id in warnings_data[guild_id]:
        warning_count = warnings_data[guild_id][user_id]
    embed.add_field(name='Warnings', value=str(warning_count), inline=True)

    await ctx.send(embed=embed)
    command_logger.info(f"userinfo: SUCCESS - Displayed info for user {member.name} (ID: {member.id}) with {len(roles)} roles in guild {ctx.guild.name} (ID: {ctx.guild.id})")

@bot.hybrid_command(name='ping', description='Test if the bot is responding')
async def ping(ctx):
    """Simple ping command to test bot responsiveness."""
    latency = round(bot.latency * 1000)
    command_logger.info(f"ping: Requested by {ctx.author.name} (ID: {ctx.author.id}) in guild {ctx.guild.name if ctx.guild else 'DM'} (ID: {ctx.guild.id if ctx.guild else 'N/A'}) - Latency: {latency}ms")
    await ctx.send(f'🏓 Pong! Latency: {latency}ms')

@bot.command(name='work')
async def work_command(ctx):
    """Enable the bot - Owner only command."""
    global botEnabled
    
    # Check owner permission
    if not is_owner(ctx.author.id):
        await ctx.send('❌ You do not have permission to use this command.')
        command_logger.warning(f"work: Permission denied for {ctx.author.name} (ID: {ctx.author.id}), expected owner: {MAIN_OWNER_ID}")
        return
    
    # Enable the bot
    botEnabled = True
    
    # Save state to file
    save_bot_state({'enabled': True})
    
    await ctx.send('✅ **Bot is now ENABLED!** All commands are active.')
    command_logger.info(f"BOT STATUS: Bot enabled by {ctx.author.name} (ID: {ctx.author.id})")
    logger.info(f"Bot enabled by owner {ctx.author.name} (ID: {ctx.author.id}) - State persisted")

# Mark work command as owner-only
work_command.owner_only = True

@bot.command(name='stop')
async def stop_command(ctx):
    """Disable the bot - Owner only command."""
    global botEnabled
    
    # Check owner permission
    if not is_owner(ctx.author.id):
        await ctx.send('❌ You do not have permission to use this command.')
        command_logger.warning(f"stop: Permission denied for {ctx.author.name} (ID: {ctx.author.id}), expected owner: {MAIN_OWNER_ID}")
        return
    
    # Disable the bot
    botEnabled = False
    
    # Save state to file
    save_bot_state({'enabled': False})
    
    await ctx.send('🔴 **Bot is now DISABLED!** All commands are inactive except Swork.')
    command_logger.info(f"BOT STATUS: Bot disabled by {ctx.author.name} (ID: {ctx.author.id})")
    logger.info(f"Bot disabled by owner {ctx.author.name} (ID: {ctx.author.id}) - State persisted")

# Mark stop command as owner-only
stop_command.owner_only = True

@bot.hybrid_command(name='help', description='Display all available commands')
async def help_command(ctx):
    command_logger.info(f"help: Requested by {ctx.author.name} (ID: {ctx.author.id}) in guild {ctx.guild.name if ctx.guild else 'DM'} (ID: {ctx.guild.id if ctx.guild else 'N/A'})")

    # Get all commands, excluding owner-only commands
    all_commands = [cmd for cmd in bot.commands if not hasattr(cmd, 'owner_only') or not cmd.owner_only]
    all_hybrid_commands = [cmd for cmd in bot.tree.get_commands() if not hasattr(cmd, 'owner_only') or not cmd.owner_only]
    
    total_commands = len(all_commands) + len(all_hybrid_commands)

    embed = discord.Embed(
        title=f'Bot Commands ({total_commands} total)',
        description='Commands can be used with `/` (slash) or `S` (prefix)',
        color=discord.Color.blue()
    )

    embed.add_field(
        name='🎭 Role Management',
        value='`/addrole <member> <role>` - Add a role to a member\n'
              '`/removerole <member> <role>` - Remove a role from a member\n'
              '`/listroles` - List all server roles (with pagination)\n'
              '`/roleall <role> [confirm]` - Add a role to all non-bot members (dry-run by default)',
        inline=False
    )

    embed.add_field(
        name='🛡️ Moderation',
        value='`/kick <member> [reason]` - Kick a member\n'
              '`/ban <member> [reason]` - Ban a member\n'
              '`/unban <user_id>` - Unban a user\n'
              '`/mute <member> [duration] [reason]` - Mute a member\n'
              '`/unmute <member>` - Unmute a member\n'
              '`/warn <member> [reason]` - Warn a member (with automatic punishment escalation)\n'
              '`/clearwarns <member> [amount]` - Clear warnings from a member\n'
              '`/purge <amount>` - Delete messages',
        inline=False
    )

    embed.add_field(
        name='🛡️ Security',
        value='`/antinuke [action] [value]` - Configure anti-nuke protection\n'
              '`/antispam [action] [value]` - Configure anti-spam protection\n'
              '`/securitywhitelist [action] [role]` - Manage security whitelist',
        inline=False
    )

    embed.add_field(
        name='ℹ️ Information',
        value='`/serverinfo` - Display server information\n'
              '`/userinfo [member]` - Display user information\n'
              '`/ping` - Test bot responsiveness\n'
              '`/help` - Show this help message',
        inline=False
    )

    await ctx.send(embed=embed)

# Security event handlers
@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    """Track bans for anti-nuke."""
    if not security_settings.get('antinuke_enabled', True):
        return
    
    # Get the member who performed the ban (from audit log)
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                if isinstance(entry.user, discord.Member) and not is_whitelisted(entry.user):
                    action_count = track_user_action(guild.id, entry.user.id, 'ban')
                    if action_count >= security_settings.get('antinuke_kick_threshold', 3):
                        await handle_antinuke_violation(guild, entry.user, action_count)
                break
    except Exception as e:
        logger.debug(f"Could not track ban action: {e}")

@bot.event
async def on_member_remove(member: discord.Member):
    """Track member removals (kicks) for anti-nuke."""
    if not security_settings.get('antinuke_enabled', True):
        return
    
    try:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                if isinstance(entry.user, discord.Member) and not is_whitelisted(entry.user):
                    action_count = track_user_action(member.guild.id, entry.user.id, 'kick')
                    if action_count >= security_settings.get('antinuke_kick_threshold', 3):
                        await handle_antinuke_violation(member.guild, entry.user, action_count)
                break
    except Exception as e:
        logger.debug(f"Could not track kick action: {e}")

@bot.event
async def on_guild_role_delete(role: discord.Role):
    """Track role deletions for anti-nuke."""
    if not security_settings.get('antinuke_enabled', True):
        return
    
    try:
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if entry.target.id == role.id:
                if isinstance(entry.user, discord.Member) and not is_whitelisted(entry.user):
                    action_count = track_user_action(role.guild.id, entry.user.id, 'role_delete')
                    if action_count >= security_settings.get('antinuke_kick_threshold', 3):
                        await handle_antinuke_violation(role.guild, entry.user, action_count)
                break
    except Exception as e:
        logger.debug(f"Could not track role delete action: {e}")

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    """Track channel deletions for anti-nuke."""
    if not security_settings.get('antinuke_enabled', True):
        return
    
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.target.id == channel.id:
                if isinstance(entry.user, discord.Member) and not is_whitelisted(entry.user):
                    action_count = track_user_action(channel.guild.id, entry.user.id, 'channel_delete')
                    if action_count >= security_settings.get('antinuke_kick_threshold', 3):
                        await handle_antinuke_violation(channel.guild, entry.user, action_count)
                break
    except Exception as e:
        logger.debug(f"Could not track channel delete action: {e}")

@bot.event
async def on_bulk_message_delete(messages: List[discord.Message]):
    """Track bulk message deletions for anti-nuke."""
    if not security_settings.get('antinuke_enabled', True) or not messages:
        return
    
    guild = messages[0].guild
    if not guild:
        return
    
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.message_bulk_delete):
            if isinstance(entry.user, discord.Member) and not is_whitelisted(entry.user):
                action_count = track_user_action(guild.id, entry.user.id, 'bulk_delete')
                if action_count >= security_settings.get('antinuke_kick_threshold', 3):
                    await handle_antinuke_violation(guild, entry.user, action_count)
            break
    except Exception as e:
        logger.debug(f"Could not track bulk delete action: {e}")

# Security configuration commands
@bot.hybrid_command(name='antinuke', description='Configure anti-nuke protection settings', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def antinuke_config(ctx, action: str = None, value: str = None):
    """Configure anti-nuke protection."""
    if ctx.guild is None:
        await ctx.send('❌ This command can only be used in a server.')
        return
    
    if action is None:
        # Show current settings
        embed = discord.Embed(
            title='🛡️ Anti-Nuke Protection Settings',
            color=discord.Color.blue()
        )
        embed.add_field(name='Status', value='✅ Enabled' if security_settings.get('antinuke_enabled', True) else '❌ Disabled', inline=True)
        embed.add_field(name='Ban Threshold', value=f"{security_settings.get('antinuke_ban_threshold', 5)} actions", inline=True)
        embed.add_field(name='Kick Threshold', value=f"{security_settings.get('antinuke_kick_threshold', 3)} actions", inline=True)
        embed.add_field(name='Time Window', value=f"{security_settings.get('antinuke_time_window', 10)} seconds", inline=True)
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action == 'enable':
        security_settings['antinuke_enabled'] = True
        save_security_settings(security_settings)
        await ctx.send('✅ Anti-nuke protection enabled!')
    elif action == 'disable':
        security_settings['antinuke_enabled'] = False
        save_security_settings(security_settings)
        await ctx.send('❌ Anti-nuke protection disabled!')
    elif action == 'banthreshold' and value:
        try:
            threshold = int(value)
            if threshold < 1:
                await ctx.send('❌ Threshold must be at least 1.')
                return
            security_settings['antinuke_ban_threshold'] = threshold
            save_security_settings(security_settings)
            await ctx.send(f'✅ Ban threshold set to {threshold} actions.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    elif action == 'kickthreshold' and value:
        try:
            threshold = int(value)
            if threshold < 1:
                await ctx.send('❌ Threshold must be at least 1.')
                return
            security_settings['antinuke_kick_threshold'] = threshold
            save_security_settings(security_settings)
            await ctx.send(f'✅ Kick threshold set to {threshold} actions.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    elif action == 'timewindow' and value:
        try:
            window = int(value)
            if window < 1:
                await ctx.send('❌ Time window must be at least 1 second.')
                return
            security_settings['antinuke_time_window'] = window
            save_security_settings(security_settings)
            await ctx.send(f'✅ Time window set to {window} seconds.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    else:
        await ctx.send('❌ Invalid action. Use: `enable`, `disable`, `banthreshold <number>`, `kickthreshold <number>`, or `timewindow <seconds>`')

@bot.hybrid_command(name='antispam', description='Configure anti-spam protection settings', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def antispam_config(ctx, action: str = None, value: str = None):
    """Configure anti-spam protection."""
    if ctx.guild is None:
        await ctx.send('❌ This command can only be used in a server.')
        return
    
    if action is None:
        # Show current settings
        embed = discord.Embed(
            title='🚫 Anti-Spam Protection Settings',
            color=discord.Color.blue()
        )
        embed.add_field(name='Status', value='✅ Enabled' if security_settings.get('antispam_enabled', True) else '❌ Disabled', inline=True)
        embed.add_field(name='Message Limit', value=f"{security_settings.get('antispam_message_limit', 5)} per {security_settings.get('antispam_time_window', 5)}s", inline=True)
        embed.add_field(name='Mention Limit', value=f"{security_settings.get('antispam_mention_limit', 5)} per message", inline=True)
        embed.add_field(name='Duplicate Limit', value=f"{security_settings.get('antispam_duplicate_limit', 3)} messages", inline=True)
        embed.add_field(name='Action', value=security_settings.get('antispam_action', 'mute').title(), inline=True)
        embed.add_field(name='Mute Duration', value=f"{security_settings.get('antispam_mute_duration', 10)} minutes", inline=True)
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action == 'enable':
        security_settings['antispam_enabled'] = True
        save_security_settings(security_settings)
        await ctx.send('✅ Anti-spam protection enabled!')
    elif action == 'disable':
        security_settings['antispam_enabled'] = False
        save_security_settings(security_settings)
        await ctx.send('❌ Anti-spam protection disabled!')
    elif action == 'messagelimit' and value:
        try:
            limit = int(value)
            if limit < 1:
                await ctx.send('❌ Limit must be at least 1.')
                return
            security_settings['antispam_message_limit'] = limit
            save_security_settings(security_settings)
            await ctx.send(f'✅ Message limit set to {limit} messages.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    elif action == 'mentionlimit' and value:
        try:
            limit = int(value)
            if limit < 1:
                await ctx.send('❌ Limit must be at least 1.')
                return
            security_settings['antispam_mention_limit'] = limit
            save_security_settings(security_settings)
            await ctx.send(f'✅ Mention limit set to {limit} mentions.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    elif action == 'duplicatelimit' and value:
        try:
            limit = int(value)
            if limit < 1:
                await ctx.send('❌ Limit must be at least 1.')
                return
            security_settings['antispam_duplicate_limit'] = limit
            save_security_settings(security_settings)
            await ctx.send(f'✅ Duplicate limit set to {limit} messages.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    elif action == 'action' and value:
        value = value.lower()
        if value in ['mute', 'kick', 'ban']:
            security_settings['antispam_action'] = value
            save_security_settings(security_settings)
            await ctx.send(f'✅ Anti-spam action set to {value}.')
        else:
            await ctx.send('❌ Invalid action. Use: `mute`, `kick`, or `ban`')
    elif action == 'muteduration' and value:
        try:
            duration = int(value)
            if duration < 1:
                await ctx.send('❌ Duration must be at least 1 minute.')
                return
            security_settings['antispam_mute_duration'] = duration
            save_security_settings(security_settings)
            await ctx.send(f'✅ Mute duration set to {duration} minutes.')
        except ValueError:
            await ctx.send('❌ Invalid number. Please provide a valid integer.')
    else:
        await ctx.send('❌ Invalid action. Use: `enable`, `disable`, `messagelimit <number>`, `mentionlimit <number>`, `duplicatelimit <number>`, `action <mute/kick/ban>`, or `muteduration <minutes>`')

@bot.hybrid_command(name='securitywhitelist', description='Manage security whitelist (roles exempt from protection)', default_member_permissions=discord.Permissions(administrator=True))
@commands.has_permissions(administrator=True)
async def security_whitelist(ctx, action: str = None, role: discord.Role = None):
    """Manage security whitelist."""
    if ctx.guild is None:
        await ctx.send('❌ This command can only be used in a server.')
        return
    
    if action is None:
        whitelisted = security_settings.get('whitelisted_roles', [])
        if not whitelisted:
            await ctx.send('📋 No roles are whitelisted.')
        else:
            roles_list = []
            for role_id in whitelisted:
                role_obj = ctx.guild.get_role(int(role_id))
                if role_obj:
                    roles_list.append(role_obj.mention)
            if roles_list:
                await ctx.send(f'📋 Whitelisted roles: {", ".join(roles_list)}')
            else:
                await ctx.send('📋 Whitelisted role IDs: {", ".join(whitelisted)}')
        return
    
    action = action.lower()
    
    if action == 'add' and role:
        whitelisted = security_settings.get('whitelisted_roles', [])
        if str(role.id) not in whitelisted:
            whitelisted.append(str(role.id))
            security_settings['whitelisted_roles'] = whitelisted
            await save_security_settings(security_settings)
            await ctx.send(f'✅ Added {role.mention} to security whitelist.')
        else:
            await ctx.send(f'❌ {role.mention} is already whitelisted.')
    elif action == 'remove' and role:
        whitelisted = security_settings.get('whitelisted_roles', [])
        if str(role.id) in whitelisted:
            whitelisted.remove(str(role.id))
            security_settings['whitelisted_roles'] = whitelisted
            await save_security_settings(security_settings)
            await ctx.send(f'✅ Removed {role.mention} from security whitelist.')
        else:
            await ctx.send(f'❌ {role.mention} is not whitelisted.')
    else:
        await ctx.send('❌ Invalid action. Use: `add <role>` or `remove <role>`')

async def restart_bot():
    """Restart the bot gracefully."""
    logger.info("Restarting bot...")
    try:
        # Close the bot session cleanly
        if not bot.is_closed():
            await bot.close()
        # Wait a moment for cleanup
        await asyncio.sleep(2)
    except Exception as e:
        logger.warning(f"Error during bot close: {e}")
    # Restart the process
    os.execv(sys.executable, ['python'] + sys.argv)

if __name__ == '__main__':
    import sys
    import os
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('bot.log')
        ]
    )
    
    # Start webserver
    webserver_thread = keep_alive()
    if not webserver_thread:
        logger.error("Failed to start webserver")
        sys.exit(1)
    
    try:
        from config import TOKEN
    except ImportError:
        print("ERROR: config.py file not found or TOKEN variable not defined!")
        sys.exit(1)

    if not TOKEN or TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print('ERROR: Please add your bot token in config.py!')
        print('\nTo set up your Discord bot:')
        print('1. Go to https://discord.com/developers/applications')
        print('2. Create a new application or select an existing one')
        print('3. Go to the "Bot" section')
        print('4. Enable these Privileged Gateway Intents:')
        print('   - MESSAGE CONTENT INTENT')
        print('   - SERVER MEMBERS INTENT')
        print('5. Click "Reset Token" to get your bot token')
        print('6. Open config.py and replace YOUR_BOT_TOKEN_HERE with your actual token')
        print('\nTo invite the bot to your server:')
        print('7. Go to OAuth2 > URL Generator')
        print('8. Select scopes: bot, applications.commands')
        print('9. Select permissions: Administrator (or specific permissions)')
        print('10. Copy and visit the generated URL to invite the bot')
        sys.exit(1)

    # Use centralized error handling for bot
    def emergency_save():
        save_warnings_sync(warnings_data)

    run_bot_with_error_handling(bot, TOKEN, on_shutdown=emergency_save)