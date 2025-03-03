import streamlit as st
import pandas as pd
import os
import time
import pickle
from datetime import datetime, timedelta
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from quickbooks import QuickBooks
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.customer import Customer
from quickbooks.objects.vendor import Vendor
from quickbooks.objects.bill import Bill
from quickbooks.objects.purchase import Purchase
from quickbooks.objects.account import Account
from quickbooks.objects.item import Item


# Page configuration
st.set_page_config(page_title="QuickBooks Data Explorer", layout="wide")
st.title("QuickBooks Data Structure Explorer")
st.write("This tool helps you explore your QuickBooks data structure before building the full dashboard.")

# Initialize QuickBooks Client
def initialize_quickbooks_client():
    # Modified to use the [quickbooks] section in secrets.toml
    client_id = st.secrets["QB_CLIENT_ID"]
    client_secret = st.secrets["QB_CLIENT_SECRET"]
    redirect_uri = st.secrets["QB_REDIRECT_URI"]
    environment = st.secrets.get("QB_ENVIRONMENT", "sandbox")  # 'sandbox' or 'production'
    
    auth_client = AuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        environment=environment
    )
    
    # If we have a saved token, load and use it
    token_path = "qb_token.pickle"
    
    # Flag to indicate if we need to get a new token
    need_new_token = True
    
    if os.path.exists(token_path):
        try:
            with open(token_path, "rb") as token_file:
                token_info = pickle.load(token_file)
                auth_client.access_token = token_info.get("access_token")
                auth_client.refresh_token = token_info.get("refresh_token")
                auth_client.realm_id = token_info.get("realm_id")
                
                # If we have a refresh token, try to use it
                if auth_client.refresh_token:
                    try:
                        auth_client.refresh()
                        need_new_token = False
                        
                        # Save refreshed token
                        with open(token_path, "wb") as token_file:
                            token_info = {
                                "access_token": auth_client.access_token,
                                "refresh_token": auth_client.refresh_token,
                                "realm_id": auth_client.realm_id
                            }
                            pickle.dump(token_info, token_file)
                    except Exception as e:
                        st.warning(f"Failed to refresh token: {str(e)}. Need to reauthenticate.")
        except Exception as e:
            st.warning(f"Error loading saved token: {str(e)}. Need to reauthenticate.")
    
    # If we need a new token, initiate authorization flow
    if need_new_token:
        # New authorization needed
        authorization_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])
        st.markdown(f"[Authorize QuickBooks access]({authorization_url})")
        
        auth_code = st.text_input("Enter the authorization code received:")
        realm_id = st.text_input("Enter your QuickBooks Company ID (realm ID):")
        
        if auth_code and realm_id:
            try:
                auth_client.get_bearer_token(auth_code, realm_id=realm_id)
                auth_client.realm_id = realm_id
                
                # Save token for future use
                with open(token_path, "wb") as token_file:
                    token_info = {
                        "access_token": auth_client.access_token,
                        "refresh_token": auth_client.refresh_token,
                        "realm_id": auth_client.realm_id
                    }
                    pickle.dump(token_info, token_file)
                
                st.success("Authentication successful! Please refresh the page.")
                st.stop()
            except Exception as e:
                st.error(f"Authentication error: {str(e)}")
                st.stop()
    
    # Return QuickBooks client initialized with auth client
    return QuickBooks(
        auth_client=auth_client,
        refresh_token=auth_client.refresh_token,
        company_id=auth_client.realm_id
    )

