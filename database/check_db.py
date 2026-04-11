import sqlite3
import os

dbs = ['h:/trans/database/history.db', 'h:/trans/database/bot.db']

for db_path in dbs:
    if not os.path.exists(db_path):
        print(f"File not found: {db_path}")
        continue
    
    print(f"\n{'='*20} {os.path.basename(db_path)} {'='*20}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Get tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    
    for table in tables:
        print(f"\n--- Table: {table} ---")
        # Get schema
        cur.execute(f"PRAGMA table_info({table})")
        columns = cur.fetchall()
        for col in columns:
            print(f"  Column: {col[1]} ({col[2]}) {'[PK]' if col[5] else ''}")
            
        # Get existing indexes
        cur.execute(f"PRAGMA index_list({table})")
        indexes = cur.fetchall()
        if indexes:
            print("  Indexes:")
            for idx in indexes:
                idx_name = idx[1]
                cur.execute(f"PRAGMA index_info({idx_name})")
                idx_cols = [row[2] for row in cur.fetchall()]
                print(f"    {idx_name}: ({', '.join(idx_cols)})")
        else:
            print("  No explicit indexes (excluding PK).")
            
    conn.close()
