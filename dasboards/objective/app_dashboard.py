#sstreamlit run dasboards/objective/app_dashboard.py

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import calendar
import os
from intuitlib.client import AuthClient
from quickbooks import QuickBooks
from quickbooks.objects.account import Account
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.bill import Bill
from quickbooks.objects.vendorcredit import VendorCredit
from quickbooks.objects.journalentry import JournalEntry
from quickbooks.objects.purchase import Purchase
from quickbooks.objects.customer import Customer
from quickbooks import helpers
from intuitlib.enums import Scopes
# Configuration de la page
st.set_page_config(
    page_title="Tableau de bord Restaurant",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Fonction pour se connecter à l'API QuickBooks
# Ajouter quelque part dans votre app pour le débogage
if st.sidebar.checkbox("Afficher l'état de la session"):
    st.sidebar.write(st.session_state)
    
def connect_to_quickbooks():
    from intuitlib.enums import Scopes
    
    # Configuration de base
    try:
        client_id = st.secrets["QB_CLIENT_ID"]
        client_secret = st.secrets["QB_CLIENT_SECRET"]
        redirect_uri = "http://localhost:8501/"  # URI de redirection sans /callback
        environment = st.secrets["QB_ENVIRONMENT"]
    except:
        client_id = st.sidebar.text_input("QuickBooks Client ID", type="password")
        client_secret = st.sidebar.text_input("QuickBooks Client Secret", type="password")
        redirect_uri = "http://localhost:8501/"  # URI fixe sans /callback
        environment = st.sidebar.selectbox("Environnement", ["sandbox", "production"])
        
        if not (client_id and client_secret):
            return None

    auth_client = AuthClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        environment=environment
    )
    
    # Si nous n'avons pas encore de jeton dans la session
    if 'access_token' not in st.session_state:
        # Générer l'URL d'authentification
        auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])
        
        st.sidebar.markdown("""
        ### Instructions pour l'authentification QuickBooks:
        
        1) Cliquez sur le bouton ci-dessous pour vous connecter à QuickBooks:
        """)
        
        st.sidebar.markdown(f"[Se connecter à QuickBooks]({auth_url})")
        
        st.sidebar.markdown("""
        2) Après avoir autorisé l'application, vous serez redirigé vers une page 
           qui affichera peut-être une erreur - c'est normal.
           
        3) Dans l'URL de cette page, copiez:
           - Le code (après `code=` et avant `&state=`)
           - Le Realm ID (après `realmId=`)
           
        4) Collez ces informations ci-dessous:
        """)
        
        # Champs pour saisie manuelle
        auth_code = st.sidebar.text_input("Code d'autorisation:", "")
        realm_id = st.sidebar.text_input("Realm ID:", "")
        
        if st.sidebar.button("Valider l'authentification"):
            if auth_code and realm_id:
                try:
                    auth_client.get_bearer_token(auth_code)
                    st.session_state.access_token = auth_client.access_token
                    st.session_state.refresh_token = auth_client.refresh_token
                    st.session_state.realm_id = realm_id
                    st.sidebar.success("Connecté à QuickBooks!")
                    st.experimental_rerun()  # Pour rafraîchir la page
                except Exception as e:
                    st.sidebar.error(f"Erreur d'authentification: {e}")
                    return None
            else:
                st.sidebar.error("Veuillez fournir le code d'autorisation et le Realm ID")
                return None
        
        return None  # Retourner None si l'authentification n'est pas encore complète
    
    # Si nous avons déjà un jeton, créer le client QuickBooks
    try:
        client = QuickBooks(
            auth_client=auth_client,
            refresh_token=st.session_state.refresh_token,
            company_id=st.session_state.realm_id,
        )
        st.sidebar.success("Connecté à QuickBooks!")
        return client
    except Exception as e:
        st.sidebar.error(f"Erreur lors de la création du client QuickBooks: {e}")
        if 'access_token' in st.session_state:
            del st.session_state.access_token
        return None
    
# Fonction pour obtenir les données QuickBooks
def get_qbo_data(client, start_date, end_date, account_refs=None):
    """
    Récupère les données financières de QuickBooks pour la période spécifiée.
    """
    if not client:
        return None
    
    # Convertir les dates au format QuickBooks
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    
    # Récupérer les transactions de ventes, coûts, etc.
    try:
        # Requête pour les entrées de journal dans la période
        query = f"""
        SELECT * FROM JournalEntry 
        WHERE TxnDate >= '{start_str}' AND TxnDate <= '{end_str}'
        MAXRESULTS 1000
        """
        journal_entries = JournalEntry.query(query, qb=client)
        
        # Requête pour les factures dans la période
        query = f"""
        SELECT * FROM Invoice 
        WHERE TxnDate >= '{start_str}' AND TxnDate <= '{end_str}'
        MAXRESULTS 1000
        """
        invoices = Invoice.query(query, qb=client)
        
        # Requête pour les achats dans la période
        query = f"""
        SELECT * FROM Purchase 
        WHERE TxnDate >= '{start_str}' AND TxnDate <= '{end_str}'
        MAXRESULTS 1000
        """
        purchases = Purchase.query(query, qb=client)
        
        # Récupérer les comptes pour identifier les catégories
        accounts = Account.filter(Active=True, qb=client)
        
        # Créer un dictionnaire de mappage des comptes
        account_map = {}
        for account in accounts:
            account_map[account.Id] = {
                'Name': account.Name,
                'Number': account.AcctNum if hasattr(account, 'AcctNum') else '',
                'Type': account.AccountType,
                'SubType': account.AccountSubType if hasattr(account, 'AccountSubType') else ''
            }
        
        return {
            'journal_entries': journal_entries,
            'invoices': invoices,
            'purchases': purchases,
            'accounts': account_map
        }
    
    except Exception as e:
        st.error(f"Erreur lors de la récupération des données QuickBooks: {e}")
        return None

