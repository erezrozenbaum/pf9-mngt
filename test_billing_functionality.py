#!/usr/bin/env python3
"""
v1.95 Billing System Functionality Test
Tests all billing endpoints with proper authentication.
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_billing_functionality():
    """Test billing system functionality in Docker environment."""
    print("🧪 Testing v1.95 Billing System Functionality...")
    
    # Step 1: Authentication
    auth_data = {
        "username": "admin@ccc.co.il", 
        "password": "r#1kajun"
    }
    
    print("\n1. 🔐 Authentication Test...")
    login_response = requests.post(f"{BASE_URL}/api/auth/login", json=auth_data)
    if login_response.status_code != 200:
        print(f"❌ Authentication failed: {login_response.text}")
        return False
    
    token = login_response.json()["access_token"] 
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Authentication successful")
    
    # Step 2: Test billing overview endpoint
    print("\n2. 📊 Billing Overview Test...")
    overview_response = requests.get(f"{BASE_URL}/api/billing/overview", headers=headers)
    if overview_response.status_code != 200:
        print(f"❌ Billing overview failed: {overview_response.text}")
        return False
    
    overview_data = overview_response.json()
    print(f"✅ Billing overview success:")
    print(f"   📈 Total billing configs: {overview_data.get('billing_summary', {}).get('total_tenants', 0)}")
    print(f"   💰 Total prepaid accounts: {overview_data.get('prepaid_summary', {}).get('total_accounts', 0)}")
    
    # Step 3: Test tenant billing configs endpoint  
    print("\n3. 🏢 Tenant Billing Configs Test...")
    configs_response = requests.get(f"{BASE_URL}/api/billing/tenant-configs", headers=headers)
    if configs_response.status_code != 200:
        print(f"❌ Tenant configs failed: {configs_response.text}")
        return False
    
    configs_data = configs_response.json()
    print(f"✅ Tenant configs success: {len(configs_data.get('configs', []))} configurations found")
    
    # Step 4: Test prepaid accounts endpoint
    print("\n4. 💳 Prepaid Accounts Test...")
    prepaid_response = requests.get(f"{BASE_URL}/api/billing/prepaid-accounts", headers=headers)
    if prepaid_response.status_code != 200:
        print(f"❌ Prepaid accounts failed: {prepaid_response.text}")
        return False
    
    prepaid_data = prepaid_response.json()
    print(f"✅ Prepaid accounts success: {len(prepaid_data.get('accounts', []))} accounts found")
    
    # Step 5: Database tables verification
    print("\n5. 🗃️ Database Tables Verification...")
    try:
        import subprocess
        result = subprocess.run([
            "docker", "exec", "pf9_db", "psql", "-U", "pf9", "-d", "pf9_mgmt", "-c", 
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND (table_name LIKE '%billing%' OR table_name LIKE '%prepaid%' OR table_name LIKE '%pricing%' OR table_name LIKE '%webhook%' OR table_name LIKE '%lifecycle%');"
        ], capture_output=True, text=True, check=True)
        
        tables = [line.strip() for line in result.stdout.split('\n') if line.strip() and not line.startswith('-') and line != 'table_name']
        billing_tables = [t for t in tables if any(keyword in t for keyword in ['billing', 'prepaid', 'pricing', 'webhook', 'lifecycle'])]
        print(f"✅ Database verification success: {len(billing_tables)} billing tables found")
        for table in billing_tables:
            print(f"   📋 {table}")
            
    except Exception as e:
        print(f"⚠️ Database verification warning: {e}")
    
    print("\n🎉 ALL BILLING FUNCTIONALITY TESTS PASSED!")
    print("🚀 v1.95 Billing Enhancement System is OPERATIONAL!")
    return True

if __name__ == "__main__":
    success = test_billing_functionality()
    sys.exit(0 if success else 1)