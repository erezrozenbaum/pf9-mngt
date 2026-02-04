#!/usr/bin/env python3
"""
Cleanup old snapshots that are no longer present in PF9
Run this after RVtools to remove stale snapshot records
"""
import os
import sys
import psycopg2
from datetime import datetime, timedelta

def cleanup_old_snapshots():
    """Remove snapshots that haven't been seen in the last RVtools run"""
    
    # Database connection
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432') 
    db_name = os.getenv('POSTGRES_DB', 'pf9_mgmt')
    db_user = os.getenv('POSTGRES_USER', 'pf9')
    db_password = os.getenv('POSTGRES_PASSWORD', 'pf9_password_change_me')
    
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password
        )
        
        with conn.cursor() as cur:
            # Remove snapshots that haven't been seen in the last hour
            # (more aggressive cleanup to keep database current)
            cutoff = datetime.utcnow() - timedelta(hours=1)
            
            # First, check how many old snapshots exist
            cur.execute("""
                SELECT COUNT(*) FROM snapshots 
                WHERE last_seen_at < %s
            """, (cutoff,))
            old_count = cur.fetchone()[0]
            
            if old_count > 0:
                print(f"Found {old_count} old snapshot(s) to remove...")
                
                # Remove old snapshots
                cur.execute("""
                    DELETE FROM snapshots 
                    WHERE last_seen_at < %s
                """, (cutoff,))
                
                removed = cur.rowcount
                print(f"Removed {removed} old snapshot record(s)")
                
                # Also clean up orphaned history records
                cur.execute("""
                    DELETE FROM snapshots_history 
                    WHERE snapshot_id NOT IN (SELECT id FROM snapshots)
                """)
                
                hist_removed = cur.rowcount
                if hist_removed > 0:
                    print(f"Removed {hist_removed} orphaned history record(s)")
            else:
                print("No old snapshots found - all records are current")
                
            # Show current snapshot count
            cur.execute("SELECT COUNT(*) FROM snapshots")
            current_count = cur.fetchone()[0]
            print(f"Total snapshots in database: {current_count}")
            
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"Error cleaning up snapshots: {e}")
        return False
        
    return True

if __name__ == "__main__":
    cleanup_old_snapshots()