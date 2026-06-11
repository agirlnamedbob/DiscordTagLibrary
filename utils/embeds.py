from collections import defaultdict
from datetime import datetime
import discord


def build_gallery_jump_url(guild_id, channel_id, message_id):
    """Build a jump URL to a bot-owned look message."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def format_tag_list(tags):
    """Format tag rows grouped by category, sorted alphabetically."""
    if not tags:
        return "_No tags yet — use **Edit Tags** to add some._"

    category_mapping = {
        'Style': 'Styles',
        'Tag': 'Tags',
        'Custom': 'Custom',
        'Other': 'Custom'
    }
    
    # Sort all tags alphabetically by name (case-insensitive) first
    sorted_tags = sorted(tags, key=lambda x: x['tag_name'].lower())

    # Group sorted items in a single pass
    grouped = defaultdict(list)
    for t in sorted_tags:
        clean_cat = category_mapping.get(t['category'], 'Custom')
        grouped[clean_cat].append(f"`#{t['tag_name']}`")

    # Build output rows based on display order
    display_order = ['Styles', 'Tags', 'Custom']
    lines = [f"**{cat}:** {' '.join(grouped[cat])}" for cat in display_order if grouped[cat]]
    
    return "\n".join(lines)


def create_tag_list_embed(tags, category, server_name):
    """Create an embed showing all tags in a category, alphabetized with smart chunking."""
    embed = discord.Embed(
        title=f"✦ {category} Tags in {server_name} ✦",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )

    if not tags:
        embed.description = f"No tags in the **{category}** category yet."
        return embed

    # Sort tags alphabetically by name (case-insensitive)
    sorted_tags = sorted(tags, key=lambda x: x['tag_name'].lower())

    # Pre-format individual tag strings with look counts
    tag_strs = [f"`#{t['tag_name']}` ({t['look_count'] or 0})" for t in sorted_tags]

    # Smart Chunking: Build chunks out of whole tags, not raw characters
    chunks = []
    current_chunk = []
    current_length = 0
    total_accumulated_length = 0

    for tag in tag_strs:
        # Emergency safeguard: Hard cutoff if total text breaches safe embed limits
        if total_accumulated_length + len(tag) > 5500:
            embed.set_footer(text="⚠ Visual limit reached. Clean up unused tags to see more.")
            break
            
        # 1024 is the maximum allowed characters for a single embed field value
        if current_length + len(tag) + 2 > 1024: 
            chunks.append(", ".join(current_chunk))
            current_chunk = [tag]
            current_length = len(tag)
        else:
            current_chunk.append(tag)
            current_length += len(tag) + 2
            
        total_accumulated_length += len(tag) + 2

    if current_chunk:
        chunks.append(", ".join(current_chunk))

    # Determine UI layout based on payload size
    if len(chunks) == 1 and len(chunks[0]) <= 4000:
        # Keep everything in the description box if it fits nicely
        embed.description = chunks[0]
    else:
        # Spill over into distinct page fields if the list is long
        embed.description = f"List of all registered **{category}** tags:"
        for idx, chunk in enumerate(chunks, 1):
            embed.add_field(
                name=f"Tags (Page {idx})", 
                value=chunk, 
                inline=False
            )
            
    return embed


def create_look_embed(look, tags, guild_id, attachment_filename=None):
    """Create the embed for a bot-owned look post with optimized width."""
    comp_name = look['comp_name'] or "No name"

    # We use a long line of invisible spaces or a subtle markdown line 
    # to force the embed wrapper to expand to maximum width.
    max_width_stretcher = "\u200b " + " " * 35 

    embed = discord.Embed(
        title=comp_name,
        description=max_width_stretcher, # Pushes the embed walls out
        color=discord.Color.from_rgb(255, 182, 193),
        timestamp=look['created_at']
    )
    
    styles = [t['tag_name'] for t in tags if t['category'] == 'Style']
    look_tags = [t['tag_name'] for t in tags if t['category'] == 'Tag']
    customs = [t['tag_name'] for t in tags if t['category'] in ['Custom', 'Other']]

    # Making these inline=True groups them nicely into columns
    embed.add_field(name="Style", value=", ".join(f"`#{t}`" for t in styles) if styles else "_None_", inline=True)
    embed.add_field(name="Tag", value=", ".join(f"`#{t}`" for t in look_tags) if look_tags else "_None_", inline=True)
    embed.add_field(name="Custom", value=", ".join(f"`#{t}`" for t in customs) if customs else "_None_", inline=True)
    
    # This will automatically drop to the next row because Discord limits rows to 3 inline fields
    embed.add_field(name="Submitted by", value=f"<@{look['submitted_by']}>", inline=False)

    if attachment_filename:
        embed.set_image(url=f"attachment://{attachment_filename}")

    return embed


def create_search_results_embed(tag_names, looks, page, total_pages, total_count, guild_id, mode="AND"):
    """Create embed showing intersection search results."""
    tag_label = f" {mode} ".join(f"#{name}" for name in tag_names)
    embed = discord.Embed(
        title=f"✦ Lookbook Search: {tag_label} ✦",
        description=f"Found {total_count} matching looks (Page {page}/{total_pages})",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )

    if not looks:
        embed.description = "No looks match all of these tags yet. Try `/look_submit` to add one!"
        return embed

    for index, look in enumerate(looks):
        comp_name = look['comp_name'] or "No name"
        curator = f"<@{look['submitted_by']}>"
        jump_url = build_gallery_jump_url(guild_id, look['channel_id'], look['bot_message_id'])
        matched = look['matched_tags']
        if matched:
            tag_str = " ".join(f"`#{t}`" for t in matched)
        else:
            tag_str = "_none_"

        field_value = (
            f"✦ **Comp Name** ✦ {comp_name}\n"
            f"✦ **Tags** ✦ {tag_str}\n"
            f"✦ **Submitted by** ✦ {curator}\n"
            f"✦ [View post]({jump_url}) ✦"
        )

        row_title = f"✦ Match {index + 1 + (page - 1) * 5} ✦"
        embed.add_field(name=row_title, value=field_value, inline=False)

    return embed