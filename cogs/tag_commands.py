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
                self.tag_names, looks, self.current_page, self.total_pages, total_count, guild_id=self.guild_id
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


class SearchTagsSelect(discord.ui.Select):
    """Dropdown menu for selecting tags in search."""

    def __init__(self, tags: list):
        options = [
            discord.SelectOption(
                label=f"#{tag['tag_name']}",
                value=tag['tag_name'],
            )
            for tag in tags[:25]
        ]
        super().__init__(
            placeholder="Select tags to search for...",
            min_values=1,
            max_values=min(len(options), 25),
            options=options,
            custom_id="search_tags_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()


class SearchFormView(discord.ui.View):
    """Search panel view to choose tags and AND/OR mode."""

    def __init__(self, author_id: int, tags: list):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.mode = "AND"
        self.tags_select = SearchTagsSelect(tags)
        self.add_item(self.tags_select)
        self.update_buttons()

    def update_buttons(self):
        # Clear previous button items
        for item in list(self.children):
            if isinstance(item, discord.ui.Button):
                self.remove_item(item)

        # Add Toggle Mode button
        mode_label = f"Mode: {self.mode} (Match All)" if self.mode == "AND" else f"Mode: {self.mode} (Match Any)"
        mode_style = discord.ButtonStyle.green if self.mode == "AND" else discord.ButtonStyle.gray
        mode_btn = discord.ui.Button(
            label=mode_label,
            style=mode_style,
            custom_id="search_mode_toggle",
        )
        mode_btn.callback = self.toggle_mode
        self.add_item(mode_btn)

        # Add Search button
        search_btn = discord.ui.Button(
            label="🔍 Search",
            style=discord.ButtonStyle.primary,
            custom_id="search_submit_btn",
        )
        search_btn.callback = self.run_search
        self.add_item(search_btn)

    async def toggle_mode(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return
        self.mode = "OR" if self.mode == "AND" else "AND"
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def run_search(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This search form isn't yours!", ephemeral=True)
            return

        selected_names = self.tags_select.values
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
            selected_names, looks, page=1, total_pages=total_pages, total_count=total_count, guild_id=interaction.guild.id
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


class TagCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tag_create", description="Create a new tag")
    @app_commands.describe(
        name="Tag name (e.g., 'business', 'fantasy')",
        category="Category of the tag (Default: Other)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Style", value="Style"),
        app_commands.Choice(name="Tag", value="Tag"),
        app_commands.Choice(name="Other", value="Other"),
    ])
    async def create_tag(self, interaction: discord.Interaction, name: str, category: app_commands.Choice[str] = None):
        """Create a new tag"""
        try:
            category_val = category.value if category else "Other"
            if category_val in ["Style", "Tag"] and not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("❌ Only Server Admins can create 'Style' and 'Tag' categories.", ephemeral=True)
                return

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
                category=category_val,
                created_by=interaction.user.id
            )

            if tag_id:
                embed = discord.Embed(
                    title="✅ Tag Created",
                    description=f"New tag `#{name.lower()}` is ready to use!",
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
            await interaction.response.defer()

            tags = await db.get_tags(interaction.guild.id)
            embed = create_tag_list_embed(tags, interaction.guild.name)

            await interaction.followup.send(embed=embed)
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
                    "❌ No tags exist in this server yet. Ask an admin to create tags with `/tag_create`.",
                    ephemeral=True,
                )
                return

            view = SearchFormView(interaction.user.id, tags)
            embed = discord.Embed(
                title="🔍 Lookbook Tag Search Panel",
                description=(
                    "Use the dropdown select menu below to pick one or more tags.\n"
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
