import discord
from datetime import datetime


def build_gallery_jump_url(guild_id, channel_id, message_id):
    """Build a jump URL to a bot-owned look message."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def format_tag_list(tags):
    """Format tag rows as a hashtag string."""
    if not tags:
        return "_No tags yet — use **Edit Tags** to add some._"
    return " ".join(f"`#{tag['tag_name']}`" for tag in tags)


def create_tag_list_embed(tags, server_name):
    """Create embed showing all tags"""
    embed = discord.Embed(
        title=f"📌 Tags in {server_name}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )

    if not tags:
        embed.description = "No tags created yet. Use `/tag_create` to start!"
        return embed

    for tag in tags:
        tag_name = tag['tag_name']
        count = tag['look_count'] or 0
        embed.add_field(
            name=f"#{tag_name}",
            value=f"`{count}` looks",
            inline=True
        )

    return embed


def create_look_embed(look, tags, guild_id):
    """Create the embed for a bot-owned look post."""
    caption = look['caption'] or "No caption"
    tag_line = format_tag_list(tags)

    embed = discord.Embed(
        title="✨ Lookbook Entry",
        description=caption,
        color=discord.Color.from_rgb(255, 182, 193),
        timestamp=look['created_at']
    )
    embed.add_field(name="Tags", value=tag_line, inline=False)
    embed.add_field(name="Submitted by", value=f"<@{look['submitted_by']}>", inline=True)
    if look['bot_message_id']:
        jump_url = build_gallery_jump_url(guild_id, look['channel_id'], look['bot_message_id'])
        embed.add_field(name="View post", value=f"[Jump to message]({jump_url})", inline=True)

    if look['image_url']:
        embed.set_image(url=look['image_url'])

    embed.set_footer(text=f"Look #{look['look_id']}")
    return embed


def create_search_results_embed(tag_names, looks, page, total_pages, total_count, guild_id):
    """Create embed showing intersection search results."""
    tag_label = " AND ".join(f"#{name}" for name in tag_names)
    embed = discord.Embed(
        title=f"🔍 Lookbook Search: {tag_label}",
        description=f"Found {total_count} matching looks (Page {page}/{total_pages})",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )

    if not looks:
        embed.description = "No looks match all of these tags yet. Try `/look_submit` to add one!"
        return embed

    if looks[0]['image_url']:
        embed.set_image(url=looks[0]['image_url'])

    for index, look in enumerate(looks):
        caption = look['caption'] or "No description"
        curator = f"<@{look['submitted_by']}>"
        jump_url = build_gallery_jump_url(guild_id, look['channel_id'], look['bot_message_id'])
        matched = look['matched_tags']
        if matched:
            tag_str = " ".join(f"`#{t}`" for t in matched)
        else:
            tag_str = "_none_"

        field_value = (
            f"📝 **Details:** {caption}\n"
            f"🏷️ **Tags:** {tag_str}\n"
            f"👤 **Submitted by:** {curator}\n"
            f"✨ [View post]({jump_url})"
        )

        row_title = "🌟 Top Match" if index == 0 and page == 1 else f"📷 Look #{index + 1 + (page - 1) * 5}"
        embed.add_field(name=row_title, value=field_value, inline=False)

    return embed
