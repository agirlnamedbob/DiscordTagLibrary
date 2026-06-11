import discord
from discord.ext import commands
from discord import app_commands
from io import BytesIO
from utils.database import db
from utils.embeds import create_look_embed
from cogs.look_views import LookManageView
from utils.helpers import parse_tag_string


def is_image_attachment(attachment: discord.Attachment) -> bool:
    return attachment.content_type and attachment.content_type.startswith("image/")


def get_parent_channel_id(channel: discord.abc.GuildChannel) -> int | None:
    """Return parent text channel ID when submitting from a thread."""
    if isinstance(channel, discord.Thread):
        return channel.parent_id
    return None


async def post_look_message(
    bot,
    channel: discord.abc.Messageable,
    guild: discord.Guild,
    look_id: int,
    image_bytes: bytes,
    filename: str,
):
    """Post a look embed publicly in the given channel."""
    # Sanitize filename to avoid space mismatch during discord upload/embed matching
    filename = filename.replace(" ", "_")

    look = await db.get_look(look_id)
    tag_rows = await db.get_look_tag_names(look_id)
    embed = create_look_embed(look, tag_rows, guild.id, attachment_filename=filename)

    file = discord.File(fp=BytesIO(image_bytes), filename=filename)
    view = LookManageView(look_id)
    bot.add_view(view)

    message = await channel.send(embed=embed, file=file, view=view)

    await db.update_look_message_id(look_id, message.id)

    return message


class LookSubmit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _submit_look(
        self,
        channel: discord.abc.Messageable,
        guild: discord.Guild,
        channel_id: int,
        parent_channel_id: int | None,
        user_id: int,
        image_bytes: bytes,
        filename: str,
        comp_name: str | None,
        tag_names: list[str],
    ) -> tuple[discord.Message | None, str | None]:
        """Core ingestion logic: post publicly in the invoke channel."""
        if not await db.is_channel_allowed(guild.id, channel_id, parent_channel_id):
            return None, (
                "❌ This channel isn't enabled for look submissions. "
                "Ask an admin to run `/look_setup`."
            )

        if len(tag_names) > 25:
            return None, "❌ You can attach at most 25 tags."

        tag_ids, missing = await db.resolve_tag_names(guild.id, tag_names)
        if missing:
            return None, f"❌ Unknown tags: {', '.join(f'`#{n}`' for n in missing)}"

        look_id = await db.create_look(
            server_id=guild.id,
            channel_id=channel_id,
            comp_name=comp_name,
            submitted_by=user_id,
        )

        try:
            message = await post_look_message(
                self.bot,
                channel,
                guild,
                look_id,
                image_bytes,
                filename,
            )
        except discord.Forbidden:
            await db.delete_look(look_id)
            return None, "❌ I don't have permission to post in this channel."
        except Exception as e:
            print(f"❌ Look post failed: {e}")
            await db.delete_look(look_id)
            return None, "❌ Failed to post your look. Please try again."

        if tag_ids:
            await db.add_look_tags(look_id, tag_ids, user_id)
            look = await db.get_look(look_id)
            tag_rows = await db.get_look_tag_names(look_id)
            
            filename = message.attachments[0].filename if message.attachments else None
            embed = create_look_embed(look, tag_rows, guild.id, attachment_filename=filename)
            await message.edit(embed=embed, attachments=message.attachments, view=LookManageView(look_id))

        return message, None

    @app_commands.command(name="look_submit", description="Submit a look to the lookbook")
    @app_commands.describe(
        image="Image attachment for your look",
        comp_name="Name of the competition/look (e.g. Winter Wonderland)"
    )
    async def look_submit(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment,
        comp_name: str,
    ):
        if not is_image_attachment(image):
            await interaction.response.send_message(
                "❌ Please attach an image file.",
                ephemeral=True,
            )
            return

        if image.size > 8 * 1024 * 1024:
            await interaction.response.send_message(
                "❌ Image must be 8 MB or smaller.",
                ephemeral=True,
            )
            return

        parent_channel_id = get_parent_channel_id(interaction.channel)

        if not await db.is_channel_allowed(
            interaction.guild.id,
            interaction.channel.id,
            parent_channel_id,
        ):
            await interaction.response.send_message(
                "❌ This channel isn't enabled for look submissions. "
                "Ask an admin to run `/look_setup`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        image_bytes = await image.read()

        _, error = await self._submit_look(
            interaction.channel,
            interaction.guild,
            interaction.channel.id,
            parent_channel_id,
            interaction.user.id,
            image_bytes,
            image.filename,
            comp_name,
            [],
        )

        if error:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.followup.send("✅ Look submitted successfully!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(LookSubmit(bot))
