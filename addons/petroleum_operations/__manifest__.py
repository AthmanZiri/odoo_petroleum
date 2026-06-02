{
    'name': 'Petroleum Operations',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Back-to-back supplier sourcing, margins, depots and loading details for bulk fuel trading',
    'description': """
Petroleum Operations
====================
Operational customisations for the bulk-fuel brokerage workflow:

* Per sale-order-line supplier selection and negotiated buy price, with live
  margin (sell - buy) per line and per order.
* Back-to-back purchase orders are created from the chosen supplier and buy
  price instead of the product's first vendor.
* A Depot / Loading Point master, linked on sale orders, purchase orders and
  trips.
* Loading details (EPRA number, tanker compartment plan) captured on the trip
  and copied onto the purchase order / loading instruction.
* Relaxes the one-driver-per-truck and one-active-trip-per-truck hard blocks
  (kept as informational warnings) to match real daily operations.
""",
    'author': 'Jameel Petroleum',
    'license': 'LGPL-3',
    'depends': [
        'sale_order_trip_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/depot_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/trip_views.xml',
    ],
    'installable': True,
    'application': False,
}
