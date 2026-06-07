import discord
from discord.ext import commands
from discord import app_commands
from utils.database import db


class LookSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="look_setup", description="Configure which channels allow /look_submit")
    @app_commands.describe(
        action="Add, remove, or list allowlisted channels",
        channel="Channel to add or remove (not needed for list)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add channel", value="add"),
        app_commands.Choice(name="Remove channel", value="remove"),
        app_commands.Choice(name="List channels", value="list"),
    ])
    async def look_setup(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: discord.abc.GuildChannel = None,
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to configure look channels.",
                ephemeral=True,
            )
            return

        if action.value in ("add", "remove") and channel is None:
            await interaction.response.send_message(
                "❌ Please specify a channel for this action.",
                ephemeral=True,
            )
            return

        if action.value == "list":
            allowed_ids = await db.get_allowed_channels(interaction.guild.id)
            if not allowed_ids:
                await interaction.response.send_message(
                    "No channels are configured yet. Use `/look_setup` with **Add channel** to enable one.",
                    ephemeral=True,
                )
                return

            lines = []
            for channel_id in allowed_ids:
                ch = interaction.guild.get_channel(channel_id)
                label = ch.mention if ch else f"`{channel_id}` (deleted or inaccessible)"
                lines.append(f"• {label}")

            embed = discord.Embed(
                title="Look submission channels",
                description="\n".join(lines),
                color=discord.Color.blue(),
            )
            embed.set_footer(text="Users can run /look_submit in these channels.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not isinstance(channel, discord.TextChannel | discord.Thread):
            await interaction.response.send_message(
                "❌ Only text channels and threads can be allowlisted.",
                ephemeral=True,
            )
            return

        channel_id = channel.id if isinstance(channel, discord.TextChannel) else channel.parent_id
        if channel_id is None:
            await interaction.response.send_message(
                "❌ Could not resolve the parent channel for this thread.",
                ephemeral=True,
            )
            return

        if action.value == "add":
            await db.add_allowed_channel(interaction.guild.id, channel_id, interaction.user.id)
            await interaction.response.send_message(
                f"✅ {channel.mention} is now enabled for `/look_submit`.",
                ephemeral=True,
            )
            return

        removed = await db.remove_allowed_channel(interaction.guild.id, channel_id)
        if removed:
            await interaction.response.send_message(
                f"✅ {channel.mention} was removed from the allowlist.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ {channel.mention} is not on the allowlist.",
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(LookSetup(bot))
