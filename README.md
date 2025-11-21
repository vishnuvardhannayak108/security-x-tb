# SECURITY X TB

SECURITY X TB is a powerful and comprehensive Discord bot designed for advanced role management, server moderation, and automated security. It features a robust warning system, anti-nuke protection, and detailed logging to keep your server safe and organized.

## 🚀 Features

### 🛡️ Security & Moderation
*   **Anti-Nuke System**: Automatically detects and bans/kicks users performing suspicious mass actions (e.g., rapid bans/kicks).
*   **Anti-Spam Protection**: Prevents spam by monitoring message rates, duplicate messages, and excessive mentions.
*   **Warning System**: 
    *   Warn users with reasons.
    *   **Auto-Punishments**: Automatically mutes, kicks, or bans users based on warning thresholds (e.g., 3 warnings = mute).
    *   Clear warnings for specific users.
*   **Moderation Commands**: Kick, Ban, Unban, Mute (Timeout), Unmute, Purge messages.

### 🎭 Role Management
*   **Add/Remove Roles**: Easily assign or remove roles from members.
*   **Bulk Role Assignment**: Add a specific role to **all** non-bot members in the server (with dry-run safety check).
*   **Role Listing**: View all roles in the server with member counts in a paginated view.

### 📊 Logging & Information
*   **Comprehensive Logging**: detailed logs for commands, errors, and security events saved to `bot.log`.
*   **Security Alerts**: Real-time alerts sent to a configured log channel.
*   **Server & User Info**: Display detailed information about the server or specific users.
*   **Bot Health**: Built-in heartbeat monitoring and auto-restart capabilities.

### ⚙️ Control
*   **Owner Commands**: Special `!work` and `!stop` commands to globally enable or disable the bot.
*   **Hybrid Commands**: Supports both Prefix (`S`) and Slash Commands (`/`).

## 📋 Prerequisites

*   Python 3.8 or higher
*   A Discord Bot Token (with `Message Content`, `Server Members`, and `Presence` intents enabled)

## 🛠️ Installation

1.  **Clone the repository**
    ```bash
    git clone https://github.com/yourusername/SECURITY-X-TB.git
    cd SECURITY-X-TB
    ```

2.  **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configuration**
    You can configure the bot using environment variables or by editing `config.py`.

    *   **Environment Variables** (Recommended):
        *   `DISCORD_BOT_TOKEN`: Your Discord Bot Token.
        *   `MAIN_OWNER_ID`: Your Discord User ID (for owner-only commands).
    
    *   **Config File** (`config.py`):
        *   Update `MANAGER_ROLE_NAME` to the name of the role that can manage roles (default: 'Manager').
        *   Alternatively, set `MANAGER_ROLE_IDS` to a list of Role IDs.

4.  **Run the Bot**
    ```bash
    python bot.py
    ```

## 📖 Usage

### Owner Commands (Prefix only)
*   `Swork`: Enable the bot (starts in disabled state).
*   `Sstop`: Disable the bot.

### Slash Commands
*   `/help`: Show all available commands.
*   `/warn <member> <reason>`: Warn a user.
*   `/mute <member> <duration> <reason>`: Timeout a user.
*   `/kick <member> <reason>`: Kick a user.
*   `/ban <member> <reason>`: Ban a user.
*   `/addrole <member> <role>`: Add a role.
*   `/roleall <role>`: Add role to everyone.
*   `/serverinfo`: Show server stats.

## 🔒 Security Settings
Security settings (Anti-nuke/Anti-spam) are stored in `security_settings.json`. The bot will generate this file with default values on first run. You can customize thresholds for bans, kicks, and spam detection limits in this file.

## 📝 License
This project is open source and available under the [MIT License](LICENSE).