# Main application
try:
    # Initialize QuickBooks client
    with st.spinner("Connecting to QuickBooks..."):
        qb_client = initialize_quickbooks_client()
    
    # Show connection status
    st.success("Successfully connected to QuickBooks!")
    
    # Data exploration section
    st.header("Data Explorer")
    
    # Select entity to explore
    entity_types = [
        "Accounts", 
        "Customers", 
        "Vendors", 
        "Invoices", 
        "Bills", 
        "Purchases",
        "Classes",
        "Items"
    ]
    
    selected_entity = st.selectbox("Select data to explore:", entity_types)
    
    if selected_entity:
        with st.spinner(f"Loading {selected_entity}..."):
            try:
                # Date range for transactional data
                if selected_entity in ["Invoices", "Bills", "Purchases"]:
                    col1, col2 = st.columns(2)
                    with col1:
                        # Default to last 3 months
                        default_start = datetime.now() - timedelta(days=90)
                        start_date = st.date_input("Start Date", default_start)
                    with col2:
                        end_date = st.date_input("End Date", datetime.now())
                
                # Fetch data based on selection
                if selected_entity == "Accounts":
                    entities = Account.all(qb=qb_client)
                    st.subheader("Chart of Accounts")
                elif selected_entity == "Customers":
                    entities = Customer.all(qb=qb_client)
                    st.subheader("Customers (Potential Restaurant Locations)")
                elif selected_entity == "Vendors":
                    entities = Vendor.all(qb=qb_client)
                    st.subheader("Vendors")
                elif selected_entity == "Invoices":
                    query = f"SELECT * FROM Invoice WHERE TxnDate >= '{start_date}' AND TxnDate <= '{end_date}' MAXRESULTS 100"
                    entities = Invoice.query(query, qb=qb_client)
                    st.subheader("Recent Invoices (Sales)")
                elif selected_entity == "Bills":
                    query = f"SELECT * FROM Bill WHERE TxnDate >= '{start_date}' AND TxnDate <= '{end_date}' MAXRESULTS 100"
                    entities = Bill.query(query, qb=qb_client)
                    st.subheader("Recent Bills (Expenses)")
                elif selected_entity == "Purchases":
                    query = f"SELECT * FROM Purchase WHERE TxnDate >= '{start_date}' AND TxnDate <= '{end_date}' MAXRESULTS 100"
                    entities = Purchase.query(query, qb=qb_client)
                    st.subheader("Recent Purchases")
                elif selected_entity == "Classes":
                    # Handle potential Class import error gracefully
                    try:
                        entities = Class.all(qb=qb_client)
                        st.subheader("Classes (Could be used for Restaurant Locations)")
                    except Exception as class_error:
                        st.error(f"Error loading Classes: {str(class_error)}")
                        st.info("The Classes feature may not be enabled in your QuickBooks account, or there might be an issue with library compatibility.")
                        entities = []
                elif selected_entity == "Items":
                    entities = Item.all(qb=qb_client)
                    st.subheader("Items")
                
                # Display data
                if entities:
                    st.write(f"Found {len(entities)} {selected_entity.lower()}")
                    
                    # Process entities into a dataframe
                    entity_data = []
                    
                    for entity in entities:
                        # Different handling for different entity types
                        if selected_entity == "Accounts":
                            entity_dict = {
                                "Id": entity.Id,
                                "Name": entity.Name,
                                "AccountType": entity.AccountType,
                                "AccountSubType": getattr(entity, "AccountSubType", ""),
                                "FullyQualifiedName": getattr(entity, "FullyQualifiedName", "")
                            }
                        elif selected_entity == "Customers":
                            entity_dict = {
                                "Id": entity.Id,
                                "DisplayName": entity.DisplayName,
                                "Active": getattr(entity, "Active", True),
                                "CompanyName": getattr(entity, "CompanyName", "")
                            }
                        elif selected_entity == "Vendors":
                            entity_dict = {
                                "Id": entity.Id,
                                "DisplayName": entity.DisplayName,
                                "Active": getattr(entity, "Active", True),
                                "CompanyName": getattr(entity, "CompanyName", "")
                            }
                        elif selected_entity == "Classes":
                            entity_dict = {
                                "Id": entity.Id,
                                "Name": entity.Name,
                                "Active": getattr(entity, "Active", True),
                                "FullyQualifiedName": getattr(entity, "FullyQualifiedName", "")
                            }
                        elif selected_entity == "Items":
                            entity_dict = {
                                "Id": entity.Id,
                                "Name": entity.Name,
                                "Type": getattr(entity, "Type", ""),
                                "Active": getattr(entity, "Active", True)
                            }
                        elif selected_entity in ["Invoices", "Bills", "Purchases"]:
                            # Transactional data
                            entity_dict = {
                                "Id": entity.Id,
                                "TxnDate": entity.TxnDate,
                                "TotalAmt": getattr(entity, "TotalAmt", 0)
                            }
                            
                            # Add customer or vendor info if available
                            if hasattr(entity, "CustomerRef") and entity.CustomerRef:
                                entity_dict["CustomerRef"] = entity.CustomerRef.value
                            if hasattr(entity, "VendorRef") and entity.VendorRef:
                                entity_dict["VendorRef"] = entity.VendorRef.value
                            
                            # Check for class reference (for restaurant location)
                            if hasattr(entity, "ClassRef") and entity.ClassRef:
                                entity_dict["ClassRef"] = entity.ClassRef.value
                        
                        entity_data.append(entity_dict)
                    
                    # Convert to dataframe and display
                    if entity_data:
                        df = pd.DataFrame(entity_data)
                        st.dataframe(df)
                        
                        # Show structure details
                        st.subheader("Data Structure")
                        st.write("Column Names:")
                        st.code(", ".join(df.columns.tolist()))
                        
                        # Select an entity to view details
                        if not df.empty:
                            st.subheader("Entity Details")
                            
                            if selected_entity in ["Accounts", "Customers", "Vendors", "Classes", "Items"]:
                                # For master records, select by name
                                name_field = "Name" if "Name" in df.columns else "DisplayName"
                                if name_field in df.columns:
                                    selected_name = st.selectbox(
                                        f"Select a {selected_entity[:-1]} to view details:",
                                        options=df[name_field].tolist()
                                    )
                                    
                                    # Display full entity attributes
                                    if selected_name:
                                        id_value = df[df[name_field] == selected_name]["Id"].values[0]
                                        
                                        # Fetch full entity
                                        if selected_entity == "Accounts":
                                            detail_entity = Account.get(id_value, qb=qb_client)
                                        elif selected_entity == "Customers":
                                            detail_entity = Customer.get(id_value, qb=qb_client)
                                        elif selected_entity == "Vendors":
                                            detail_entity = Vendor.get(id_value, qb=qb_client)
                                        elif selected_entity == "Classes":
                                            detail_entity = Class.get(id_value, qb=qb_client)
                                        elif selected_entity == "Items":
                                            detail_entity = Item.get(id_value, qb=qb_client)
                                        
                                        # Display all attributes
                                        st.json(detail_entity.to_dict())
                            else:
                                # For transactional records, select by ID
                                if "Id" in df.columns:
                                    selected_id = st.selectbox(
                                        f"Select a {selected_entity[:-1]} to view details:",
                                        options=df["Id"].tolist()
                                    )
                                    
                                    # Display full entity attributes
                                    if selected_id:
                                        # Fetch full entity
                                        if selected_entity == "Invoices":
                                            detail_entity = Invoice.get(selected_id, qb=qb_client)
                                        elif selected_entity == "Bills":
                                            detail_entity = Bill.get(selected_id, qb=qb_client)
                                        elif selected_entity == "Purchases":
                                            detail_entity = Purchase.get(selected_id, qb=qb_client)
                                        
                                        # Display all attributes
                                        st.json(detail_entity.to_dict())
                else:
                    st.warning(f"No {selected_entity.lower()} found.")
            
            except Exception as e:
                st.error(f"Error loading {selected_entity}: {str(e)}")
    
    # Data structure analysis
    st.header("Account Structure Recommendations")
    
    # Check for required account structure
    if "Accounts" in entity_types:
        with st.expander("View Recommended Account Structure"):
            st.markdown("""
            ## Recommended Chart of Accounts for Dashboard
            
            To match the dashboard, we recommend the following accounts:
            
            ### Food Cost Accounts
            - `Food Cost - Raw Waste` (for Perte brute)
            - `Food Cost - Finished Product Waste` (for Perte completée)
            - `Food Cost - Condiments` (for Condiments)
            - `Food Cost - Employee Meals` (for Cout des aliments empl.)
            - `Food Cost - STAT` (for STAT)
            
            ### Labor Cost Accounts
            - `Labor - Line Staff` (for M-O Équipiers, CdQ)
            - `Labor - Management` (for Gestion)
            
            ### Restaurant Location Method
            For tracking multiple restaurants, use either:
            1. **Classes** - Create a class for each restaurant location
            2. **Customers** - Create a customer record for each restaurant
            
            Check if your structure matches these recommendations.
            """)
    
    # Data mapping tool
    st.header("Data Mapping Tool")
    
    with st.expander("Map Your QuickBooks Data to Dashboard Categories"):
        st.write("Use this tool to create a mapping between your QuickBooks accounts and dashboard categories.")
        
        # Initialize session state for mapping
        if 'mappings' not in st.session_state:
            st.session_state.mappings = {
                "Perte brute": "",
                "Perte completée": "",
                "Condiments": "",
                "Cout des aliments empl.": "",
                "STAT": "",
                "M-O Équipiers, CdQ": "",
                "Gestion": ""
            }
        
        # Load accounts for mapping
        try:
            accounts = Account.all(qb=qb_client)
            account_names = [account.Name for account in accounts]
            
            # Create mapping interface
            st.write("Map dashboard categories to your QuickBooks accounts:")
            
            for category, current_value in st.session_state.mappings.items():
                st.session_state.mappings[category] = st.selectbox(
                    f"Which account represents '{category}'?",
                    options=[""] + account_names,
                    index=account_names.index(current_value) + 1 if current_value in account_names else 0
                )
            
            # Save mapping button
            if st.button("Save Mapping"):
                # Convert to a format for the dashboard
                mapping_output = "# QuickBooks Account Mapping\n\n"
                mapping_output += "ACCOUNT_MAPPING = {\n"
                for category, account in st.session_state.mappings.items():
                    if account:
                        mapping_output += f"    '{category}': '{account}',\n"
                mapping_output += "}\n"
                
                st.code(mapping_output)
                st.download_button(
                    "Download Mapping as Python File",
                    mapping_output,
                    "quickbooks_mapping.py",
                    "text/plain"
                )
                
                st.success("Mapping saved! You can now use this in your dashboard configuration.")
        except Exception as e:
            st.error(f"Error loading accounts for mapping: {str(e)}")
    
    # Restaurant location exploration
    st.header("Restaurant Location Explorer")
    
    with st.expander("Find Restaurant Locations in Your Data"):
        st.write("This tool helps you identify how restaurant locations are represented in your QuickBooks data.")
        
        location_methods = ["Classes", "Customers", "Custom Fields"]
        selected_method = st.radio("How are restaurant locations represented in your QuickBooks?", location_methods)
        
        if selected_method == "Classes":
            try:
                classes = Class.all(qb=qb_client)
                class_data = [{
                    "Id": cls.Id,
                    "Name": cls.Name,
                    "FullyQualifiedName": getattr(cls, "FullyQualifiedName", cls.Name)
                } for cls in classes]
                
                st.write(f"Found {len(class_data)} classes that could represent restaurant locations:")
                st.dataframe(pd.DataFrame(class_data))
                
                # Check if classes are used in transactions
                st.write("Checking if classes are used in transactions...")
                try:
                    # Check recent invoices for class references
                    query = "SELECT * FROM Invoice WHERE ClassRef IS NOT NULL MAXRESULTS 10"
                    class_invoices = Invoice.query(query, qb=qb_client)
                    
                    if class_invoices:
                        st.success(f"Found {len(class_invoices)} invoices with class references. Classes are being used!")
                    else:
                        st.warning("No invoices found with class references. Classes may not be actively used.")
                except Exception as e:
                    st.error(f"Error checking class usage: {str(e)}")
                
            except Exception as e:
                st.error(f"Error loading classes: {str(e)}")
        
        elif selected_method == "Customers":
            try:
                customers = Customer.all(qb=qb_client)
                customer_data = [{
                    "Id": customer.Id,
                    "DisplayName": customer.DisplayName,
                    "CompanyName": getattr(customer, "CompanyName", "")
                } for customer in customers]
                
                st.write(f"Found {len(customer_data)} customers that could represent restaurant locations:")
                
                # Filter options
                filter_text = st.text_input("Filter customers containing text:", "Restaurant")
                
                if filter_text:
                    filtered_data = [c for c in customer_data 
                                    if filter_text.lower() in c["DisplayName"].lower() or 
                                        (c["CompanyName"] and filter_text.lower() in c["CompanyName"].lower())]
                    st.write(f"Found {len(filtered_data)} customers containing '{filter_text}':")
                    st.dataframe(pd.DataFrame(filtered_data))
                else:
                    st.dataframe(pd.DataFrame(customer_data))
                
            except Exception as e:
                st.error(f"Error loading customers: {str(e)}")
        
        elif selected_method == "Custom Fields":
            st.write("To check for custom fields, we need to examine transactions:")
            
            try:
                # Check recent invoices for custom fields
                recent_invoices = Invoice.query("SELECT * FROM Invoice MAXRESULTS 10", qb=qb_client)
                
                if recent_invoices and len(recent_invoices) > 0:
                    # Check if any custom fields exist
                    has_custom_fields = False
                    custom_field_names = set()
                    
                    for invoice in recent_invoices:
                        invoice_dict = invoice.to_dict()
                        if "CustomField" in invoice_dict:
                            has_custom_fields = True
                            for field in invoice_dict["CustomField"]:
                                if "Name" in field:
                                    custom_field_names.add(field["Name"])
                    
                    if has_custom_fields:
                        st.success(f"Found custom fields: {', '.join(custom_field_names)}")
                        st.write("These custom fields might be used to identify restaurant locations.")
                    else:
                        st.warning("No custom fields found in recent invoices.")
                else:
                    st.warning("No recent invoices found to check for custom fields.")
            
            except Exception as e:
                st.error(f"Error checking custom fields: {str(e)}")
    
    # Configuration helper
    st.header("Dashboard Configuration Helper")
    
    with st.expander("Generate Configuration for Dashboard"):
        st.write("Based on your data exploration, let's generate configuration for your dashboard:")
        
        # Restaurant location method
        location_options = ["Classes", "Customers", "Custom Fields"]
        location_method = st.selectbox(
            "How are restaurant locations identified in your QuickBooks?",
            options=location_options
        )
        
        # Time periods
        current_year = datetime.now().year
        default_years = [current_year, current_year - 1]
        years_to_include = st.multiselect(
            "Which years to include in the dashboard?",
            options=list(range(current_year - 5, current_year + 1)),
            default=default_years
        )
        
        # Generate configuration
        if st.button("Generate Configuration"):
            config_code = f"""
# Dashboard Configuration

# Restaurant location configuration
RESTAURANT_LOCATION_METHOD = "{location_method}"

# Years to include in analysis
YEARS_TO_ANALYZE = {years_to_include}

# Account mappings for dashboard categories
ACCOUNT_MAPPING = {{
"""
            # Add any saved mappings
            if 'mappings' in st.session_state:
                for category, account in st.session_state.mappings.items():
                    if account:
                        config_code += f"    '{category}': '{account}',\n"
            
            config_code += "}\n"
            
            st.code(config_code)
            st.download_button(
                "Download Configuration",
                config_code,
                "dashboard_config.py",
                "text/plain"
            )
            
            st.success("Configuration generated! You can now use this with your dashboard implementation.")
            
            # Provide next steps
            st.markdown("""
            ## Next Steps
            
            1. Download the configuration file
            2. Add it to your dashboard project
            3. Implement the full dashboard using the provided mapping
            4. Deploy your dashboard to Streamlit Cloud
            """)

except Exception as e:
    st.error(f"An error occurred: {str(e)}")
    st.error("Please check your QuickBooks API credentials and try again.")