# Fonction pour traiter les données et créer le tableau de bord
def process_data_for_dashboard(qbo_data, start_date, end_date, selected_restaurant=None):
    """
    Traite les données de QuickBooks pour les adapter au format du tableau de bord.
    """
    if not qbo_data:
        return None
    
    # Créer des DataFrames vides pour chaque catégorie
    sales_data = []
    food_cost_data = []
    labour_data = []
    
    # Traiter les journaux
    for entry in qbo_data['journal_entries']:
        for line in entry.Line:
            if hasattr(line, 'JournalEntryLineDetail') and hasattr(line.JournalEntryLineDetail, 'AccountRef'):
                account_id = line.JournalEntryLineDetail.AccountRef.value
                account_info = qbo_data['accounts'].get(account_id, {})
                amount = float(line.Amount) if hasattr(line, 'Amount') else 0
                
                # Déterminer si crédit ou débit
                is_credit = line.JournalEntryLineDetail.PostingType == "Credit"
                if is_credit:
                    amount = -amount
                
                # Extraire la date
                txn_date = datetime.strptime(entry.TxnDate, '%Y-%m-%d')
                month = txn_date.strftime('%Y-%m')
                
                # Classer selon le numéro de compte
                account_num = account_info.get('Number', '')
                
                # Filtrer par restaurant si spécifié
                entity_ref = None
                if hasattr(entry, 'EntityRef'):
                    entity_ref = entry.EntityRef.name
                
                if selected_restaurant and entity_ref != selected_restaurant:
                    continue
                
                # Classifier en fonction du compte
                if account_num.startswith('401'):  # Ventes
                    sales_data.append({
                        'Date': txn_date,
                        'Month': month,
                        'Amount': amount,
                        'Account': account_info.get('Name', ''),
                        'Type': 'Sales',
                        'Restaurant': entity_ref
                    })
                elif account_num.startswith('51'):  # Coût des aliments
                    food_cost_data.append({
                        'Date': txn_date,
                        'Month': month,
                        'Amount': amount,
                        'Account': account_info.get('Name', ''),
                        'Type': 'Food Cost',
                        'Category': categorize_food_cost(account_num),
                        'Restaurant': entity_ref
                    })
                elif account_num.startswith('60'):  # Main d'oeuvre
                    labour_data.append({
                        'Date': txn_date,
                        'Month': month,
                        'Amount': amount,
                        'Account': account_info.get('Name', ''),
                        'Type': 'Labour',
                        'Category': 'Crew' if account_num == '60100' else 'Management',
                        'Restaurant': entity_ref
                    })
    
    # Traiter les factures pour les ventes
    for invoice in qbo_data['invoices']:
        if hasattr(invoice, 'TotalAmt'):
            amount = float(invoice.TotalAmt)
            txn_date = datetime.strptime(invoice.TxnDate, '%Y-%m-%d')
            month = txn_date.strftime('%Y-%m')
            
            customer_name = invoice.CustomerRef.name if hasattr(invoice, 'CustomerRef') else None
            
            if selected_restaurant and customer_name != selected_restaurant:
                continue
                
            sales_data.append({
                'Date': txn_date,
                'Month': month,
                'Amount': amount,
                'Account': 'Sales',
                'Type': 'Sales',
                'Restaurant': customer_name
            })
    
    # Traiter les achats pour les coûts
    for purchase in qbo_data['purchases']:
        if hasattr(purchase, 'TotalAmt'):
            amount = float(purchase.TotalAmt)
            txn_date = datetime.strptime(purchase.TxnDate, '%Y-%m-%d')
            month = txn_date.strftime('%Y-%m')
            
            # Déterminer la catégorie en fonction du fournisseur ou des lignes
            category = 'Other'
            if hasattr(purchase, 'Line'):
                for line in purchase.Line:
                    if hasattr(line, 'AccountBasedExpenseLineDetail') and hasattr(line.AccountBasedExpenseLineDetail, 'AccountRef'):
                        account_id = line.AccountBasedExpenseLineDetail.AccountRef.value
                        account_info = qbo_data['accounts'].get(account_id, {})
                        account_num = account_info.get('Number', '')
                        
                        if account_num.startswith('51'):
                            category = categorize_food_cost(account_num)
                            break
            
            entity_name = purchase.EntityRef.name if hasattr(purchase, 'EntityRef') else None
            
            if selected_restaurant and entity_name != selected_restaurant:
                continue
                
            food_cost_data.append({
                'Date': txn_date,
                'Month': month,
                'Amount': amount,
                'Account': category,
                'Type': 'Food Cost',
                'Category': category,
                'Restaurant': entity_name
            })
    
    # Créer les DataFrames
    sales_df = pd.DataFrame(sales_data) if sales_data else pd.DataFrame(columns=['Date', 'Month', 'Amount', 'Account', 'Type', 'Restaurant'])
    food_cost_df = pd.DataFrame(food_cost_data) if food_cost_data else pd.DataFrame(columns=['Date', 'Month', 'Amount', 'Account', 'Type', 'Category', 'Restaurant'])
    labour_df = pd.DataFrame(labour_data) if labour_data else pd.DataFrame(columns=['Date', 'Month', 'Amount', 'Account', 'Type', 'Category', 'Restaurant'])
    
    # Générer les données pour le tableau de bord
    dashboard_data = {}
    
    # Générer les mois entre la date de début et de fin
    months = []
    current_date = start_date.replace(day=1)
    while current_date <= end_date:
        months.append(current_date.strftime('%Y-%m'))
        # Passer au mois suivant
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)
    
    # Obtenir les données de l'année précédente pour comparaison
    prev_year_start = start_date.replace(year=start_date.year - 1)
    prev_year_end = end_date.replace(year=end_date.year - 1)
    
    # Placeholder pour les données de l'année précédente (dans une vraie mise en œuvre, vous récupéreriez ces données)
    prev_year_data = {month: np.random.randint(400000, 600000) for month in months}
    
    # Préparer les données mensuelles
    monthly_data = {}
    for month in months:
        month_sales = sales_df[sales_df['Month'] == month]['Amount'].sum() if not sales_df.empty else 0
        prev_month_sales = prev_year_data.get(month, 0)
        
        growth = ((month_sales - prev_month_sales) / prev_month_sales * 100) if prev_month_sales > 0 else 0
        
        # Food costs par catégorie
        food_costs = {}
        if not food_cost_df.empty:
            month_food_costs = food_cost_df[food_cost_df['Month'] == month]
            for category in ['Perte brute', 'Perte complétée', 'Condiments', 'Aliments employés', 'STAT']:
                food_costs[category] = month_food_costs[month_food_costs['Category'] == category]['Amount'].sum()
        else:
            food_costs = {
                'Perte brute': 0,
                'Perte complétée': 0,
                'Condiments': 0, 
                'Aliments employés': 0,
                'STAT': 0
            }
        
        total_food_cost = sum(food_costs.values())
        food_cost_percent = (total_food_cost / month_sales * 100) if month_sales > 0 else 0
        
        # Labour costs
        labour_costs = {}
        if not labour_df.empty:
            month_labour = labour_df[labour_df['Month'] == month]
            labour_costs['Équipiers'] = month_labour[month_labour['Category'] == 'Crew']['Amount'].sum()
            labour_costs['Gestion'] = month_labour[month_labour['Category'] == 'Management']['Amount'].sum()
        else:
            labour_costs = {'Équipiers': 0, 'Gestion': 0}
        
        total_labour = sum(labour_costs.values())
        labour_percent = (total_labour / month_sales * 100) if month_sales > 0 else 0
        
        # Ajouter les données FCFP de Clearview (simulé ici)
        fcfp = np.random.randint(90, 130)
        
        # Calculer le pourcentage numérique (simulé)
        numerique = np.random.uniform(15.0, 17.0)
        
        monthly_data[month] = {
            'Ventes': {
                'Actuel': month_sales,
                'Année précédente': prev_month_sales,
                'Croissance': growth
            },
            'Coût des aliments': {
                'Perte brute': food_costs['Perte brute'],
                'Perte complétée': food_costs['Perte complétée'],
                'Condiments': food_costs['Condiments'],
                'Aliments employés': food_costs['Aliments employés'],
                'STAT': food_costs['STAT'],
                'Total': total_food_cost,
                'Pourcentage': food_cost_percent
            },
            'Main d\'oeuvre': {
                'Équipiers': labour_costs['Équipiers'],
                'Gestion': labour_costs['Gestion'],
                'Total': total_labour,
                'Pourcentage': labour_percent
            },
            'FCFP': fcfp,
            'Numérique': numerique
        }
    
    # Calculer le total du trimestre
    quarter_data = {
        'Ventes': {
            'Actuel': sum(monthly_data[month]['Ventes']['Actuel'] for month in months),
            'Année précédente': sum(monthly_data[month]['Ventes']['Année précédente'] for month in months),
        },
        'Coût des aliments': {
            'Perte brute': sum(monthly_data[month]['Coût des aliments']['Perte brute'] for month in months),
            'Perte complétée': sum(monthly_data[month]['Coût des aliments']['Perte complétée'] for month in months),
            'Condiments': sum(monthly_data[month]['Coût des aliments']['Condiments'] for month in months),
            'Aliments employés': sum(monthly_data[month]['Coût des aliments']['Aliments employés'] for month in months),
            'STAT': sum(monthly_data[month]['Coût des aliments']['STAT'] for month in months),
        },
        'Main d\'oeuvre': {
            'Équipiers': sum(monthly_data[month]['Main d\'oeuvre']['Équipiers'] for month in months),
            'Gestion': sum(monthly_data[month]['Main d\'oeuvre']['Gestion'] for month in months),
        }
    }
    
    # Calculer les totaux et pourcentages pour le trimestre
    quarter_data['Ventes']['Croissance'] = ((quarter_data['Ventes']['Actuel'] - quarter_data['Ventes']['Année précédente']) / 
                                           quarter_data['Ventes']['Année précédente'] * 100) if quarter_data['Ventes']['Année précédente'] > 0 else 0
    
    quarter_data['Coût des aliments']['Total'] = (quarter_data['Coût des aliments']['Perte brute'] + 
                                                 quarter_data['Coût des aliments']['Perte complétée'] + 
                                                 quarter_data['Coût des aliments']['Condiments'] + 
                                                 quarter_data['Coût des aliments']['Aliments employés'] + 
                                                 quarter_data['Coût des aliments']['STAT'])
    
    quarter_data['Coût des aliments']['Pourcentage'] = (quarter_data['Coût des aliments']['Total'] / 
                                                       quarter_data['Ventes']['Actuel'] * 100) if quarter_data['Ventes']['Actuel'] > 0 else 0
    
    quarter_data['Main d\'oeuvre']['Total'] = (quarter_data['Main d\'oeuvre']['Équipiers'] + 
                                             quarter_data['Main d\'oeuvre']['Gestion'])
    
    quarter_data['Main d\'oeuvre']['Pourcentage'] = (quarter_data['Main d\'oeuvre']['Total'] / 
                                                   quarter_data['Ventes']['Actuel'] * 100) if quarter_data['Ventes']['Actuel'] > 0 else 0
    
    # Calculer le FCFP moyen
    quarter_data['FCFP'] = sum(monthly_data[month]['FCFP'] for month in months) / len(months) if months else 0
    
    # Calculer le numérique moyen
    quarter_data['Numérique'] = sum(monthly_data[month]['Numérique'] for month in months) / len(months) if months else 0
    
    # Ajouter les objectifs
    objectives = {
        'Ventes': {
            'Croissance': 5.5,
            'Montant': 87482.02
        },
        'Coût des aliments': {
            'Pourcentage': 2.5,
            'Montant': 33861
        },
        'Main d\'oeuvre': {
            'Pourcentage': 25.0,
            'Montant': 338613.32
        },
        'FCFP': 140,
        'Numérique': 18.8
    }
    
    # Calculer les différences avec les objectifs
    differences = {
        'Ventes': objectives['Ventes']['Croissance'] - quarter_data['Ventes']['Croissance'],
        'Coût des aliments': objectives['Coût des aliments']['Pourcentage'] - quarter_data['Coût des aliments']['Pourcentage'],
        'Main d\'oeuvre': objectives['Main d\'oeuvre']['Pourcentage'] - quarter_data['Main d\'oeuvre']['Pourcentage'],
        'FCFP': objectives['FCFP'] - quarter_data['FCFP'],
        'Numérique': objectives['Numérique'] - quarter_data['Numérique']
    }
    
    # Définir les valeurs maximales et atteintes
    maximums = {
        'Ventes': {'Maximum': 30, 'Atteint': 0 if differences['Ventes'] < 0 else 30},
        'Coût des aliments': {'Maximum': 15, 'Atteint': 0 if differences['Coût des aliments'] < 0 else 15},
        'Main d\'oeuvre': {'Maximum': 20, 'Atteint': 20 if abs(differences['Main d\'oeuvre']) <= 1.2 else 0},
        'FCFP': {'Maximum': 20, 'Atteint': 20},
        'Numérique': {'Maximum': 15, 'Atteint': 0 if differences['Numérique'] < 0 else 15}
    }
    
    # Rassembler toutes les données
    dashboard_data = {
        'monthly': monthly_data,
        'quarterly': quarter_data,
        'objectives': objectives,
        'differences': differences,
        'maximums': maximums,
        'months': months
    }
    
    return dashboard_data

