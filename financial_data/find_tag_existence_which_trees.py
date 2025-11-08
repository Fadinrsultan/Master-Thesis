from arelle import Cntlr, XbrlConst

# Initialize the Arelle controller
cntlr = Cntlr.Cntlr()

# Load the XBRL model (use the correct path to your XBRL file)
ENTRY_XSD = "/Users/fadisultan/Downloads/us-gaap-2025/entire/us-gaap-entryPoint-all-2025.xsd"
model_xbrl = cntlr.modelManager.load(ENTRY_XSD)

# Get the presentation relationships
pres = model_xbrl.relationshipSet(XbrlConst.parentChild)
''' "financials": {
  "2016-09-24": {
    "Revenues": 215639000000,
    "NetIncomeLoss": 9014000000,
    "EarningsPerShareBasic": 1.68,
    "EarningsPerShareDiluted": 1.67,
    "OperatingIncomeLoss": 60024000000,
    "GrossProfit": 17813000000,
    "ResearchAndDevelopmentExpense": 10045000000,
    "SellingGeneralAndAdministrativeExpense": 14194000000,
    "Assets": 321686000000,
    "Liabilities": 193437000000,
    "StockholdersEquity": 128249000000,
    "CashAndCashEquivalentsAtCarryingValue": 20484000000,
    "NetCashProvidedByUsedInOperatingActivities": 66231000000,
    "PaymentsToAcquirePropertyPlantAndEquipment": 12734000000,
    "ShortTermInvestments": {
      "ShortTermInvestments is not available, but I can offer AvailableForSaleSecuritiesCurrent as a replacement": 46671000000
    },
    "CostOfRevenue": 17813000000,
    "OperatingExpenses": 24239000000,
    "IncomeTaxExpenseBenefit": 15685000000,
    "AccountsReceivableNetCurrent": 15754000000,
    "FreeCashFlow": 53497000000
  }
}
'''

# List of tags you want to check
tags = [
    "Revenues",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "OperatingIncomeLoss",
    "GrossProfit",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "LongTermDebt",
    "ShortTermInvestments",
    "CostOfRevenue",
    "OperatingExpenses",
    "IncomeTaxExpenseBenefit",
    "AccountsReceivableNetCurrent"
]


# Function to find the network for a tag
def find_network_for_tag(tag):
    found_networks = []
    # Loop through all presentation relationships
    for rel in pres.modelRelationships:
        # Check if label or qname matches the tag
        label = rel.toModelObject.label(lang="en")
        qname = rel.toModelObject.qname
        if label and tag.lower() in label.lower():  # Match by label (case-insensitive)
            found_networks.append(rel.linkrole)
        elif tag.lower() in str(qname).lower():  # Match by qname (case-insensitive)
            found_networks.append(rel.linkrole)

    return found_networks if found_networks else ["Not Found"]


# Loop through each tag and find its network
for tag in tags:
    print(f"Checking for tag: {tag}")

    networks = find_network_for_tag(tag)

    if networks != ["Not Found"]:
        for network in networks:
            print(f"Tag: {tag} => Network: {network}")
    else:
        print(f"Tag: {tag} => Network: Not Found")

    print("\n" + "=" * 40 + "\n")
