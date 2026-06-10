import math
import discord
from discord.ext import commands
from discord import app_commands
from utils.database import db
from utils.embeds import create_tag_list_embed, create_search_results_embed, create_search_gallery_embed
from utils.helpers import parse_tag_string


class GalleryPaginationView(discord.ui.View):
    """Interactive buttons to navigate search result gallery pages (1 look per page)"""

    def __init__(self, author_id, tag_names, server_id, guild_id, current_page, total_pages, mode):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.tag_names = tag_names
        self.server_id = server_id
        self.guild_id = guild_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.mode = mode
        self.update_buttons()

    def update_buttons(self):
        self.prev_page.disabled = (self.current_page <= 1)
        self.next_page.disabled = (self.current_page >= self.total_pages)

    async def refresh_view(self, interaction: discord.Interaction):
        limit = 5
        offset = (self.current_page - 1) * limit

        looks, total_count, _ = await db.search_looks(
            self.server_id, self.tag_names, mode=self.mode, limit=limit, offset=offset
        )
        self.total_pages = math.ceil(total_count / limit) if total_count > 0 else 1
        self.update_buttons()

        if looks:
            embed = create_search_results_embed(
                self.tag_names, looks, self.current_page, self.total_pages, total_count, guild_id=self.guild_id, mode=self.mode
            )
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You didn't start this search!", ephemeral=True)
            return

        self.current_page -= 1
        await self.refresh_view(interaction)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You didn't start this search!", ephemeral=True)
            return

        self.current_page += 1
        await self.refresh_view(interaction)


