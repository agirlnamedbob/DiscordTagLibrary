import math
import discord
from discord.ext import commands
from discord import app_commands
from utils.database import db
from utils.embeds import create_tag_list_embed, create_search_results_embed
from utils.helpers import parse_tag_string


class TagPaginationView(discord.ui.View):
    """Interactive buttons to navigate search result pages"""

    def __init__(self, author_id, tag_names, server_id, guild_id, current_page, total_pages):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.tag_names = tag_names
        self.server_id = server_id
        self.guild_id = guild_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.update_buttons()

    def update_buttons(self):
        self.prev_page.disabled = (self.current_page <= 1)
        self.next_page.disabled = (self.current_page >= self.total_pages)

    async def refresh_view(self, interaction: discord.Interaction):
        limit = 5
        offset = (self.current_page - 1) * limit

        looks, total_count, _ = await db.search_tags_intersection(
            self.server_id, self.tag_names, limit=limit, offset=offset
        )
        self.total_pages = max(1, math.ceil(total_count / limit))
        self.update_buttons()

        embed = create_search_results_embed(
            self.tag_names, looks, self.current_page, self.total_pages, total_count, self.guild_id
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


class TagCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tag_create", description="Create a new tag")
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
        description="Search lookbook posts by one or more tags (AND intersection)",
    )
    @app_commands.describe(
        tags="Tag names to match — comma-separated for intersection (e.g. casual, pink)",
        page="Page number to view (defaults to 1)",
    )
    @app_commands.autocomplete(tags=tag_autocomplete)
    async def search_lookbook(self, interaction: discord.Interaction, tags: str, page: int = 1):
        """Queries the database and displays looks matching all requested tags."""
        try:
            await interaction.response.defer()

            tag_names = parse_tag_string(tags)
            if not tag_names:
                await interaction.followup.send(
                    "❌ Provide at least one tag name (e.g. `casual` or `casual, pink`).",
                    ephemeral=True,
                )
                return

            if len(tag_names) > 25:
                await interaction.followup.send("❌ You can search with at most 25 tags.", ephemeral=True)
                return

            server_id = interaction.guild.id

            _, missing = await db.resolve_tag_names(server_id, tag_names)
            if missing:
                await interaction.followup.send(
                    f"❌ Unknown tags: {', '.join(f'`#{n}`' for n in missing)}",
                    ephemeral=True,
                )
                return

            limit = 5
            if page < 1:
                page = 1
            offset = (page - 1) * limit

            looks, total_count, _ = await db.search_tags_intersection(
                server_id, tag_names, limit=limit, offset=offset
            )

            if not looks:
                tag_label = " AND ".join(f"`#{n}`" for n in tag_names)
                await interaction.followup.send(
                    f"📌 No looks match {tag_label} yet! Use `/look_submit` to add one.",
                    ephemeral=True,
                )
                return

            total_pages = max(1, math.ceil(total_count / limit))
            if page > total_pages:
                offset = (total_pages - 1) * limit
                looks, total_count, _ = await db.search_tags_intersection(
                    server_id, tag_names, limit=limit, offset=offset
                )
                page = total_pages

            embed = create_search_results_embed(
                tag_names, looks, page, total_pages, total_count, interaction.guild.id
            )

            view = TagPaginationView(
                author_id=interaction.user.id,
                tag_names=tag_names,
                server_id=server_id,
                guild_id=interaction.guild.id,
                current_page=page,
                total_pages=total_pages,
            )

            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            print(f"❌ Critical crash caught inside tag_search: {e}")
            try:
                await interaction.followup.send(
                    "❌ An unexpected error occurred while processing your lookbook search.",
                    ephemeral=True,
                )
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(TagCommands(bot))