def categorize_food_cost(account_num):
    """Catégorise les coûts des aliments en fonction du numéro de compte."""
    mapping = {
        '51025-1': 'Perte brute',
        '51025-2': 'Perte complétée',
        '51025-3': 'Condiments',
        '51025-4': 'Aliments employés'
    }
    
    for prefix, category in mapping.items():
        if account_num.startswith(prefix):
            return category
    
    # Si le compte commence par 51 mais n'est pas dans le mapping, présumer STAT
    if account_num.startswith('51'):
        return 'STAT'
    
    return 'Autre'

def format_currency(value):
    """Formate un nombre en devise."""
    return f"${value:,.0f}" if value >= 10 else f"${value:.2f}"

def format_percentage(value):
    """Formate un nombre en pourcentage."""
    return f"{value:.2f}%"

# Interface utilisateur Streamlit
def main():
    st.title("Tableau de bord de performance restaurant")
    
    # Connexion à QuickBooks
    qb_client = connect_to_quickbooks()
    
    # Configuration de la période et du restaurant
    st.sidebar.header("Filtres")
    
    # Liste des trimestres disponibles
    current_year = datetime.now().year
    quarters = [
        f"T1 {current_year} (Jan-Mar)",
        f"T2 {current_year} (Avr-Jun)",
        f"T3 {current_year} (Jul-Sep)",
        f"T4 {current_year} (Oct-Déc)",
    ]
    
    selected_quarter = st.sidebar.selectbox("Trimestre", quarters)
    
    # Déterminer les dates de début et de fin en fonction du trimestre sélectionné
    if "T1" in selected_quarter:
        start_date = datetime(current_year, 1, 1)
        end_date = datetime(current_year, 3, 31)
    elif "T2" in selected_quarter:
        start_date = datetime(current_year, 4, 1)
        end_date = datetime(current_year, 6, 30)
    elif "T3" in selected_quarter:
        start_date = datetime(current_year, 7, 1)
        end_date = datetime(current_year, 9, 30)
    else:  # T4
        start_date = datetime(current_year, 10, 1)
        end_date = datetime(current_year, 12, 31)
    
    # Option pour personnaliser la période
    custom_period = st.sidebar.checkbox("Période personnalisée")
    if custom_period:
        start_date = st.sidebar.date_input("Date de début", start_date)
        end_date = st.sidebar.date_input("Date de fin", end_date)
    
    # Pour la démo, créons une liste de restaurants fictive
    # Dans une vraie application, vous récupéreriez cette liste de QuickBooks
    restaurants = ["HULL", "GATINEAU", "OTTAWA", "MONTREAL"]
    
    selected_restaurant = st.sidebar.selectbox("Restaurant", ["Tous"] + restaurants)
    selected_restaurant = None if selected_restaurant == "Tous" else selected_restaurant
    
    # Récupérer les données de QuickBooks
    if qb_client:
        # Bouton pour récupérer les données
        if st.sidebar.button("Actualiser les données"):
            with st.spinner("Récupération des données..."):
                qbo_data = get_qbo_data(qb_client, start_date, end_date)
                if qbo_data:
                    st.session_state.qbo_data = qbo_data
                    st.sidebar.success("Données récupérées avec succès!")
                else:
                    st.sidebar.error("Échec de la récupération des données.")
        
        # Si les données sont disponibles, traiter et afficher
        if 'qbo_data' in st.session_state:
            dashboard_data = process_data_for_dashboard(
                st.session_state.qbo_data, 
                start_date, 
                end_date, 
                selected_restaurant
            )
            
            if dashboard_data:
                # Afficher le tableau de bord
                display_dashboard(dashboard_data, selected_restaurant or "HULL")
            else:
                st.warning("Aucune donnée disponible pour la période et le restaurant sélectionnés.")
    else:
        # Mode démo pour le déploiement sans connexion à QuickBooks
        st.info("Mode démo sans connexion QuickBooks. Utilisation de données simulées.")
        
        # Générer des données fictives pour la démonstration
        demo_data = generate_demo_data(start_date, end_date, selected_restaurant or "HULL")
        if demo_data:
            display_dashboard(demo_data, selected_restaurant or "HULL")