class TagListSearchDropdown(discord.ui.Select):
    def __init__(self, tags: list):
        options = []
        for tag in tags[:25]:  # Discord select menu limit is 25
            options.append(discord.SelectOption(
                label=f"#{tag['tag_name']}",
                value=tag['tag_name'],
                description=f"{tag['look_count'] or 0} looks"
            ))
        super().__init__(
            placeholder="Select a tag to search looks...",
            options=options if options else [discord.SelectOption(label="No tags available", value="none")],
            custom_id="tag_list_search_select",
            disabled=not options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.defer()
            return
            
        selected_tag = self.values[0]
        await interaction.response.defer(ephemeral=True)
        
        looks, total_count, _ = await db.search_looks(
            interaction.guild.id, [selected_tag], mode="AND", limit=5, offset=0
        )
        
        if not looks:
            await interaction.followup.send(
                f"📌 No looks match `#{selected_tag}`!",
                ephemeral=True,
            )
            return

        total_pages = math.ceil(total_count / 5) if total_count > 0 else 1
        embed = create_search_results_embed(
            [selected_tag], looks, page=1, total_pages=total_pages, total_count=total_count, guild_id=interaction.guild.id, mode="AND"
        )

        view = GalleryPaginationView(
            author_id=interaction.user.id,
            tag_names=[selected_tag],
            server_id=interaction.guild.id,
            guild_id=interaction.guild.id,
            current_page=1,
            total_pages=total_pages,
            mode="AND"
        )

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class TagListView(discord.ui.View):
    def __init__(self, tags: list):
        super().__init__(timeout=180)
        if tags:
            self.add_item(TagListSearchDropdown(tags))


class PaginatedSearchTagsSelect(discord.ui.Select):
    """Dropdown for a specific page of search tags."""

    def __init__(self, page_tags: list, selected_tag_ids: set, category: str, page: int):
        options = []
        for tag in page_tags:
            options.append(discord.SelectOption(
                label=f"#{tag['tag_name']}",
                value=str(tag['tag_id']),
                default=str(tag['tag_id']) in selected_tag_ids,
            ))

        super().__init__(
            placeholder=f"Select {category} tags for search (Page {page + 1})...",
            min_values=0,
            max_values=min(len(options), 25) if options else 1,
            options=options if options else [discord.SelectOption(label="No tags in this category", value="none")],
            custom_id=f"search_tags_select:{category}:{page}",
            disabled=not options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()


class PaginatedSearchFormView(discord.ui.View):
    """Paginated search panel with Category, Page, and AND/OR mode switching."""

    def __init__(self, author_id: int, all_tags: list):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.all_tags = all_tags
        self.selected_tag_ids = set()
        self.category = "Style"
        self.page = 0
        self.mode = "AND"
        self.update_components()

    def sync_selections(self):
        select = next((item for item in self.children if isinstance(item, PaginatedSearchTagsSelect)), None)
        if select and not select.disabled:
            page_option_ids = {opt.value for opt in select.options if opt.value != "none"}
            selected_ids = set(select.values) if "none" not in select.values else set()
            self.selected_tag_ids -= page_option_ids
            self.selected_tag_ids |= selected_ids

    def make_category_callback(self, cat):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
                return
            self.sync_selections()
            self.category = cat
            self.page = 0
            self.update_components()
            await interaction.response.edit_message(view=self)
        return callback

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return
        self.sync_selections()
        self.page -= 1
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return
        self.sync_selections()
        self.page += 1
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def toggle_mode(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return
        self.sync_selections()
        self.mode = "OR" if self.mode == "AND" else "AND"
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

        self.add_item(PaginatedSearchTagsSelect(page_tags, self.selected_tag_ids, self.category, self.page))

        categories = ["Style", "Tag", "Custom"]
        for cat in categories:
            btn = discord.ui.Button(
                label=cat, 
                style=discord.ButtonStyle.primary if cat == self.category else discord.ButtonStyle.secondary,
                custom_id=f"search_cat_btn:{cat}",
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

        # Toggle Mode button
        mode_label = f"Mode: {self.mode} (Match All)" if self.mode == "AND" else f"Mode: {self.mode} (Match Any)"
        mode_style = discord.ButtonStyle.success if self.mode == "AND" else discord.ButtonStyle.secondary
        mode_btn = discord.ui.Button(
            label=mode_label,
            style=mode_style,
            custom_id="search_mode_toggle_btn",
            row=3
        )
        mode_btn.callback = self.toggle_mode
        self.add_item(mode_btn)

        search_btn = discord.ui.Button(label="🔍 Search", style=discord.ButtonStyle.primary, row=3)
        search_btn.callback = self.run_search
        self.add_item(search_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
        cancel_btn.callback = self.cancel
        self.add_item(cancel_btn)

    async def run_search(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return

        self.sync_selections()
        
        # Map selected tag IDs to names
        selected_names = [t['tag_name'] for t in self.all_tags if str(t['tag_id']) in self.selected_tag_ids]
        
        if not selected_names:
            await interaction.response.send_message("❌ Please select at least one tag to search.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        looks, total_count, _ = await db.search_looks(
            interaction.guild.id, selected_names, mode=self.mode, limit=5, offset=0
        )

        if not looks:
            tag_label = f" {self.mode} ".join(f"`#{n}`" for n in selected_names)
            await interaction.followup.send(
                f"📌 No looks match {tag_label}! Try selecting different tags.",
                ephemeral=True,
            )
            return

        total_pages = math.ceil(total_count / 5) if total_count > 0 else 1
        embed = create_search_results_embed(
            selected_names, looks, page=1, total_pages=total_pages, total_count=total_count, guild_id=interaction.guild.id, mode=self.mode
        )

        view = GalleryPaginationView(
            author_id=self.author_id,
            tag_names=selected_names,
            server_id=interaction.guild.id,
            guild_id=interaction.guild.id,
            current_page=1,
            total_pages=total_pages,
            mode=self.mode
        )

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return
        await interaction.response.send_message("Search cancelled.", ephemeral=True)
        self.stop()


class TagCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tag_create", description="Create a new tag (goes into Custom category)")
    @app_commands.describe(
        name="Tag name (e.g., 'business', 'fantasy')"
    )
    async def create_tag(self, interaction: discord.Interaction, name: str):
        """Create a new tag"""
        try:
            await interaction.response.defer()

            if len(name) > 50:
                await interaction.followup.send("❌ Tag name too long (max 50 characters)", ephemeral=True)
                return

            if not name.replace("-", "").replace("_", "").isalnum():
                await interaction.followup.send(
                    "❌ Tag can only contain letters, numbers, hyphens, and underscores",
                    ephemeral=True,
                )
                return

            tag_id = await db.create_tag(
                server_id=interaction.guild.id,
                tag_name=name.lower(),
                category='Custom',
                created_by=interaction.user.id
            )

            if tag_id:
                embed = discord.Embed(
                    title="✅ Tag Created",
                    description=f"New tag `#{name.lower()}` is ready to use in the **Custom** category!",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"❌ Tag `#{name.lower()}` already exists", ephemeral=True)

        except Exception as e:
            print(f"❌ Error in create_tag: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    @app_commands.command(name="tag_list", description="Show all tags in this server")
    async def list_tags(self, interaction: discord.Interaction):
        """List all tags"""
        try:
            await interaction.response.defer(ephemeral=True)

            tags = await db.get_tags(interaction.guild.id)
            embed = create_tag_list_embed(tags, interaction.guild.name)

            view = TagListView(tags)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            print(f"❌ Error in tag_list: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    @app_commands.command(name="tag_delete", description="Delete a tag")
    @app_commands.describe(name="Tag name to delete")
    async def delete_tag(self, interaction: discord.Interaction, name: str):
        """Delete a tag"""
        try:
            await interaction.response.defer()

            if not interaction.user.guild_permissions.manage_guild:
                await interaction.followup.send("❌ You need manage server permissions", ephemeral=True)
                return

            from config import HARDCODED_STYLES, HARDCODED_TAGS
            if name.lower().strip() in [s.lower() for s in HARDCODED_STYLES + HARDCODED_TAGS]:
                await interaction.followup.send("❌ Cannot delete hardcoded Style or Tag options.", ephemeral=True)
                return

            success = await db.delete_tag(interaction.guild.id, name.lower())

            if success:
                embed = discord.Embed(
                    title="✅ Tag Deleted",
                    description=f"Tag `#{name.lower()}` has been removed",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"❌ Tag `#{name.lower()}` not found", ephemeral=True)

        except Exception as e:
            print(f"❌ Error in delete_tag: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    async def tag_autocomplete(self, interaction: discord.Interaction, current: str):
        """Autocompletes available workspace tags as the user types"""
        try:
            tag_names = await db.get_tag_names(interaction.guild.id)
            if not tag_names:
                return []
            return [
                app_commands.Choice(name=f"#{name}", value=name)
                for name in tag_names if current.lower() in name.lower()
            ][:25]
        except Exception as e:
            print(f"❌ Error in tag_autocomplete: {e}")
            return []

    @app_commands.command(
        name="tag_search",
        description="Open search panel to filter looks using tag dropdowns and boolean logic"
    )
    async def search_lookbook(self, interaction: discord.Interaction):
        """Displays interactive form where users select tags and search mode."""
        try:
            await interaction.response.defer(ephemeral=True)

            tags = await db.get_tags(interaction.guild.id)
            if not tags:
                await interaction.followup.send(
                    "❌ No tags exist in this server yet.",
                    ephemeral=True,
                )
                return

            view = PaginatedSearchFormView(interaction.user.id, tags)
            embed = discord.Embed(
                title="🔍 Lookbook Tag Search Panel",
                description=(
                    "Use the dropdown select menu below to pick one or more tags across categories.\n"
                    "Toggle the search mode button to change matching behavior:\n"
                    "• **AND Mode**: Matches looks containing **all** selected tags.\n"
                    "• **OR Mode**: Matches looks containing **at least one** selected tag.\n\n"
                    "Click **Search** to view results."
                ),
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            print(f"❌ Error in tag_search command: {e}")
            await interaction.followup.send("❌ Failed to initialize search panel.", ephemeral=True)

    @app_commands.command(name="help", description="Show help instructions for using the bot")
    async def help_command(self, interaction: discord.Interaction):
        """Show bot help information"""
        try:
            await interaction.response.defer(ephemeral=True)

            embed = discord.Embed(
                title="📖 Tag Library Help Guide",
                description="Welcome to the Discord Tag Library bot! Here is a guide on how to configure and use the bot.",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="🔧 Admin Configuration",
                value=(
                    "• `/look_setup action:Add channel channel:#name`\n"
                    "  Enable look submissions inside the specified channel.\n"
                    "• `/look_setup action:Remove channel channel:#name`\n"
                    "  Disable look submissions inside the specified channel.\n"
                    "• `/look_setup action:List channels`\n"
                    "  List all allowed look submission channels."
                ),
                inline=False
            )

            embed.add_field(
                name="🏷️ Tag Management",
                value=(
                    "• `/tag_create name:tagName`\n"
                    "  Create a new tag to label looks.\n"
                    "• `/tag_list`\n"
                    "  Show all available tags in this server along with their look count.\n"
                    "• `/tag_delete name:tagName`\n"
                    "  Delete a tag from the server (requires Manage Server permission)."
                ),
                inline=False
            )

            embed.add_field(
                name="📸 Submitting Looks",
                value=(
                    "• `/look_submit image:[upload] comp_name:Name`\n"
                    "  Submit a new lookbook entry inside an allowlisted channel.\n"
                    "• **Form-Based Controls** (buttons attached to posts):\n"
                    "  - **Edit Title**: Click to rename the look name using a modal popup.\n"
                    "  - **Edit Tags**: Click to assign or modify tags using a multiselect dropdown."
                ),
                inline=False
            )

            embed.add_field(
                name="🔍 Searching the Lookbook",
                value=(
                    "• `/tag_search`\n"
                    "  Brings up an interactive search form where you can choose tags from a dropdown, toggle search modes (**AND** matching all tags vs **OR** matching any tag), and browse the results as a paginated image gallery."
                ),
                inline=False
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            print(f"❌ Error in help_command: {e}")
            await interaction.followup.send("❌ An error occurred displaying help.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TagCommands(bot))
