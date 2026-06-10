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
            await look_message.edit(embed=embed, attachments=look_message.attachments)
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


class EditTitleModal(discord.ui.Modal, title="Edit Competition Name"):
    comp_name_input = discord.ui.TextInput(
        label="Competition Name",
        placeholder="Enter competition name...",
        min_length=1,
        max_length=100,
        required=True,
    )

    def __init__(self, look_id: int, current_name: str):
        super().__init__()
        self.look_id = look_id
        self.comp_name_input.default = current_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_name = self.comp_name_input.value.strip()
        if not new_name:
            await interaction.followup.send("❌ Name cannot be empty.", ephemeral=True)
            return

        try:
            await db.update_look_name(self.look_id, new_name)
        except Exception as e:
            print(f"❌ Error updating look title: {e}")
            await interaction.followup.send("❌ Failed to update title. Please try again.", ephemeral=True)
            return

        look = await db.get_look(self.look_id)
        tag_rows = await db.get_look_tag_names(self.look_id)
        embed = create_look_embed(look, tag_rows, interaction.guild.id)

        try:
            # Edit the message with the updated embed title
            await interaction.message.edit(embed=embed, attachments=interaction.message.attachments)
            await interaction.followup.send("✅ Title updated!", ephemeral=True)
        except Exception as e:
            print(f"❌ Error editing look message: {e}")
            await interaction.followup.send("✅ Title updated in database, but look message could not be edited.", ephemeral=True)


class LookManageView(discord.ui.View):
    """Persistent view attached to look posts."""

    def __init__(self, look_id: int):
        super().__init__(timeout=None)
        self.look_id = look_id

        # Edit Title button
        title_btn = discord.ui.Button(
            label="Edit Title",
            style=discord.ButtonStyle.secondary,
            custom_id=f"look_edit_title:{look_id}",
        )
        title_btn.callback = self.edit_title_callback
        self.add_item(title_btn)

        # Edit Tags button (retains custom_id for backward compatibility)
        tags_btn = discord.ui.Button(
            label="Edit Tags",
            style=discord.ButtonStyle.secondary,
            custom_id=f"look_edit:{look_id}",
        )
        tags_btn.callback = self.edit_tags_callback
        self.add_item(tags_btn)

    async def edit_title_callback(self, interaction: discord.Interaction):
        look = await db.get_look(self.look_id)
        if not look or not look['bot_message_id']:
            await interaction.response.send_message(
                "❌ This look no longer exists.",
                ephemeral=True,
            )
            return

        current_name = look['comp_name'] or ""
        modal = EditTitleModal(self.look_id, current_name)
        await interaction.response.send_modal(modal)

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
        self.views_loaded = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self.views_loaded:
            return
        for guild in self.bot.guilds:
            looks = await db.get_all_looks(guild.id)
            for row in looks:
                self.bot.add_view(LookManageView(row['look_id']))
        self.views_loaded = True
        print("✅ Registered persistent look views")


async def setup(bot):
    await bot.add_cog(LookViews(bot))
