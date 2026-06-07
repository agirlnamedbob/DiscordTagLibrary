import asyncpg
from config import DATABASE_URL


class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        """Initialize database connection pool"""
        self.pool = await asyncpg.create_pool(DATABASE_URL, ssl=True)
        print("✅ Database connected")
        await self.create_tables()

    async def disconnect(self):
        """Close database connections"""
        if self.pool:
            await self.pool.close()
            print("✅ Database disconnected")

    async def create_tables(self):
        """Create tables if they don't exist"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    tag_id SERIAL PRIMARY KEY,
                    server_id BIGINT NOT NULL,
                    tag_name VARCHAR(50) NOT NULL,
                    tag_color VARCHAR(7),
                    created_by BIGINT,
                    created_date TIMESTAMP DEFAULT NOW(),
                    UNIQUE(server_id, tag_name)
                )
            ''')

            await conn.execute('DROP TABLE IF EXISTS message_tags CASCADE')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS looks (
                    look_id SERIAL PRIMARY KEY,
                    server_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    bot_message_id BIGINT,
                    image_url TEXT,
                    caption TEXT,
                    submitted_by BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(server_id, bot_message_id)
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS look_tags (
                    look_id INTEGER NOT NULL REFERENCES looks(look_id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (look_id, tag_id)
                )
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_looks_server_created
                ON looks(server_id, created_at DESC)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_look_tags_tag_id
                ON look_tags(tag_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_look_tags_look_id
                ON look_tags(look_id)
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS guild_settings (
                    server_id BIGINT PRIMARY KEY,
                    allowed_channel_ids BIGINT[] NOT NULL DEFAULT '{}',
                    configured_by BIGINT,
                    configured_at TIMESTAMP DEFAULT NOW()
                )
            ''')

            print("✅ Database tables ready")

    # GUILD SETTINGS
    async def get_allowed_channels(self, server_id):
        """Return allowlisted channel IDs for look submissions."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT allowed_channel_ids FROM guild_settings WHERE server_id = $1
            ''', server_id)
            if not row:
                return []
            return list(row['allowed_channel_ids'])

    async def is_channel_allowed(self, server_id, channel_id, parent_channel_id=None):
        """Check if a channel (or its parent thread channel) is allowlisted."""
        allowed = await self.get_allowed_channels(server_id)
        if channel_id in allowed:
            return True
        if parent_channel_id and parent_channel_id in allowed:
            return True
        return False

    async def add_allowed_channel(self, server_id, channel_id, configured_by):
        """Add a channel to the server's look submission allowlist."""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO guild_settings (server_id, allowed_channel_ids, configured_by)
                VALUES ($1, ARRAY[$2::bigint], $3)
                ON CONFLICT (server_id) DO UPDATE SET
                    allowed_channel_ids = (
                        SELECT ARRAY(
                            SELECT DISTINCT unnest(
                                guild_settings.allowed_channel_ids || ARRAY[$2::bigint]
                            )
                        )
                    ),
                    configured_by = EXCLUDED.configured_by,
                    configured_at = NOW()
            ''', server_id, channel_id, configured_by)
            return True

    async def remove_allowed_channel(self, server_id, channel_id):
        """Remove a channel from the allowlist. Returns False if it was not listed."""
        async with self.pool.acquire() as conn:
            result = await conn.execute('''
                UPDATE guild_settings
                SET allowed_channel_ids = array_remove(allowed_channel_ids, $2),
                    configured_at = NOW()
                WHERE server_id = $1 AND $2 = ANY(allowed_channel_ids)
            ''', server_id, channel_id)
            return result.endswith("1")

    # TAG OPERATIONS
    async def create_tag(self, server_id, tag_name, tag_color, created_by):
        """Create a new tag"""
        async with self.pool.acquire() as conn:
            try:
                tag_id = await conn.fetchval('''
                    INSERT INTO tags (server_id, tag_name, tag_color, created_by)
                    VALUES ($1, $2, $3, $4)
                    RETURNING tag_id
                ''', server_id, tag_name, tag_color, created_by)
                return tag_id
            except asyncpg.UniqueViolationError:
                return None

    async def get_tags(self, server_id):
        """Get all tags in a server with look counts"""
        async with self.pool.acquire() as conn:
            tags = await conn.fetch('''
                SELECT t.tag_id, t.tag_name, t.tag_color, t.created_date,
                       COUNT(DISTINCT lt.look_id) AS look_count
                FROM tags t
                LEFT JOIN look_tags lt ON t.tag_id = lt.tag_id
                LEFT JOIN looks l ON lt.look_id = l.look_id AND l.server_id = t.server_id
                WHERE t.server_id = $1
                GROUP BY t.tag_id, t.tag_name, t.tag_color, t.created_date
                ORDER BY t.created_date DESC
            ''', server_id)
            return tags

    async def delete_tag(self, server_id, tag_name):
        """Delete a tag"""
        async with self.pool.acquire() as conn:
            result = await conn.execute('''
                DELETE FROM tags
                WHERE server_id = $1 AND tag_name = $2
            ''', server_id, tag_name)
            return "1 row" in str(result)

    async def get_tag_id(self, server_id, tag_name):
        """Get tag ID by name"""
        async with self.pool.acquire() as conn:
            tag_id = await conn.fetchval('''
                SELECT tag_id FROM tags
                WHERE server_id = $1 AND tag_name = $2
            ''', server_id, tag_name)
            return tag_id

    async def resolve_tag_names(self, server_id, tag_names):
        """Resolve tag names to IDs. Returns (tag_ids, missing_names)."""
        if not tag_names:
            return [], []

        unique_names = list(dict.fromkeys(name.lower().strip().lstrip("#") for name in tag_names if name.strip()))
        if not unique_names:
            return [], []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT tag_id, tag_name FROM tags
                WHERE server_id = $1 AND tag_name = ANY($2::text[])
            ''', server_id, unique_names)

        found = {row['tag_name']: row['tag_id'] for row in rows}
        missing = [name for name in unique_names if name not in found]
        tag_ids = [found[name] for name in unique_names if name in found]
        return tag_ids, missing

    # LOOK OPERATIONS
    async def create_look(self, server_id, channel_id, caption, submitted_by, image_url=None):
        """Insert a look row before the channel message is posted."""
        async with self.pool.acquire() as conn:
            look_id = await conn.fetchval('''
                INSERT INTO looks (server_id, channel_id, caption, submitted_by, image_url)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING look_id
            ''', server_id, channel_id, caption, submitted_by, image_url)
            return look_id

    async def update_look_message_id(self, look_id, bot_message_id, image_url=None):
        """Link a look to its bot-owned channel message."""
        async with self.pool.acquire() as conn:
            if image_url is not None:
                await conn.execute('''
                    UPDATE looks
                    SET bot_message_id = $2, image_url = $3, updated_at = NOW()
                    WHERE look_id = $1
                ''', look_id, bot_message_id, image_url)
            else:
                await conn.execute('''
                    UPDATE looks
                    SET bot_message_id = $2, updated_at = NOW()
                    WHERE look_id = $1
                ''', look_id, bot_message_id)

    async def delete_look(self, look_id):
        """Remove a look (compensating action if channel post fails)."""
        async with self.pool.acquire() as conn:
            await conn.execute('DELETE FROM looks WHERE look_id = $1', look_id)

    async def get_look(self, look_id):
        """Fetch a single look by ID."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM looks WHERE look_id = $1', look_id)

    async def get_all_looks(self, server_id):
        """Fetch all looks with posted messages (for persistent view registration)."""
        async with self.pool.acquire() as conn:
            return await conn.fetch('''
                SELECT look_id FROM looks
                WHERE server_id = $1 AND bot_message_id IS NOT NULL
            ''', server_id)

    async def get_look_tag_names(self, look_id):
        """Return tag names attached to a look."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT t.tag_id, t.tag_name, t.tag_color
                FROM look_tags lt
                JOIN tags t ON t.tag_id = lt.tag_id
                WHERE lt.look_id = $1
                ORDER BY t.tag_name
            ''', look_id)
            return rows

    async def add_look_tags(self, look_id, tag_ids, added_by):
        """Attach tags to a look."""
        if not tag_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany('''
                INSERT INTO look_tags (look_id, tag_id, added_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (look_id, tag_id) DO NOTHING
            ''', [(look_id, tag_id, added_by) for tag_id in tag_ids])

    async def set_look_tags(self, look_id, tag_ids, added_by):
        """Replace look tags with the selected set."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetch('''
                    SELECT tag_id FROM look_tags WHERE look_id = $1
                ''', look_id)
                current_ids = {row['tag_id'] for row in current}
                selected_ids = set(tag_ids)

                to_remove = current_ids - selected_ids
                to_add = selected_ids - current_ids

                if to_remove:
                    await conn.execute('''
                        DELETE FROM look_tags
                        WHERE look_id = $1 AND tag_id = ANY($2::int[])
                    ''', look_id, list(to_remove))

                if to_add:
                    await conn.executemany('''
                        INSERT INTO look_tags (look_id, tag_id, added_by)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (look_id, tag_id) DO NOTHING
                    ''', [(look_id, tag_id, added_by) for tag_id in to_add])

                await conn.execute('''
                    UPDATE looks SET updated_at = NOW() WHERE look_id = $1
                ''', look_id)

    # SEARCH OPERATIONS
    async def search_tags_intersection(self, server_id, tag_names, limit=5, offset=0):
        """Find looks matching ALL requested tags (intersection)."""
        unique_names = list(dict.fromkeys(
            name.lower().strip().lstrip("#") for name in tag_names if name and name.strip()
        ))
        if not unique_names:
            return [], 0, unique_names

        async with self.pool.acquire() as conn:
            resolved_count = await conn.fetchval('''
                SELECT COUNT(*)::int FROM tags
                WHERE server_id = $1 AND tag_name = ANY($2::text[])
            ''', server_id, unique_names)

            if resolved_count != len(unique_names):
                return [], 0, unique_names

            looks = await conn.fetch('''
                WITH requested AS (
                    SELECT tag_id FROM tags
                    WHERE server_id = $1 AND tag_name = ANY($2::text[])
                ),
                resolved_count AS (
                    SELECT COUNT(*)::int AS n FROM requested
                )
                SELECT
                    l.look_id,
                    l.bot_message_id,
                    l.channel_id,
                    l.image_url,
                    l.caption,
                    l.submitted_by,
                    l.created_at,
                    array_agg(DISTINCT t.tag_name ORDER BY t.tag_name) AS matched_tags
                FROM looks l
                JOIN look_tags lt ON lt.look_id = l.look_id
                JOIN tags t ON t.tag_id = lt.tag_id
                WHERE l.server_id = $1
                  AND lt.tag_id IN (SELECT tag_id FROM requested)
                GROUP BY l.look_id, l.bot_message_id, l.channel_id, l.image_url,
                         l.caption, l.submitted_by, l.created_at
                HAVING COUNT(DISTINCT lt.tag_id) = (SELECT n FROM resolved_count)
                ORDER BY l.created_at DESC
                LIMIT $3 OFFSET $4
            ''', server_id, unique_names, limit, offset)

            total = await conn.fetchval('''
                WITH requested AS (
                    SELECT tag_id FROM tags
                    WHERE server_id = $1 AND tag_name = ANY($2::text[])
                ),
                n AS (
                    SELECT COUNT(*)::int AS n FROM requested
                )
                SELECT COUNT(*) FROM (
                    SELECT l.look_id
                    FROM looks l
                    JOIN look_tags lt ON lt.look_id = l.look_id
                    WHERE l.server_id = $1
                      AND lt.tag_id IN (SELECT tag_id FROM requested)
                    GROUP BY l.look_id
                    HAVING COUNT(DISTINCT lt.tag_id) = (SELECT n FROM n)
                ) sub
            ''', server_id, unique_names)

            return looks, total, unique_names


db = Database()