def generate_demo_data(start_date, end_date, restaurant_name):
    """Génère des données de démonstration pour le tableau de bord"""
    # Générer les mois entre la date de début et de fin
    months = []
    current_date = start_date.replace(day=1)
    while current_date <= end_date:
        months.append(current_date.strftime('%Y-%m'))
        # Passer au mois suivant
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)
    
    # Simuler des données de ventes mensuelles
    monthly_data = {}
    for month in months:
        # Ventes
        month_sales = np.random.randint(450000, 600000)
        prev_month_sales = np.random.randint(400000, 550000)
        growth = ((month_sales - prev_month_sales) / prev_month_sales * 100)
        
        # Coûts des aliments
        food_costs = {
            'Perte brute': np.random.randint(2000, 5000),
            'Perte complétée': np.random.randint(1000, 3000),
            'Condiments': np.random.randint(3000, 7000),
            'Aliments employés': np.random.randint(1500, 4000),
            'STAT': np.random.randint(8000, 15000)
        }
        
        total_food_cost = sum(food_costs.values())
        food_cost_percent = (total_food_cost / month_sales * 100)
        
        # Coûts de main d'oeuvre
        labour_costs = {
            'Équipiers': np.random.randint(80000, 100000),
            'Gestion': np.random.randint(40000, 60000)
        }
        
        total_labour = sum(labour_costs.values())
        labour_percent = (total_labour / month_sales * 100)
        
        # FCFP et Numérique
        fcfp = np.random.randint(90, 130)
        numerique = np.random.uniform(15.0, 17.0)
        
        monthly_data[month] = {
            'Ventes': {
                'Actuel': month_sales,
                'Année précédente': prev_month_sales,
                'Croissance': growth
            },
            'Coût des aliments': {
                'Perte brute': food_costs['Perte brute'],
                'Perte complétée': food_costs['Perte complétée'],
                'Condiments': food_costs['Condiments'],
                'Aliments employés': food_costs['Aliments employés'],
                'STAT': food_costs['STAT'],
                'Total': total_food_cost,
                'Pourcentage': food_cost_percent
            },
            'Main d\'oeuvre': {
                'Équipiers': labour_costs['Équipiers'],
                'Gestion': labour_costs['Gestion'],
                'Total': total_labour,
                'Pourcentage': labour_percent
            },
            'FCFP': fcfp,
            'Numérique': numerique
        }
    
    # Calculer le total du trimestre
    quarter_data = {
        'Ventes': {
            'Actuel': sum(monthly_data[month]['Ventes']['Actuel'] for month in months),
            'Année précédente': sum(monthly_data[month]['Ventes']['Année précédente'] for month in months),
        },
        'Coût des aliments': {
            'Perte brute': sum(monthly_data[month]['Coût des aliments']['Perte brute'] for month in months),
            'Perte complétée': sum(monthly_data[month]['Coût des aliments']['Perte complétée'] for month in months),
            'Condiments': sum(monthly_data[month]['Coût des aliments']['Condiments'] for month in months),
            'Aliments employés': sum(monthly_data[month]['Coût des aliments']['Aliments employés'] for month in months),
            'STAT': sum(monthly_data[month]['Coût des aliments']['STAT'] for month in months),
        },
        'Main d\'oeuvre': {
            'Équipiers': sum(monthly_data[month]['Main d\'oeuvre']['Équipiers'] for month in months),
            'Gestion': sum(monthly_data[month]['Main d\'oeuvre']['Gestion'] for month in months),
        }
    }
    
    # Calculer les totaux et pourcentages pour le trimestre
    quarter_data['Ventes']['Croissance'] = ((quarter_data['Ventes']['Actuel'] - quarter_data['Ventes']['Année précédente']) / 
                                           quarter_data['Ventes']['Année précédente'] * 100) if quarter_data['Ventes']['Année précédente'] > 0 else 0
    
    quarter_data['Coût des aliments']['Total'] = (quarter_data['Coût des aliments']['Perte brute'] + 
                                                 quarter_data['Coût des aliments']['Perte complétée'] + 
                                                 quarter_data['Coût des aliments']['Condiments'] + 
                                                 quarter_data['Coût des aliments']['Aliments employés'] + 
                                                 quarter_data['Coût des aliments']['STAT'])
    
    quarter_data['Coût des aliments']['Pourcentage'] = (quarter_data['Coût des aliments']['Total'] / 
                                                       quarter_data['Ventes']['Actuel'] * 100) if quarter_data['Ventes']['Actuel'] > 0 else 0
    
    quarter_data['Main d\'oeuvre']['Total'] = (quarter_data['Main d\'oeuvre']['Équipiers'] + 
                                             quarter_data['Main d\'oeuvre']['Gestion'])
    
    quarter_data['Main d\'oeuvre']['Pourcentage'] = (quarter_data['Main d\'oeuvre']['Total'] / 
                                                   quarter_data['Ventes']['Actuel'] * 100) if quarter_data['Ventes']['Actuel'] > 0 else 0
    
    # Calculer le FCFP moyen
    quarter_data['FCFP'] = sum(monthly_data[month]['FCFP'] for month in months) / len(months) if months else 0
    
    # Calculer le numérique moyen
    quarter_data['Numérique'] = sum(monthly_data[month]['Numérique'] for month in months) / len(months) if months else 0
    
    # Ajouter les objectifs
    objectives = {
        'Ventes': {
            'Croissance': 5.5,
            'Montant': 87482.02
        },
        'Coût des aliments': {
            'Pourcentage': 2.5,
            'Montant': 33861
        },
        'Main d\'oeuvre': {
            'Pourcentage': 25.0,
            'Montant': 338613.32
        },
        'FCFP': 140,
        'Numérique': 18.8
    }
    
    # Calculer les différences avec les objectifs
    differences = {
        'Ventes': objectives['Ventes']['Croissance'] - quarter_data['Ventes']['Croissance'],
        'Coût des aliments': objectives['Coût des aliments']['Pourcentage'] - quarter_data['Coût des aliments']['Pourcentage'],
        'Main d\'oeuvre': objectives['Main d\'oeuvre']['Pourcentage'] - quarter_data['Main d\'oeuvre']['Pourcentage'],
        'FCFP': objectives['FCFP'] - quarter_data['FCFP'],
        'Numérique': objectives['Numérique'] - quarter_data['Numérique']
    }
    
    # Définir les valeurs maximales et atteintes
    maximums = {
        'Ventes': {'Maximum': 30, 'Atteint': 0 if differences['Ventes'] < 0 else 30},
        'Coût des aliments': {'Maximum': 15, 'Atteint': 0 if differences['Coût des aliments'] < 0 else 15},
        'Main d\'oeuvre': {'Maximum': 20, 'Atteint': 20 if abs(differences['Main d\'oeuvre']) <= 1.2 else 0},
        'FCFP': {'Maximum': 20, 'Atteint': 20},
        'Numérique': {'Maximum': 15, 'Atteint': 0 if differences['Numérique'] < 0 else 15}
    }
    
    # Rassembler toutes les données
    dashboard_data = {
        'monthly': monthly_data,
        'quarterly': quarter_data,
        'objectives': objectives,
        'differences': differences,
        'maximums': maximums,
        'months': months
    }
    
    return dashboard_data

