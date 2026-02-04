#!/usr/bin/env python3
"""
Aggressive database cleanup - removes all records that weren't seen in the latest run
This ensures the database exactly matches current Platform9 state
"""
import os
import psycopg2
from datetime import datetime, timedelta

def aggressive_cleanup():
    """Remove all records that weren't seen in the most recent inventory run"""
    try:
        # Connect to database
        conn = psycopg2.connect(
            host=os.environ.get('PF9_DB_HOST', 'localhost'),
            port=os.environ.get('PF9_DB_PORT', 5432),
            database=os.environ.get('PF9_DB_NAME', 'pf9_mgmt'),
            user=os.environ.get('PF9_DB_USER', 'pf9'),
            password=os.environ.get('PF9_DB_PASSWORD', 'pf9_password_change_me')
        )
        
        with conn.cursor() as cur:
            # Get the most recent update timestamp from any table
            cur.execute("""
                SELECT MAX(last_seen_at) as latest 
                FROM (
                    SELECT MAX(last_seen_at) as last_seen_at FROM servers
                    UNION ALL
                    SELECT MAX(last_seen_at) as last_seen_at FROM volumes
                    UNION ALL
                    SELECT MAX(last_seen_at) as last_seen_at FROM snapshots
                ) t
            """)
            result = cur.fetchone()
            if not result or not result[0]:
                print("No recent records found")
                return False
                
            latest_update = result[0]
            print(f"Latest update timestamp: {latest_update}")
            
            # Remove records that are more than 30 minutes older than the latest update
            # This catches records from previous runs that no longer exist
            cutoff = latest_update - timedelta(minutes=30)
            print(f"Removing records older than: {cutoff}")
            
            tables_to_clean = [
                'snapshots', 'images', 'servers', 'volumes', 
                'floating_ips', 'ports', 'routers', 'subnets', 'networks'
            ]
            
            total_removed = 0
            for table in tables_to_clean:
                try:
                    # Count records to remove
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE last_seen_at < %s", (cutoff,))
                    to_remove = cur.fetchone()[0]
                    
                    if to_remove > 0:
                        # Remove old records
                        cur.execute(f"DELETE FROM {table} WHERE last_seen_at < %s", (cutoff,))
                        removed = cur.rowcount
                        print(f"Removed {removed} old records from {table}")
                        total_removed += removed
                    else:
                        print(f"No old records in {table}")
                        
                except Exception as e:
                    print(f"Warning: Could not clean {table}: {e}")
                    conn.rollback()
                    continue
            
            if total_removed > 0:
                conn.commit()
                print(f"\nTotal removed: {total_removed} old records")
            else:
                print("No cleanup needed - all records are current")
            
            # Show final counts
            print(f"\nFinal counts:")
            for table in ['servers', 'volumes', 'snapshots', 'networks']:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"  {table}: {count}")
                
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error during aggressive cleanup: {e}")
        return False

if __name__ == "__main__":
    print("=== Aggressive Database Cleanup ===")
    print("This removes all records not seen in the latest inventory run")
    print()
    
    success = aggressive_cleanup()
    if success:
        print("\n✅ Aggressive cleanup completed successfully")
    else:
        print("\n❌ Cleanup failed")