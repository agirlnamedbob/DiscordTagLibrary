import discord
from discord.ext import commands
from utils.database import db
from utils.embeds import create_look_embed


import math

class PaginatedEditTagsSelect(discord.ui.Select):
    """Dropdown for a specific page of tags."""

    def __init__(self, look_id: int, page_tags: list, current_tag_ids: set, category: str, page: int):
        options = []
        for tag in page_tags:
            options.append(discord.SelectOption(
                label=f"#{tag['tag_name']}",
                value=str(tag['tag_id']),
                default=str(tag['tag_id']) in current_tag_ids,
            ))

        super().__init__(
            placeholder=f"Select {category} tags (Page {page + 1})...",
            min_values=0,
            max_values=min(len(options), 25) if options else 1,
            options=options if options else [discord.SelectOption(label="No tags in this category", value="none")],
            custom_id=f"look_tags_select:{look_id}:{category}:{page}",
            disabled=not options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()


class PaginatedTagsView(discord.ui.View):
    """Paginated tag editor with Category and Page switching."""

    def __init__(self, look_id: int, all_tags: list, current_tag_ids: set):
        super().__init__(timeout=180)
        self.look_id = look_id
        self.all_tags = all_tags
        self.current_tag_ids = {str(tid) for tid in current_tag_ids}
        self.category = "Style"
        self.page = 0
        self.update_components()

    def sync_selections(self):
        select = next((item for item in self.children if isinstance(item, PaginatedEditTagsSelect)), None)
        if select and not select.disabled:
            page_option_ids = {opt.value for opt in select.options if opt.value != "none"}
            selected_ids = set(select.values) if "none" not in select.values else set()
            self.current_tag_ids -= page_option_ids
            self.current_tag_ids |= selected_ids

    def make_category_callback(self, cat):
        async def callback(interaction: discord.Interaction):
            self.sync_selections()
            self.category = cat
            self.page = 0
            self.update_components()
            await interaction.response.edit_message(view=self)
        return callback

    async def prev_page(self, interaction: discord.Interaction):
        self.sync_selections()
        self.page -= 1
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.sync_selections()
        self.page += 1
        self.update_components()
        await interaction.response.edit_message(view=self)

    def update_components(self):
        self.clear_items()

        cat_tags = [t for t in self.all_tags if t.get('category', 'Custom') == self.category]
        total_pages = max(1, math.ceil(len(cat_tags) / 25))
        if self.page >= total_pages:
            self.page = total_pages - 1
            
        start_idx = self.page * 25
        page_tags = cat_tags[start_idx:start_idx + 25]

        self.add_item(PaginatedEditTagsSelect(self.look_id, page_tags, self.current_tag_ids, self.category, self.page))

        categories = ["Style", "Tag", "Custom"]
        for cat in categories:
            btn = discord.ui.Button(
                label=cat, 
                style=discord.ButtonStyle.primary if cat == self.category else discord.ButtonStyle.secondary,
                custom_id=f"cat_btn:{cat}",
                row=1
            )
            btn.callback = self.make_category_callback(cat)
            self.add_item(btn)

        prev_btn = discord.ui.Button(label="⬅️ Prev", style=discord.ButtonStyle.secondary, disabled=(self.page == 0), row=2)
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)
        
        next_btn = discord.ui.Button(label="Next ➡️", style=discord.ButtonStyle.secondary, disabled=(self.page >= total_pages - 1), row=2)
        next_btn.callback = self.next_page
        self.add_item(next_btn)

        save_btn = discord.ui.Button(label="Save Tags", style=discord.ButtonStyle.success, row=3)
        save_btn.callback = self.save
        self.add_item(save_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
        cancel_btn.callback = self.cancel
        self.add_item(cancel_btn)

    async def save(self, interaction: discord.Interaction):
        self.sync_selections()
        await interaction.response.defer(ephemeral=True)

        look = await db.get_look(self.look_id)
        if not look or not look['bot_message_id']:
            await interaction.followup.send("❌ This look no longer exists.", ephemeral=True)
            return

        selected_ids = [int(v) for v in self.current_tag_ids]

        try:
            await db.set_look_tags(self.look_id, selected_ids, interaction.user.id)
        except Exception as e:
            print(f"❌ Error saving look tags: {e}")
            await interaction.followup.send("❌ Failed to save tags. Please try again.", ephemeral=True)
            return

        tag_rows = await db.get_look_tag_names(self.look_id)
        look = await db.get_look(self.look_id)

        try:
            channel = interaction.guild.get_channel(look['channel_id'])
            if not channel:
                channel = await interaction.guild.fetch_channel(look['channel_id'])
            look_message = await channel.fetch_message(look['bot_message_id'])
            
            filename = look_message.attachments[0].filename if look_message.attachments else None
            embed = create_look_embed(look, tag_rows, interaction.guild.id, attachment_filename=filename)
                
            await look_message.edit(embed=embed, attachments=look_message.attachments)
        except discord.NotFound:
            await interaction.followup.send("✅ Tags saved, but the look message was deleted.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send("✅ Tags saved, but I couldn't update the look embed (missing permissions).", ephemeral=True)
            return

        tag_label = ", ".join(f"`#{t['tag_name']}`" for t in tag_rows) or "_none_"
        await interaction.followup.send(f"✅ Tags updated: {tag_label}", ephemeral=True)
        self.stop()

    async def cancel(self, interaction: discord.Interaction):
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

        try:
            filename = interaction.message.attachments[0].filename if interaction.message.attachments else None
            embed = create_look_embed(look, tag_rows, interaction.guild.id, attachment_filename=filename)
                
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
        view = PaginatedTagsView(self.look_id, tags, current_ids)
        await interaction.response.send_message(
            "Use the buttons to switch categories and pages. Click **Save Tags** when done.",
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
