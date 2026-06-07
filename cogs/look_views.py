import discord
from discord.ext import commands
from utils.database import db
from utils.embeds import create_look_embed


class EditTagsSelect(discord.ui.Select):
    """Multi-select dropdown for workspace tags."""

    def __init__(self, look_id: int, tags: list, current_tag_ids: set):
        current_ids = {str(tid) for tid in current_tag_ids}
        options = [
            discord.SelectOption(
                label=f"#{tag['tag_name']}",
                value=str(tag['tag_id']),
                default=str(tag['tag_id']) in current_ids,
            )
            for tag in tags[:25]
        ]

        super().__init__(
            placeholder="Select tags for this look...",
            min_values=0,
            max_values=min(len(options), 25),
            options=options,
            custom_id=f"look_tags_select:{look_id}",
        )
        self.look_id = look_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()


class EditTagsView(discord.ui.View):
    """Ephemeral tag editor with Save and Cancel."""

    def __init__(self, look_id: int, tags: list, current_tag_ids: set):
        super().__init__(timeout=120)
        self.look_id = look_id
        self.add_item(EditTagsSelect(look_id, tags, current_tag_ids))

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        look = await db.get_look(self.look_id)
        if not look or not look['bot_message_id']:
            await interaction.followup.send("❌ This look no longer exists.", ephemeral=True)
            return

        select = next((item for item in self.children if isinstance(item, EditTagsSelect)), None)
        selected_ids = [int(v) for v in (select.values if select else [])]

        try:
            await db.set_look_tags(self.look_id, selected_ids, interaction.user.id)
        except Exception as e:
            print(f"❌ Error saving look tags: {e}")
            await interaction.followup.send("❌ Failed to save tags. Please try again.", ephemeral=True)
            return

        tag_rows = await db.get_look_tag_names(self.look_id)
        look = await db.get_look(self.look_id)
        embed = create_look_embed(look, tag_rows, interaction.guild.id)

        try:
            channel = interaction.guild.get_channel(look['channel_id'])
            if not channel:
                channel = await interaction.guild.fetch_channel(look['channel_id'])
            look_message = await channel.fetch_message(look['bot_message_id'])
            await look_message.edit(embed=embed)
        except discord.NotFound:
            await interaction.followup.send(
                "✅ Tags saved, but the look message was deleted.",
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "✅ Tags saved, but I couldn't update the look embed (missing permissions).",
                ephemeral=True,
            )
            return

        tag_label = ", ".join(f"`#{t['tag_name']}`" for t in tag_rows) or "_none_"
        await interaction.followup.send(f"✅ Tags updated: {tag_label}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.gray)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        self.stop()


class LookManageView(discord.ui.View):
    """Persistent view attached to look posts."""

    def __init__(self, look_id: int):
        super().__init__(timeout=None)
        self.look_id = look_id

        button = discord.ui.Button(
            label="Edit Tags",
            style=discord.ButtonStyle.secondary,
            custom_id=f"look_edit:{look_id}",
        )
        button.callback = self.edit_tags_callback
        self.add_item(button)

    async def edit_tags_callback(self, interaction: discord.Interaction):
        look = await db.get_look(self.look_id)
        if not look or not look['bot_message_id']:
            await interaction.response.send_message(
                "❌ This look no longer exists.",
                ephemeral=True,
            )
            return

        tags = await db.get_tags(interaction.guild.id)
        if not tags:
            await interaction.response.send_message(
                "❌ No tags exist yet. An admin can create one with `/tag_create`.",
                ephemeral=True,
            )
            return

        current = await db.get_look_tag_names(self.look_id)
        current_ids = {row['tag_id'] for row in current}
        view = EditTagsView(self.look_id, tags, current_ids)
        await interaction.response.send_message(
            "Select tags for this look, then click **Save**.",
            view=view,
            ephemeral=True,
        )


class LookViews(commands.Cog):
    """Registers persistent look views on startup."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            looks = await db.get_all_looks(guild.id)
            for row in looks:
                self.bot.add_view(LookManageView(row['look_id']))
        print("✅ Registered persistent look views")


async def setup(bot):
    await bot.add_cog(LookViews(bot))
