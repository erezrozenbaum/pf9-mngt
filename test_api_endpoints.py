import requests
import json

# Test the API endpoints to see what's available
base_url = "http://localhost:8000"

def test_endpoints():
    print("Testing API endpoints...")
    
    # Test known working endpoint
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"Health endpoint: {response.status_code}")
    except Exception as e:
        print(f"Health endpoint error: {e}")
    
    # Test new users endpoint
    try:
        response = requests.get(f"{base_url}/users", timeout=5)
        print(f"Users endpoint: {response.status_code}")
        if response.status_code != 200:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Users endpoint error: {e}")
    
    # Test OpenAPI spec to see available endpoints
    try:
        response = requests.get(f"{base_url}/openapi.json", timeout=5)
        if response.status_code == 200:
            spec = response.json()
            paths = list(spec.get('paths', {}).keys())
            print(f"Available endpoints ({len(paths)}):")
            user_endpoints = [p for p in paths if 'user' in p.lower()]
            if user_endpoints:
                print("User-related endpoints found:")
                for ep in user_endpoints:
                    print(f"  {ep}")
            else:
                print("No user-related endpoints found")
                print("First 10 endpoints:")
                for ep in paths[:10]:
                    print(f"  {ep}")
    except Exception as e:
        print(f"OpenAPI spec error: {e}")

if __name__ == "__main__":
    test_endpoints()