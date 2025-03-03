"""
QuickBooks API Python Integration Guide
"""
import json
import requests
from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import BackendApplicationClient
import os
# Add this line before your OAuth2 code
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# Step 1: Set up your environment
# First, install the required packages:
# pip install requests requests_oauthlib

# Step 2: Configure your QuickBooks API credentials
CLIENT_ID = 'ABTuYoL6dMfSCUeQ6RJ2FtKwONPuQfHZayHAgfzpE0tn6qeGxV'
CLIENT_SECRET = 'tZDojaw3yGyP7CC5xCFcYmz2kQKJTFqqnBmoWPsm'
REDIRECT_URI = 'http://localhost:8000/callback'  # e.g., http://localhost:8000/callback
ENVIRONMENT = 'sandbox'  # Use 'production' for live data

# Base URLs
if ENVIRONMENT == 'sandbox':
    AUTH_URL = 'https://appcenter.intuit.com/connect/oauth2'
    TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
    API_BASE = 'https://sandbox-quickbooks.api.intuit.com/v3/company/'
else:
    AUTH_URL = 'https://appcenter.intuit.com/connect/oauth2'
    TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
    API_BASE = 'https://quickbooks.api.intuit.com/v3/company/'

# Step 3: OAuth 2.0 Authorization Flow (Authorization Code Flow)

# Step 3.1: Generate authorization URL
def get_authorization_url():
    oauth = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=['com.intuit.quickbooks.accounting'])
    authorization_url, state = oauth.authorization_url(AUTH_URL)
    print(f"Please go to this URL to authorize the application: {authorization_url}")
    return state

# Step 3.2: Handle the callback and get access token
def get_access_token(state, authorization_response):
    oauth = OAuth2Session(CLIENT_ID, state=state, redirect_uri=REDIRECT_URI)
    token = oauth.fetch_token(
        TOKEN_URL,
        authorization_response=authorization_response,
        client_secret=CLIENT_SECRET
    )
    return token

# Step 4: Store the tokens
def save_tokens(token):
    with open('quickbooks_tokens.json', 'w') as f:
        json.dump(token, f)

def load_tokens():
    try:
        with open('quickbooks_tokens.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

# Step 5: Refresh the token when it expires
def refresh_access_token(refresh_token):
    oauth = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
    token = oauth.refresh_token(
        TOKEN_URL,
        refresh_token=refresh_token,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )
    save_tokens(token)
    return token

# Step 6: Make API calls
def call_quickbooks_api(access_token, realm_id, endpoint, method='GET', data=None):
    """
    Call the QuickBooks API.
    
    Args:
        access_token (str): OAuth access token
        realm_id (str): Company ID / Realm ID
        endpoint (str): API endpoint (e.g., 'customer')
        method (str): HTTP method (GET, POST, etc.)
        data (dict): Request payload for POST/PUT requests
        
    Returns:
        dict: API response
    """
    url = f"{API_BASE}{realm_id}/{endpoint}"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    if method == 'GET':
        response = requests.get(url, headers=headers)
    elif method == 'POST':
        response = requests.post(url, headers=headers, json=data)
    elif method == 'PUT':
        response = requests.put(url, headers=headers, json=data)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")
    
    response.raise_for_status()
    return response.json()

# Example: Get list of customers
def get_customers(access_token, realm_id):
    return call_quickbooks_api(access_token, realm_id, 'query?query=select%20%2A%20from%20Customer')

# Example: Create a new customer
def create_customer(access_token, realm_id, customer_data):
    return call_quickbooks_api(access_token, realm_id, 'customer', method='POST', data=customer_data)

# Example usage of the above functions
def main():
    # Step 1: Get authorization URL
    state = get_authorization_url()
    
    # Step 2: User authorizes app and is redirected back
    redirect_response = input("Enter the full callback URL after authorization: ")
    
    # Step 3: Exchange authorization code for tokens
    token = get_access_token(state, redirect_response)
    save_tokens(token)
    
    # Step 4: Use the token to make API calls
    realm_id = input("Enter your Company ID / Realm ID: ")
    access_token = token['access_token']
    
    # Example: Get customers
    customers = get_customers(access_token, realm_id)
    print(json.dumps(customers, indent=2))

if __name__ == "__main__":
    main()

# Alternative: Using the QuickBooks Python SDK
"""
The QuickBooks Python SDK simplifies API interactions:
pip install python-quickbooks

Example usage:
"""
def quickbooks_sdk_example():
    from quickbooks import QuickBooks
    from quickbooks.objects.customer import Customer
    
    # Configure the client
    client = QuickBooks(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        access_token=ACCESS_TOKEN,
        refresh_token=REFRESH_TOKEN,
        company_id=REALM_ID,
        callback_url=REDIRECT_URI,
        environment=ENVIRONMENT
    )
    
    # Get customers
    customers = Customer.all(qb=client)
    for customer in customers:
        print(customer.DisplayName)
    
    # Create a customer
    new_customer = Customer()
    new_customer.DisplayName = "New Customer"
    new_customer.CompanyName = "New Company"
    new_customer.save(qb=client)