def display_dashboard(data, restaurant_name):
    """Affiche le tableau de bord de style 'Résultats HULL'."""
    
    # Titre du tableau de bord
    st.header(f"Résultats {restaurant_name}")
    
    # Structure de base du tableau
    months = data['months']
    month_names = [datetime.strptime(m, '%Y-%m').strftime('%B').capitalize() for m in months]
    
    # Création du tableau principal
    col_headers = ["Critères"] + month_names + ["T1 (%)"] + ["T1 (%)"]
    
    # Largeur des colonnes (nombre de colonnes total + 1 pour la colonne fixe)
    col_width = 100 / (len(col_headers) + 5)  # +5 pour les colonnes d'objectifs et de déboursé
    
    # CSS personnalisé pour le tableau
    st.markdown(f"""
    <style>
    .dashboard-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
    }}
    .dashboard-table th, .dashboard-table td {{
        border: 1px solid #ddd;
        padding: 8px;
        text-align: right;
    }}
    .dashboard-table th {{
        background-color: #f2f2f2;
        font-weight: bold;
        text-align: center;
    }}
    .header-row {{
        background-color: #FFC107;
        font-weight: bold;
    }}
    .category-row {{
        background-color: #FFF8E1;
        font-weight: bold;
    }}
    .data-row {{
        background-color: #FFFDE7;
    }}
    .total-row {{
        background-color: #FFF8E1;
        font-weight: bold;
    }}
    .column-header {{
        width: {col_width}%;
    }}
    .objectives-section {{
        margin-left: 20px;
        width: {col_width * 3}%;
    }}
    .expense-section {{
        margin-left: 20px;
        width: {col_width * 2}%;
    }}
    </style>
    """, unsafe_allow_html=True)
    
    # Construction du tableau HTML
    html_table = f"""
    <table class="dashboard-table">
        <tr class="header-row">
            <th>Critères</th>
    """
    
    # En-têtes des mois
    for month in month_names:
        html_table += f"<th>{month}</th>"
    
    # En-têtes T1
    html_table += f"<th>T1 ($)</th><th>T1 (%)</th>"
    
    # En-têtes des objectifs
    html_table += f"<th>%</th><th>$</th><th>Différence</th>"
    
    # En-têtes des dépenses
    html_table += f"<th>Maximum</th><th>Atteint</th></tr>"
    
    # Section Ventes
    html_table += f"""
        <tr class="category-row">
            <td>Ventes</td>
            <td colspan="{len(month_names) + 8}"></td>
        </tr>
        <tr class="data-row">
            <td>2024</td>
    """
    
    # Données mensuelles des ventes
    for month in months:
        monthly_sales = data['monthly'][month]['Ventes']['Actuel']
        html_table += f"<td>${monthly_sales:,.0f}</td>"
    
    # Données trimestrielles des ventes
    quarterly_sales = data['quarterly']['Ventes']['Actuel']
    html_table += f"<td>${quarterly_sales:,.0f}</td><td></td>"
    
    # Objectifs des ventes (vides pour cette ligne)
    html_table += f"<td></td><td></td><td></td>"
    
    # Débours des ventes (vides pour cette ligne)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne année précédente
    html_table += f"""
        <tr class="data-row">
            <td>Année précédente</td>
    """
    
    # Données mensuelles année précédente
    for month in months:
        prev_year_sales = data['monthly'][month]['Ventes']['Année précédente']
        html_table += f"<td>${prev_year_sales:,.0f}</td>"
    
    # Données trimestrielles année précédente
    prev_year_quarterly = data['quarterly']['Ventes']['Année précédente']
    html_table += f"<td>${prev_year_quarterly:,.0f}</td><td></td>"
    
    # Objectifs année précédente (vides)
    html_table += f"<td></td><td></td><td></td>"
    
    # Débours année précédente (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne croissance
    html_table += f"""
        <tr class="data-row">
            <td>Croissance</td>
    """
    
    # Données mensuelles croissance
    for month in months:
        growth = data['monthly'][month]['Ventes']['Croissance']
        color = "red" if growth < 0 else "green"
        html_table += f"<td style='color:{color}'>{growth:.2f}%</td>"
    
    # Données trimestrielles croissance
    quarterly_growth = data['quarterly']['Ventes']['Croissance']
    color = "red" if quarterly_growth < 0 else "green"
    html_table += f"<td style='color:{color}'>{quarterly_growth:.2f}%</td><td></td>"
    
    # Objectifs croissance
    growth_objective = data['objectives']['Ventes']['Croissance']
    growth_amount = data['objectives']['Ventes']['Montant']
    growth_diff = data['differences']['Ventes']
    color = "red" if growth_diff < 0 else "green"
    html_table += f"<td>{growth_objective:.1f}%</td><td>${growth_amount:,.2f}</td><td style='color:{color}'>{growth_diff:.1f}%</td>"
    
    # Débours croissance
    growth_max = data['maximums']['Ventes']['Maximum']
    growth_achieved = data['maximums']['Ventes']['Atteint']
    html_table += f"<td>{growth_max}%</td><td>{growth_achieved}%</td></tr>"
    
    # Section Coût des aliments
    html_table += f"""
        <tr class="category-row">
            <td>Coût des aliments</td>
            <td colspan="{len(month_names) + 8}"></td>
        </tr>
    """
    
    # Lignes pour chaque catégorie de coût d'aliments
    food_cost_categories = ['Perte brute', 'Perte complétée', 'Condiments', 'Aliments employés', 'STAT']
    
    for category in food_cost_categories:
        html_table += f"""
            <tr class="data-row">
                <td>{category}</td>
        """
        
        # Données mensuelles par catégorie
        for month in months:
            category_amount = data['monthly'][month]['Coût des aliments'][category]
            html_table += f"<td>${category_amount:,.0f}</td>"
        
        # Données trimestrielles par catégorie
        quarterly_category = data['quarterly']['Coût des aliments'][category]
        
        # Calculer le pourcentage par rapport aux ventes pour ce trimestre
        if data['quarterly']['Ventes']['Actuel'] > 0:
            category_percent = quarterly_category / data['quarterly']['Ventes']['Actuel'] * 100
        else:
            category_percent = 0
            
        html_table += f"<td>${quarterly_category:,.0f}</td><td>{category_percent:.2f}%</td>"
        
        # Objectifs pour cette catégorie (si disponibles, sinon vides)
        if category == 'Perte brute':
            html_table += f"<td>0.50%</td><td></td><td></td>"
        elif category == 'Perte complétée':
            html_table += f"<td>0.25%</td><td></td><td></td>"
        elif category == 'Condiments':
            html_table += f"<td>1.00%</td><td></td><td></td>"
        elif category == 'Aliments employés':
            html_table += f"<td>0.40%</td><td></td><td></td>"
        elif category == 'STAT':
            html_table += f"<td>0.50%</td><td></td><td></td>"
        else:
            html_table += f"<td></td><td></td><td></td>"
        
        # Débours par catégorie (vides)
        html_table += f"<td></td><td></td></tr>"
    
    # Ligne Total ($) pour les coûts d'aliments
    html_table += f"""
        <tr class="total-row">
            <td>Total ($)</td>
    """
    
    # Totaux mensuels
    for month in months:
        total_food_cost = data['monthly'][month]['Coût des aliments']['Total']
        html_table += f"<td>${total_food_cost:,.0f}</td>"
    
    # Total trimestriel
    quarterly_food_cost = data['quarterly']['Coût des aliments']['Total']
    html_table += f"<td>${quarterly_food_cost:,.0f}</td><td></td>"
    
    # Objectifs totaux
    food_cost_obj_amount = data['objectives']['Coût des aliments']['Montant']
    html_table += f"<td></td><td>${food_cost_obj_amount:,.0f}</td><td></td>"
    
    # Débours totaux (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne Total (%) pour les coûts d'aliments
    html_table += f"""
        <tr class="total-row">
            <td>Total (%)</td>
    """
    
    # Pourcentages mensuels
    for month in months:
        food_cost_percent = data['monthly'][month]['Coût des aliments']['Pourcentage']
        html_table += f"<td>{food_cost_percent:.2f}%</td>"
    
    # Pourcentage trimestriel
    quarterly_food_cost_percent = data['quarterly']['Coût des aliments']['Pourcentage']
    html_table += f"<td>{quarterly_food_cost_percent:.2f}%</td><td></td>"
    
    # Objectif pourcentage
    food_cost_obj_percent = data['objectives']['Coût des aliments']['Pourcentage']
    food_cost_diff = data['differences']['Coût des aliments']
    color = "green" if food_cost_diff >= 0 else "red"
    html_table += f"<td>{food_cost_obj_percent:.2f}%</td><td></td><td style='color:{color}'>{food_cost_diff:.2f}%</td>"
    
    # Débours pourcentage
    food_cost_max = data['maximums']['Coût des aliments']['Maximum']
    food_cost_achieved = data['maximums']['Coût des aliments']['Atteint']
    html_table += f"<td>{food_cost_max}%</td><td>{food_cost_achieved}%</td></tr>"
    
    # Section Main d'oeuvre
    html_table += f"""
        <tr class="category-row">
            <td>Main d'oeuvre</td>
            <td colspan="{len(month_names) + 8}"></td>
        </tr>
    """
    
    # Ligne Équipiers ($)
    html_table += f"""
        <tr class="data-row">
            <td>M-O Équipiers, CdQ ($)</td>
    """
    
    # Données mensuelles Équipiers
    for month in months:
        crew_amount = data['monthly'][month]['Main d\'oeuvre']['Équipiers']
        html_table += f"<td>${crew_amount:,.0f}</td>"
    
    # Données trimestrielles Équipiers
    quarterly_crew = data['quarterly']['Main d\'oeuvre']['Équipiers']
    html_table += f"<td>${quarterly_crew:,.0f}</td><td></td>"
    
    # Objectifs Équipiers (vides)
    html_table += f"<td></td><td></td><td></td>"
    
    # Débours Équipiers (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne Équipiers (%)
    html_table += f"""
        <tr class="data-row">
            <td>M-O Équipiers, CdQ (%)</td>
    """
    
    # Pourcentages mensuels Équipiers
    for month in months:
        crew_amount = data['monthly'][month]['Main d\'oeuvre']['Équipiers']
        sales_amount = data['monthly'][month]['Ventes']['Actuel']
        crew_percent = (crew_amount / sales_amount * 100) if sales_amount > 0 else 0
        html_table += f"<td>{crew_percent:.1f}%</td>"
    
    # Pourcentage trimestriel Équipiers
    quarterly_crew = data['quarterly']['Main d\'oeuvre']['Équipiers']
    quarterly_sales = data['quarterly']['Ventes']['Actuel']
    quarterly_crew_percent = (quarterly_crew / quarterly_sales * 100) if quarterly_sales > 0 else 0
    html_table += f"<td>{quarterly_crew_percent:.1f}%</td><td></td>"
    
    # Objectifs Équipiers % (vides)
    html_table += f"<td></td><td></td><td></td>"
    
    # Débours Équipiers % (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne Gestion ($)
    html_table += f"""
        <tr class="data-row">
            <td>Gestion ($)</td>
    """
    
    # Données mensuelles Gestion
    for month in months:
        mgmt_amount = data['monthly'][month]['Main d\'oeuvre']['Gestion']
        html_table += f"<td>${mgmt_amount:,.0f}</td>"
    
    # Données trimestrielles Gestion
    quarterly_mgmt = data['quarterly']['Main d\'oeuvre']['Gestion']
    html_table += f"<td>${quarterly_mgmt:,.0f}</td><td></td>"
    
    # Objectifs Gestion (vides)
    html_table += f"<td></td><td></td><td></td>"
    
    # Débours Gestion (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne Gestion (%)
    html_table += f"""
        <tr class="data-row">
            <td>Gestion (%)</td>
    """
    
    # Pourcentages mensuels Gestion
    for month in months:
        mgmt_amount = data['monthly'][month]['Main d\'oeuvre']['Gestion']
        sales_amount = data['monthly'][month]['Ventes']['Actuel']
        mgmt_percent = (mgmt_amount / sales_amount * 100) if sales_amount > 0 else 0
        html_table += f"<td>{mgmt_percent:.1f}%</td>"
    
    # Pourcentage trimestriel Gestion
    quarterly_mgmt = data['quarterly']['Main d\'oeuvre']['Gestion']
    quarterly_mgmt_percent = (quarterly_mgmt / quarterly_sales * 100) if quarterly_sales > 0 else 0
    html_table += f"<td>{quarterly_mgmt_percent:.1f}%</td><td></td>"
    
    # Objectifs Gestion % (vides)
    html_table += f"<td></td><td></td><td></td>"
    
    # Débours Gestion % (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne Total ($) pour Main d'oeuvre
    html_table += f"""
        <tr class="total-row">
            <td>Total ($)</td>
    """
    
    # Totaux mensuels Main d'oeuvre
    for month in months:
        total_labour = data['monthly'][month]['Main d\'oeuvre']['Total']
        html_table += f"<td>${total_labour:,.0f}</td>"
    
    # Total trimestriel Main d'oeuvre
    quarterly_labour = data['quarterly']['Main d\'oeuvre']['Total']
    html_table += f"<td>${quarterly_labour:,.0f}</td><td></td>"
    
    # Objectifs totaux Main d'oeuvre
    labour_obj_amount = data['objectives']['Main d\'oeuvre']['Montant']
    html_table += f"<td></td><td>${labour_obj_amount:,.2f}</td><td></td>"
    
    # Débours totaux Main d'oeuvre (vides)
    html_table += f"<td></td><td></td></tr>"
    
    # Ligne Total (%) pour Main d'oeuvre
    html_table += f"""
        <tr class="total-row">
            <td>Total (%)</td>
    """
    
    # Pourcentages mensuels Main d'oeuvre
    for month in months:
        labour_percent = data['monthly'][month]['Main d\'oeuvre']['Pourcentage']
        html_table += f"<td>{labour_percent:.1f}%</td>"
    
    # Pourcentage trimestriel Main d'oeuvre
    quarterly_labour_percent = data['quarterly']['Main d\'oeuvre']['Pourcentage']
    html_table += f"<td>{quarterly_labour_percent:.1f}%</td><td></td>"
    
    # Objectif pourcentage Main d'oeuvre
    labour_obj_percent = data['objectives']['Main d\'oeuvre']['Pourcentage']
    labour_diff = data['differences']['Main d\'oeuvre']
    color = "green" if labour_diff >= 0 else "red"
    html_table += f"<td>{labour_obj_percent:.1f}%</td><td></td><td style='color:{color}'>{labour_diff:.1f}%</td>"
    
    # Débours pourcentage Main d'oeuvre
    labour_max = data['maximums']['Main d\'oeuvre']['Maximum']
    labour_achieved = data['maximums']['Main d\'oeuvre']['Atteint']
    html_table += f"<td>{labour_max}%</td><td>{labour_achieved}%</td></tr>"
    
    # Section FCFP
    html_table += f"""
        <tr class="category-row">
            <td>FCFP</td>
    """
    
    # Données mensuelles FCFP
    for month in months:
        fcfp_value = data['monthly'][month]['FCFP']
        html_table += f"<td>{fcfp_value}</td>"
    
    # Donnée trimestrielle FCFP
    quarterly_fcfp = data['quarterly']['FCFP']
    html_table += f"<td>{quarterly_fcfp:.0f}</td><td></td>"
    
    # Objectif FCFP
    fcfp_obj = data['objectives']['FCFP']
    fcfp_diff = data['differences']['FCFP']
    html_table += f"<td>{fcfp_obj}</td><td></td><td>{fcfp_diff}</td>"
    
    # Débours FCFP
    fcfp_max = data['maximums']['FCFP']['Maximum']
    fcfp_achieved = data['maximums']['FCFP']['Atteint']
    html_table += f"<td>{fcfp_max}%</td><td>{fcfp_achieved}%</td></tr>"
    
    # Section Numérique
    html_table += f"""
        <tr class="category-row">
            <td>Numérique</td>
    """
    
    # Données mensuelles Numérique
    for month in months:
        numeric_value = data['monthly'][month]['Numérique']
        html_table += f"<td>{numeric_value:.1f}%</td>"
    
    # Donnée trimestrielle Numérique
    quarterly_numeric = data['quarterly']['Numérique']
    html_table += f"<td>{quarterly_numeric:.2f}%</td><td></td>"
    
    # Objectif Numérique
    numeric_obj = data['objectives']['Numérique']
    numeric_diff = data['differences']['Numérique']
    color = "red" if numeric_diff < 0 else "green"
    html_table += f"<td>{numeric_obj:.1f}%</td><td></td><td style='color:{color}'>{numeric_diff:.2f}%</td>"
    
    # Débours Numérique
    numeric_max = data['maximums']['Numérique']['Maximum']
    numeric_achieved = data['maximums']['Numérique']['Atteint']
    html_table += f"<td>{numeric_max}%</td><td>{numeric_achieved}%</td></tr>"
    
    # Section Note Atteinte
    html_table += f"""
        <tr>
            <td colspan="{len(month_names) + 6}"></td>
            <td>Note Atteinte</td>
            <td>40%</td>
        </tr>
    """
    
    # Fin du tableau
    html_table += "</table>"
    
    # Afficher le tableau HTML
    st.markdown(html_table, unsafe_allow_html=True)
    
    # Graphiques supplémentaires
    st.subheader("Analyse des tendances")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Graphique de l'évolution des ventes
        st.subheader("Évolution des ventes")
        sales_data = {
            'Mois': month_names,
            'Ventes 2024': [data['monthly'][month]['Ventes']['Actuel'] for month in months],
            'Ventes année précédente': [data['monthly'][month]['Ventes']['Année précédente'] for month in months]
        }
        sales_df = pd.DataFrame(sales_data)
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(sales_df['Mois'], sales_df['Ventes 2024'], marker='o', color='blue', label='2024')
        ax.plot(sales_df['Mois'], sales_df['Ventes année précédente'], marker='s', color='orange', label='Année précédente')
        ax.set_ylabel('Ventes ($)')
        ax.set_xlabel('Mois')
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        
        for i, value in enumerate(sales_df['Ventes 2024']):
            ax.annotate(f"{value/1000:.0f}k", 
                        (i, value), 
                        textcoords="offset points", 
                        xytext=(0,10), 
                        ha='center')
        
        st.pyplot(fig)
    
    with col2:
        # Graphique des pourcentages de coûts
        st.subheader("Pourcentages des coûts")
        cost_data = {
            'Mois': month_names,
            'Coût des aliments (%)': [data['monthly'][month]['Coût des aliments']['Pourcentage'] for month in months],
            'Main d\'oeuvre (%)': [data['monthly'][month]['Main d\'oeuvre']['Pourcentage'] for month in months],
        }
        cost_df = pd.DataFrame(cost_data)
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(cost_df['Mois'], cost_df['Coût des aliments (%)'], color='gold', label='Coût des aliments (%)')
        ax.bar(cost_df['Mois'], cost_df['Main d\'oeuvre (%)'], bottom=cost_df['Coût des aliments (%)'], 
               color='green', label='Main d\'oeuvre (%)')
        
        ax.set_ylabel('Pourcentage des ventes (%)')
        ax.set_xlabel('Mois')
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        
        # Ligne d'objectif combiné
        combined_target = data['objectives']['Coût des aliments']['Pourcentage'] + data['objectives']['Main d\'oeuvre']['Pourcentage']
        ax.axhline(y=combined_target, color='red', linestyle='--', label=f'Objectif combiné ({combined_target}%)')
        
        st.pyplot(fig)

if __name__ == "__main__":
    main()