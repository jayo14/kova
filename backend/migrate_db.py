import asyncio
import asyncpg
import sys

SOURCE_URL = "postgresql://postgres.zmbhiudolgnlccdqicas:RsZXpWzz4N9EEfs5@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
TARGET_URL = "postgresql://postgres:gnEuXEbxa8-SJ2-4PrUWSLaE0YT44Wju@pg-088b52.ws-mika-01a0f86f.db.rumptycloud.com:5432/kova_db"

async def get_tables(conn):
    return await conn.fetch('''
        SELECT tablename 
        FROM pg_catalog.pg_tables 
        WHERE schemaname = 'public' 
          AND tablename != 'alembic_version'
    ''')

async def main():
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        source_conn = await asyncpg.connect(SOURCE_URL, ssl=ssl_context)
        target_conn = await asyncpg.connect(TARGET_URL, ssl=ssl_context)
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    tables = [
        "users", "projects", "flows", "credentials",
        "exploration_sessions", "executions", "execution_events",
        "exploration_events", "evidence"
    ]
    
    for table in tables:
        print(f"Copying {table}...")
        
        cols = await source_conn.fetch(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{table}'")
        col_names = [col['column_name'] for col in cols]
        
        rows = await source_conn.fetch(f'SELECT * FROM "{table}"')
        print(f"  Found {len(rows)} rows.")
        if rows:
            try:
                await target_conn.execute(f'TRUNCATE "{table}" CASCADE')
                records = [tuple(row[c] for c in col_names) for row in rows]
                await target_conn.copy_records_to_table(
                    table, 
                    records=records,
                    columns=col_names
                )
                print(f"  Copied {table}.")
            except Exception as e:
                print(f"  Failed copying {table}: {e}")

    await source_conn.close()
    await target_conn.close()

    await source_conn.close()
    await target_conn.close()

if __name__ == '__main__':
    asyncio.run(main())
